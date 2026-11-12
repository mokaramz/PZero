"""The Postgres ``BudgetStore`` (review 029a, migration 0021): the gateway's ledger, reservations and cache.

Every method runs in ONE transaction under ``pg_advisory_xact_lock(hashtext('<schema>.model_budget'))``, so admissions
and settlements of every process are serialized and the next admitter always sees an attempt either as its
reservation or as its committed charge, never neither:

* ``admit``: reconcile the reservations with ``expires_at <= now`` (each becomes an ``abandoned`` ledger row charged its
  estimate, dated when it was reserved, inserted on (``call_id``, ``attempt``); then deleted), sum the ``Spend`` the
  rules read (the same sets as ``store.spend_of``: committed rows by window / role / entity / run, live reservations),
  run the pure ``budget.check``, and insert the reservation when admitted.
* ``settle``: insert the attempt's ledger row ``on conflict (call_id, attempt) where call_id is not null do nothing``
  (Codex H-267: the target matches the partial unique index) and delete its reservation; True when a row was written
  (False: a repeated or late settlement, nothing recorded).
* ``cache_get`` / ``cache_put``: ``model_cache`` (no TTL, as before; ``put`` keeps the first answer for a key).
* ``totals``: the budget summary sums.

The connection is opened per call (``db_url``) unless a caller passes one already inside its transaction.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from projectzero.core.db import schema_ident, transaction
from projectzero.core.inference import budget
from projectzero.core.inference.store import (
    Admission,
    AttemptRequest,
    CacheEntry,
    LedgerRow,
    Reservation,
    Settlement,
    Totals,
    abandoned_row,
    reservation_of,
)

_INSERT_ROW = (
    "insert into {s}.model_ledger (at, purpose, provider, model, entity_ref, usd, tokens_in, tokens_out, cached, "
    "outcome, detail) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "on conflict (call_id, attempt) where call_id is not null do nothing"
)
_RETIRE = "delete from {s}.model_reservations where call_id = %s and attempt = %s"
_SPEND = """
    select
      round(coalesce(sum(usd) filter (where at >= %(day0)s), 0), 6) as day,
      round(coalesce(sum(usd) filter (where at >= %(week0)s), 0), 6) as week,
      round(coalesce(sum(usd) filter (where at >= %(month0)s), 0), 6) as month,
      round(coalesce(sum(usd) filter (where role = %(role)s and at >= %(month0)s), 0), 6) as role_month,
      round(coalesce(sum(usd) filter (where %(entity)s::text is not null and entity_ref = %(entity)s), 0), 6) as entity,
      round(coalesce(sum(usd) filter (where %(run)s::text is not null and run_id = %(run)s), 0), 6) as run
    from {s}.model_ledger
"""
_PENDING = """
    select
      coalesce(sum(usd_estimate), 0) as pending,
      coalesce(sum(usd_estimate) filter (where role = %(role)s), 0) as pending_role,
      coalesce(sum(usd_estimate) filter (where %(entity)s::text is not null and entity_ref = %(entity)s), 0)
        as pending_entity,
      coalesce(sum(usd_estimate) filter (where %(run)s::text is not null and run_id = %(run)s), 0) as pending_run
    from {s}.model_reservations
"""


class PostgresBudgetStore:
    def __init__(self, db_url: str, schema: str) -> None:
        self.db_url = db_url
        self.schema = schema
        self.s = schema_ident(schema)

    @contextmanager
    def _locked(self) -> Iterator[psycopg.Connection[Any]]:
        with transaction(self.db_url) as conn:
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{self.schema}.model_budget",))
            yield conn

    # ---- the Protocol
    def admit(self, attempt: AttemptRequest) -> Admission:
        with self._locked() as conn:
            reconciled = self._reconcile(conn, attempt.now)
            if attempt.check:
                spend = self._spend(conn, attempt)
                reason = budget.check(
                    attempt.limits,
                    spend,
                    est_usd=attempt.est_usd,
                    role=attempt.role,
                    entity_id=attempt.entity_id,
                    run_id=attempt.run_id,
                    run_cap_usd=attempt.run_cap_usd,
                    override_reason=attempt.override_reason,
                    purpose=attempt.purpose,
                )
                if reason:
                    return Admission(False, reason, reconciled)
            self._reserve(conn, reservation_of(attempt))
            return Admission(True, "", reconciled)

    def settle(self, settlement: Settlement) -> bool:
        with self._locked() as conn:
            inserted = self._insert(conn, settlement.row)
            conn.execute(sql.SQL(_RETIRE).format(s=self.s), (settlement.call_id, settlement.attempt))
            return inserted

    def cache_get(self, key: str) -> CacheEntry | None:
        with transaction(self.db_url) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                sql.SQL("select key, provider, model, text, stored_at from {}.model_cache where key = %s").format(
                    self.s
                ),
                (key,),
            )
            r = cur.fetchone()
        return CacheEntry(r["key"], r["provider"], r["model"], r["text"], r["stored_at"]) if r else None

    def cache_put(self, entry: CacheEntry) -> None:
        with transaction(self.db_url) as conn:
            conn.execute(
                sql.SQL(
                    "insert into {}.model_cache (key, provider, model, text, stored_at) values (%s, %s, %s, %s, %s) "
                    "on conflict (key) do nothing"
                ).format(self.s),
                (entry.key, entry.provider, entry.model, entry.text, entry.stored_at),
            )

    def totals(self, now: datetime) -> Totals:
        day0, week0, month0 = budget.windows(now)
        with transaction(self.db_url) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                sql.SQL(
                    "select round(coalesce(sum(usd) filter (where at >= %s), 0), 6) as day, "
                    "round(coalesce(sum(usd) filter (where at >= %s), 0), 6) as week, "
                    "round(coalesce(sum(usd) filter (where at >= %s), 0), 6) as month, "
                    "round(coalesce(sum(usd), 0), 6) as all_time from {}.model_ledger"
                ).format(self.s),
                (day0, week0, month0),
            )
            t = cur.fetchone() or {}
            cur.execute(
                sql.SQL(
                    "select coalesce(role, 'None') as role, round(sum(usd), 6) as usd from {}.model_ledger group by 1"
                ).format(self.s)
            )
            by_role = {r["role"]: float(r["usd"] or 0) for r in cur.fetchall()}
            cur.execute(
                sql.SQL(
                    "select coalesce(outcome, 'None') as outcome, count(*) as n from {}.model_ledger group by 1"
                ).format(self.s)
            )
            outcomes = {r["outcome"]: int(r["n"]) for r in cur.fetchall()}
            cur.execute(
                sql.SQL(
                    "select count(*) as n, coalesce(sum(usd_estimate), 0) as usd from {}.model_reservations"
                ).format(self.s)
            )
            p = cur.fetchone() or {}
        return Totals(
            day=float(t.get("day") or 0),
            week=float(t.get("week") or 0),
            month=float(t.get("month") or 0),
            all_time=float(t.get("all_time") or 0),
            by_role=by_role,
            outcomes=outcomes,
            reservations=int(p.get("n") or 0),
            pending=float(p.get("usd") or 0),
        )

    # ---- inside the locked transaction
    def _insert(self, conn: psycopg.Connection[Any], row: LedgerRow) -> bool:
        cur = conn.execute(
            sql.SQL(_INSERT_ROW).format(s=self.s),
            (
                row.at,
                row.purpose,
                row.provider,
                row.model,
                row.entity_ref,
                row.usd,
                row.tokens_in,
                row.tokens_out,
                row.cached,
                row.outcome,
                Jsonb(dict(row.detail)),
            ),
        )
        return cur.rowcount == 1

    def _reserve(self, conn: psycopg.Connection[Any], res: Reservation) -> None:
        conn.execute(
            sql.SQL(
                "insert into {}.model_reservations (call_id, attempt, role, purpose, provider, model, entity_ref, "
                "run_id, "
                "usd_estimate, reserved_at, expires_at, detail) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            ).format(self.s),
            (
                res.call_id,
                res.attempt,
                res.role,
                res.purpose,
                res.provider,
                res.model,
                res.entity_id,
                res.run_id,
                res.usd,
                res.reserved_at,
                res.expires_at,
                Jsonb(dict(res.detail)),
            ),
        )

    def _reconcile(self, conn: psycopg.Connection[Any], now: datetime) -> int:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                sql.SQL(
                    "select * from {}.model_reservations where expires_at <= %s order by reserved_at, call_id, attempt"
                ).format(self.s),
                (now,),
            )
            expired = cur.fetchall()
        for r in expired:
            res = Reservation(
                call_id=r["call_id"], attempt=r["attempt"], usd=float(r["usd_estimate"]), role=r["role"],
                purpose=r["purpose"], provider=r["provider"], model=r["model"], entity_id=r["entity_ref"],
                run_id=r["run_id"], reserved_at=r["reserved_at"], expires_at=r["expires_at"], detail=r["detail"] or {},
            )  # fmt: skip
            self._insert(conn, abandoned_row(res))
            conn.execute(sql.SQL(_RETIRE).format(s=self.s), (res.call_id, res.attempt))
        return len(expired)

    def _spend(self, conn: psycopg.Connection[Any], attempt: AttemptRequest) -> budget.Spend:
        day0, week0, month0 = budget.windows(attempt.now)
        params = {"day0": day0, "week0": week0, "month0": month0, "role": attempt.role,
                  "entity": attempt.entity_id or None, "run": attempt.run_id or None}  # fmt: skip
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL(_SPEND).format(s=self.s), params)
            c = cur.fetchone() or {}
            cur.execute(sql.SQL(_PENDING).format(s=self.s), params)
            p = cur.fetchone() or {}
        return budget.Spend(
            day=float(c["day"]), week=float(c["week"]), month=float(c["month"]), role_month=float(c["role_month"]),
            entity=float(c["entity"]), run=float(c["run"]), pending=float(p["pending"]),
            pending_role=float(p["pending_role"]), pending_entity=float(p["pending_entity"]),
            pending_run=float(p["pending_run"]),
        )  # fmt: skip
