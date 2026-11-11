"""Deal Flow read model and operator decisions — one candidate list for every origin (registry, Grok, Scout Intake,
Native Scout, manual).

* ``list_candidates`` — filters (status, origin, text), counts per status and origin, keyset paging. Default order is
  last observed first. The old attention ranking (Taste Map rules) is ported separately and will replace this order.
* ``get_candidate`` — one candidate with its company, identifiers, observations, events, machine proposals, routing,
  committee reviews and every id it is known by. Any old id resolves (``candidate`` / ``scout_intake`` /
  ``native_scout`` namespaces), so legacy deep links keep working.
* ``decide`` — the operator changes a status. ``kept`` is refused: Keep is the scored Conviction workflow, never a
  bare flag (old rule E2). Deciding the current status again changes nothing and says so. An optional
  ``expected_status`` guards against two tabs overwriting each other. Every change is one ``candidate_events`` row;
  source yield, feedback learning and case preparation will read those events instead of being side effects here.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from projectzero.core.db import schema_ident

STATUSES = ("new", "reviewing", "watch", "baseline", "rejected", "archived", "kept")
OPERATOR_STATUSES = frozenset({"new", "reviewing", "watch", "baseline", "rejected", "archived"})
CLOSED_STATUSES = frozenset({"rejected", "archived"})
ALIAS_NAMESPACES = ("candidate", "scout_intake", "native_scout")
MAX_PAGE = 200


class DecisionError(ValueError):
    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.extra = extra


@dataclass(frozen=True)
class ListQuery:
    status: tuple[str, ...] = ()
    origin: tuple[str, ...] = ()
    text: str | None = None
    limit: int = 50
    cursor: str | None = None

    def __post_init__(self) -> None:
        unknown = [s for s in self.status if s not in STATUSES]
        if unknown:
            raise DecisionError(400, f"unknown status {unknown[0]!r}", allowed=list(STATUSES))
        if not 1 <= self.limit <= MAX_PAGE:
            raise DecisionError(400, f"limit must be between 1 and {MAX_PAGE}")


def like_literal(text: str) -> str:
    """Escape ``text`` for a LIKE pattern so it only matches itself. The backslash (LIKE's escape character) goes first,
    or a name containing one could lose characters and a trailing backslash would swallow the appended wildcard."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def validate_operator_status(status: str) -> None:
    """The statuses an operator may set. Raises before any database work, so bad requests never open a connection."""
    if status == "kept":
        raise DecisionError(
            409, "Keep goes through the scored Conviction workflow, not a status change", keep_via="conviction"
        )
    if status not in OPERATOR_STATUSES:
        raise DecisionError(400, f"unknown status {status!r}", allowed=sorted(OPERATOR_STATUSES))


def _encode_cursor(last_observed_at: datetime, candidate_id: str) -> str:
    raw = json.dumps([last_observed_at.isoformat(), candidate_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        at, candidate_id = json.loads(base64.urlsafe_b64decode(padded.encode()))
        datetime.fromisoformat(at)
        return str(at), str(candidate_id)
    except (ValueError, TypeError) as exc:
        raise DecisionError(400, "invalid cursor") from exc


class DealFlowStore:
    def __init__(self, conn: psycopg.Connection[Any], schema: str = "pz") -> None:
        self.conn = conn
        self.s = schema_ident(schema)

    def _rows(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL(query).format(s=self.s), params)
            return list(cur.fetchall())

    def _first(self, query: str, params: Any = ()) -> dict[str, Any] | None:
        rows = self._rows(query, params)
        return rows[0] if rows else None

    # ── list ────────────────────────────────────────────────────────────────────────────────────────────────────
    def list_candidates(self, q: ListQuery) -> dict[str, Any]:
        where = ["true"]
        params: list[Any] = []
        if q.status:
            where.append("c.status = any(%s)")
            params.append(list(q.status))
        if q.origin:
            where.append("c.origins && %s")
            params.append(list(q.origin))
        if q.text:
            where.append("(c.name ilike %s or co.name ilike %s or c.key_fact ilike %s or c.description ilike %s)")
            like = f"%{like_literal(q.text)}%"
            params += [like] * 4
        filters = " and ".join(where)
        page_where = filters
        page_params = list(params)
        if q.cursor:
            at, candidate_id = _decode_cursor(q.cursor)
            page_where += " and (c.last_observed_at, c.id) < (%s::timestamptz, %s)"
            page_params += [at, candidate_id]
        items = self._rows(
            f"""
            select c.id, c.name, c.subject_kind, c.status, c.legacy_status, c.origins, c.country, c.location,
                   c.description, c.why, c.key_fact, c.key_unknown, c.recommended_object_type, c.sectors,
                   c.first_seen_at, c.last_observed_at, c.decided_at, c.attrs->>'identity' as identity,
                   case when co.id is null then null else jsonb_build_object(
                     'id', co.id, 'name', co.name, 'website', co.website, 'country', co.country) end as company,
                   (select count(*) from {{s}}.observations o where o.candidate_id = c.id) as observations,
                   exists(select 1 from {{s}}.candidate_events e
                          where e.candidate_id = c.id and e.action = 'merge_suggested') as merge_suggested,
                   (select jsonb_build_object('proposal', t.proposal, 'model', t.model, 'proposed_at', t.proposed_at)
                      from {{s}}.triage_proposals t where t.candidate_id = c.id and t.is_current) as triage,
                   (select jsonb_build_object('state', r.state, 'priority', r.priority, 'reason', r.reason)
                      from {{s}}.candidate_routing r where r.candidate_id = c.id) as routing
            from {{s}}.candidates c left join {{s}}.companies co on co.id = c.company_id
            where {page_where}
            order by c.last_observed_at desc, c.id desc
            limit %s
            """,
            [*page_params, q.limit + 1],
        )
        more = len(items) > q.limit
        items = items[: q.limit]
        counts = self._rows(
            f"""
            select 'status' as kind, c.status as key, count(*) as n
              from {{s}}.candidates c left join {{s}}.companies co on co.id = c.company_id where {filters} group by 2
            union all
            select 'origin', o, count(*)
              from {{s}}.candidates c left join {{s}}.companies co on co.id = c.company_id, unnest(c.origins) o
             where {filters} group by 2
            """,
            params + params,
        )
        return {
            "items": items,
            "next_cursor": _encode_cursor(items[-1]["last_observed_at"], items[-1]["id"]) if more else None,
            "counts": {
                "status": {r["key"]: r["n"] for r in counts if r["kind"] == "status"},
                "origin": {r["key"]: r["n"] for r in counts if r["kind"] == "origin"},
            },
        }

    # ── detail ──────────────────────────────────────────────────────────────────────────────────────────────────
    def resolve_id(self, namespace: str, alias_id: str) -> str | None:
        if namespace not in ALIAS_NAMESPACES:
            raise DecisionError(400, f"unknown id namespace {namespace!r}", allowed=list(ALIAS_NAMESPACES))
        rows = self._rows("select {s}.resolve_candidate(%s, %s) as id", (namespace, alias_id))
        resolved = rows[0]["id"] if rows else None
        return str(resolved) if resolved else None

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        found = self._rows("select * from {s}.candidates where id = %s", (candidate_id,))
        if not found:
            return None
        candidate = found[0]
        company_id = candidate["company_id"]
        detail: dict[str, Any] = {"candidate": candidate}
        detail["company"] = (
            self._first("select * from {s}.companies where id = %s", (company_id,)) if company_id else None
        )
        detail["identifiers"] = (
            self._rows(
                "select kind, namespace, value, strength, source from {s}.company_identifiers "
                "where company_id = %s order by strength, kind, value",
                (company_id,),
            )
            if company_id
            else []
        )
        detail["known_ids"] = self._rows(
            "select namespace, alias_id, reason from {s}.candidate_aliases where candidate_id = %s order by 1, 2",
            (candidate_id,),
        )
        detail["observations"] = self._rows(
            "select id, origin, source_id, observed_at, url, title, evidence, payload, submission_id "
            "from {s}.observations where candidate_id = %s order by observed_at desc, id desc",
            (candidate_id,),
        )
        detail["events"] = self._rows(
            "select id, actor, action, from_status, to_status, reason, detail, at "
            "from {s}.candidate_events where candidate_id = %s order by at desc, id desc",
            (candidate_id,),
        )
        detail["triage"] = self._rows(
            "select proposal, status, model, veto_model, usd, is_current, proposed_at, detail "
            "from {s}.triage_proposals where candidate_id = %s order by is_current desc, proposed_at desc",
            (candidate_id,),
        )
        detail["routing"] = self._first("select * from {s}.candidate_routing where candidate_id = %s", (candidate_id,))
        detail["committee"] = self._rows(
            "select seat, model, verdict, detail, reviewed_at from {s}.committee_reviews "
            "where candidate_id = %s order by reviewed_at desc",
            (candidate_id,),
        )
        detail["conviction"] = (
            self._first(
                "select id, slug, status, verified from {s}.conviction_entries where company_id = %s", (company_id,)
            )
            if company_id
            else None
        )
        return detail

    def _guard_reopen(self, candidate_id: str, company_id: str) -> None:
        """A company has at most one open candidate (``candidates_one_open_per_company``). Reopening a closed one while
        a sibling is open is refused with the sibling's id. The caller already holds the company lock, so two reopen
        attempts on two closed siblings run one after the other: the second sees the first one open and is refused."""
        sibling = self._first(
            "select id, status from {s}.candidates where company_id = %s and id <> %s "
            "and status not in ('rejected', 'archived')",
            (company_id, candidate_id),
        )
        if sibling:
            raise DecisionError(
                409,
                "this company already has an open candidate; decide on that one, or close it first",
                open_candidate=sibling["id"],
                open_status=sibling["status"],
            )

    def _lock_candidate(self, candidate_id: str) -> dict[str, Any]:
        """Lock in the ONE order every writer uses: company row first, then candidate row (review 005 rev 2).

        Live intake re-reports lock the company, then the candidate; deciding must not take them the other way round,
        or the two could deadlock. The candidate's company is read without a lock, that company is locked, then the
        candidate is locked and re-read. If the company changed in between (a merge), the decision is refused with 409
        at once: retrying inside this transaction would request a new company lock while holding the candidate lock
        (review 005 rev 3). The caller's transaction rolls back, so nothing is written; the client simply retries.
        """
        peek = self._first("select company_id from {s}.candidates where id = %s", (candidate_id,))
        if peek is None:
            raise DecisionError(404, "candidate not found")
        if peek["company_id"]:
            self._rows("select id from {s}.companies where id = %s for update", (peek["company_id"],))
        row = self._first("select status, company_id from {s}.candidates where id = %s for update", (candidate_id,))
        if row is None:
            raise DecisionError(404, "candidate not found")
        if row["company_id"] != peek["company_id"]:
            raise DecisionError(409, "the candidate moved to another company meanwhile; reload and decide again")
        return row

    # ── decisions ───────────────────────────────────────────────────────────────────────────────────────────────
    def decide(
        self,
        candidate_id: str,
        status: str,
        *,
        reason: str | None = None,
        notes: str | None = None,
        expected_status: str | None = None,
    ) -> dict[str, Any]:
        validate_operator_status(status)
        locked = self._lock_candidate(candidate_id)
        current, company_id = locked["status"], locked["company_id"]  # re-read under both locks
        if expected_status is not None and expected_status != current:
            raise DecisionError(409, "the candidate changed meanwhile; reload and decide again", current=current)
        if company_id and current in CLOSED_STATUSES and status not in CLOSED_STATUSES:
            self._guard_reopen(candidate_id, company_id)
        changed: Literal[True, False] = current != status
        if changed:
            self._rows(
                "update {s}.candidates set status = %s, decided_at = now() where id = %s returning id",
                (status, candidate_id),
            )
        if notes is not None:
            self._rows(
                "update {s}.candidates set attrs = attrs || jsonb_build_object('notes', %s::text) where id = %s "
                "returning id",
                (notes, candidate_id),
            )
        if changed or notes is not None:
            self._rows(
                "insert into {s}.candidate_events "
                "(candidate_id, actor, action, from_status, to_status, reason, detail) "
                "values (%s, 'operator', %s, %s, %s, %s, %s) returning id",
                (
                    candidate_id,
                    "status" if changed else "note",
                    current,
                    status if changed else None,
                    reason,
                    Jsonb({"notes": notes} if notes is not None else {}),
                ),
            )
        return {"id": candidate_id, "status": status, "previous_status": current, "changed": changed}
