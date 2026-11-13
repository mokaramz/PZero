"""The machine-triage runner (review 035b): the old ``shadow_triage.run`` over pz, one candidate at a time.

Decision (b) and plan revisions 2 and 3:

* **The model calls run with NO transaction and NO row lock open.** The caller holds the run lock (``records``), the
  run-at-a-time guard only.
* **Each candidate's outcome is ONE short transaction** (``_write``): 035a's locks (``lock_for_triage``: the company,
  then the candidate, a moved company retried), then the re-checks under them: the id still resolves to itself
  (not absorbed), the status is still ``new``, no operator verdict newer than its SELECTION MARK (the highest
  ``triage_decisions.seq`` of the survivor at selection: a KEEP committed after selection always has a greater seq),
  and the card's ``input_sha`` recomputed from the locked row equals the one the calls were made with. Then the
  previous current proposal is cleared and the new one inserted, the retry-state row set (an error) or cleared, and
  the disposition (``triage_run_items``) recorded — all together or nothing. A late result that lost to a newer
  state is never written: ``decided_meanwhile`` (status, verdict or absorption; not pending) or
  ``changed_meanwhile`` (a new card; pending, no attempt counted, re-selected as stale).
* **The skip rule** (``unchanged_skipped``) makes no call, and its disposition goes through the SAME locked write
  and re-checks before the next candidate (H-360): a skip judged on the run's snapshot whose card changed since is
  ``changed_meanwhile`` (pending, retryable, no attempt counted), never a final skip.
* **The same ``run_id`` and ``run_cap_usd`` on every call** (Flash, the veto and both schema retries): the gateway
  enforces the run cap only when both are given. A ``deadline`` (the scan job's 900 s) bounds every call.
* **Stop on ``must_stop``** (or the deadline): the candidate is not written; the caller accounts the rest.
* At the end the old ``runs[]`` summary is one ``triage_runs`` row (``usd`` from the ledger by ``run_id``).

The order is the old inbox order, here ``first_seen_at`` then ``id``. Stage 0 needs no call, so with paid calls off a
junk candidate BEFORE the first non-junk one still gets its proposal (decision c).
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.core.db import schema_ident, snapshot_transaction, transaction
from projectzero.core.inference import config as icfg
from projectzero.core.inference.gateway import Result
from projectzero.dealflow import workspaces
from projectzero.dealflow.candidates import DealFlowStore, DecisionError
from projectzero.dealflow.intake import postgres as intake_pg
from projectzero.dealflow.ranking.service import ranking_input
from projectzero.dealflow.triage import auto_rules, card, cascade, records
from projectzero.dealflow.triage import cascade_rules as rules

log = logging.getLogger(__name__)
_rules: Any = auto_rules  # the cut old code is untyped (see auto_rules.py)
TS_FORMAT = "%Y-%m-%dT%H:%M:%S"  # the old ``ledger.now_ts()``
LOCK_RETRIES = 3  # a moved company (the decision writer's 409) is retried with the new company's lock
DEADLINE_KIND = "deadline"
SKIP = "_skip"  # the skip rule's outcome as ``_write`` takes it: no proposal, the snapshot card's ``input_sha``


@dataclass
class Hooks:
    """Test seams: ``before_candidate(cid)`` runs before a candidate's cascade (before any call); ``before_write(cid)``
    after its calls and before its locked write; ``after_commit(cid, disposition)`` after its transaction
    committed."""

    before_candidate: Callable[[str], None] | None = None
    before_write: Callable[[str], None] | None = None
    after_commit: Callable[[str, str], None] | None = None


@dataclass
class Outcome:
    """What a run did: the old summary, and why it stopped (``stop_kind`` from the gateway's ``error_kind``)."""

    summary: dict[str, Any]
    stop_kind: str = ""
    stop_text: str = ""
    names: dict[str, Any] = field(default_factory=dict)


def ts(t: datetime) -> str:
    return t.strftime(TS_FORMAT)


def effective_model(config: Mapping[str, Any] | None = None, model: str | None = None) -> str:
    """The old ``effective_model``: the CHEAP role's configured model."""
    cfg = config if config is not None else icfg.load()
    return str(model or ((cfg.get("roles") or {}).get("CHEAP") or {}).get("model") or "")


def _candidates(conn: psycopg.Connection[Any], schema: str, ids: list[str]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            sql.SQL("select * from {}.candidates where id = any(%s) order by first_seen_at, id").format(
                schema_ident(schema)
            ),
            (list(ids),),
        )
        return list(cur.fetchall())


def undecided(conn: psycopg.Connection[Any], schema: str) -> list[dict[str, Any]]:
    """Every ``new`` candidate in the run order (the old ``_undecided()``: the inbox order)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            sql.SQL("select * from {}.candidates where status = 'new' order by first_seen_at, id").format(
                schema_ident(schema)
            )
        )
        return list(cur.fetchall())


def record_of(row: Mapping[str, Any]) -> dict[str, Any]:
    """The old-shaped record the cascade reads (``ranking_input``), with the candidate's id."""
    c, _ = ranking_input(row)
    c["id"] = row["id"]
    return c


def run(
    db_url: str,
    schema: str,
    *,
    run_id: str,
    ids: list[str],
    marks: Mapping[str, int],
    complete: Callable[..., Result],
    clock: Callable[[], datetime],
    now_naive: Callable[[], datetime],
    run_cap_usd: float = auto_rules.AUTO_RUN_CAP_USD,
    config: Mapping[str, Any] | None = None,
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    hooks: Hooks | None = None,
) -> Outcome:
    """One runner run over the selected ``ids`` (survivors), each with its selection mark. ``complete``: the gateway's
    ``complete`` with its injectables bound (store, env, providers, config, clock); ``clock``: the aware record clock;
    ``now_naive``: the retry state's naive Berlin clock (the old ``datetime.now()``)."""
    hooks = hooks or Hooks()
    mdl = effective_model(config)
    with snapshot_transaction(db_url) as conn:
        rows = _candidates(conn, schema, ids)
        prev = records.current_proposals(conn, schema, [str(r["id"]) for r in rows])
        override = workspaces.parse_override(records._document(conn, schema, "workspace_geos.json") or {})
    selected = [r for r in rows if r["status"] == "new"]  # the old ``_undecided()`` filtered by ``only_ids``
    counts: Counter[str] = Counter()
    stop_kind = stop_text = ""
    names = {str(r["id"]): record_of(r).get("name") for r in rows}

    def call(role: str, messages: list[dict[str, str]], **kw: Any) -> Result:
        return complete(role, messages, run_id=run_id, run_cap_usd=run_cap_usd, deadline=deadline, **kw)

    token = rules.OVERRIDE.set(override)
    try:
        for row in rows:
            cid = str(row["id"])
            if row["status"] != "new":  # decided after the selection, before this read: no call
                _settle(db_url, schema, run_id, cid, None, int(marks.get(cid, 0)), now_naive, names, hooks)
                continue
            if deadline is not None and monotonic() >= deadline:
                stop_kind, stop_text = DEADLINE_KIND, "the job's time limit was reached"
                break
            c = record_of(row)
            if hooks.before_candidate is not None:
                hooks.before_candidate(cid)
            out = cascade.triage_one(
                c, prev.get(cid), call=call, mdl=mdl, run_id=run_id, proposed_at=ts(clock()), counts=counts
            )
            if isinstance(out, cascade.Stop):
                stop_kind, stop_text = out.kind, out.text
                break
            if isinstance(out, cascade.Skipped):  # H-360: the skip is re-checked under the locks like any outcome
                skip = {SKIP: True, "input_sha": card.card_sha(c)}
                _settle(db_url, schema, run_id, cid, skip, int(marks.get(cid, 0)), now_naive, names, hooks, clock)
                continue
            if out.get("status") == "error" and out.get("error_kind") == DEADLINE_KIND:
                stop_kind, stop_text = DEADLINE_KIND, f"{out['error_kind']}: {out.get('error')}"
                break
            if hooks.before_write is not None:
                hooks.before_write(cid)
            _settle(db_url, schema, run_id, cid, out, int(marks.get(cid, 0)), now_naive, names, hooks, clock)
    finally:
        rules.OVERRIDE.reset(token)
    finished = clock()
    with transaction(db_url) as conn:
        intake_pg.ensure_intake_open(conn, schema)
        usd = records.run_usd(conn, schema, run_id)
        summary = cascade.run_summary(
            run_id=run_id,
            mdl=mdl,
            veto_model=cascade.VETO_MODEL,
            veto_thinking=False,
            finished=ts(finished),
            selected=len(selected),
            counts=counts,
            usd=usd,
            run_cap_usd=run_cap_usd,
            override_reason=None,
            stopped=stop_text,
        )
        records.insert_run(conn, schema, run_id, finished, summary)
    return Outcome(summary, stop_kind, stop_text, names)


def _settle(
    db_url: str,
    schema: str,
    run_id: str,
    cid: str,
    entry: dict[str, Any] | None,
    mark: int,
    now_naive: Callable[[], datetime],
    names: Mapping[str, Any],
    hooks: Hooks,
    clock: Callable[[], datetime] | None = None,
) -> str:
    """ONE transaction per candidate: the locks, the re-checks, then the write and its disposition (or the
    disposition alone). A moved company (409) is retried with fresh locks."""
    for attempt in range(1, LOCK_RETRIES + 1):
        try:
            with transaction(db_url) as conn:
                disposition = _write(conn, schema, run_id, cid, entry, mark, now_naive, names, clock)
            break
        except DecisionError as exc:
            if exc.status != 409 or attempt == LOCK_RETRIES:
                raise
            log.info("triage write for %s: the company moved meanwhile; retrying with fresh locks", cid)
    if hooks.after_commit is not None:
        hooks.after_commit(cid, disposition)
    return disposition


def _write(
    conn: psycopg.Connection[Any],
    schema: str,
    run_id: str,
    cid: str,
    entry: dict[str, Any] | None,
    mark: int,
    now_naive: Callable[[], datetime],
    names: Mapping[str, Any],
    clock: Callable[[], datetime] | None,
) -> str:
    intake_pg.ensure_intake_open(conn, schema)
    store = DealFlowStore(conn, schema)
    store.lock_for_triage(cid)  # the company, then the candidate (035a); a moved company: 409
    survivor = store.resolve_id("candidate", cid)
    if survivor != cid:
        records.insert_item(conn, schema, run_id, cid, "decided_meanwhile", {"why": "absorbed", "survivor": survivor})
        return "decided_meanwhile"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL("select * from {}.candidates where id = %s").format(schema_ident(schema)), (cid,))
        row = cur.fetchone()
    assert row is not None
    if row["status"] != "new":
        records.insert_item(conn, schema, run_id, cid, "decided_meanwhile", {"why": "status", "status": row["status"]})
        return "decided_meanwhile"
    seq = records.latest_seq(conn, schema, cid)
    if seq > mark:  # an operator verdict (a log-only KEEP included) committed after the selection
        records.insert_item(
            conn, schema, run_id, cid, "decided_meanwhile", {"why": "verdict", "seq": seq, "mark": mark}
        )
        return "decided_meanwhile"
    if entry is None or card.card_sha(record_of(row)) != entry.get("input_sha"):
        records.insert_item(conn, schema, run_id, cid, "changed_meanwhile", {"why": "card"})
        return "changed_meanwhile"
    if entry.get(SKIP):  # unchanged since the snapshot, re-checked under the locks: the old unchanged branch
        if records.retry_entry(conn, schema, cid) is not None:
            records.clear_retry(conn, schema, cid)  # (the old ``rs.pop``)
        records.insert_item(conn, schema, run_id, cid, "unchanged_skipped", {})
        return "unchanged_skipped"
    at = clock() if clock is not None else datetime.now().astimezone()
    records.write_proposal(conn, schema, entry, at)
    status = str(entry.get("status"))
    if status == "error":
        prior = records.retry_entry(conn, schema, cid)
        part = {cid: prior} if prior is not None else {}
        kind, raw = entry.get("error_kind"), entry.get("error")
        item = _rules._retry_item(part, cid, names.get(cid), kind, raw, now_naive())
        records.put_retry(conn, schema, cid, part[cid])
        records.insert_item(conn, schema, run_id, cid, "error", {"item": item, "kind": kind, "error": raw})
        return "error"
    if records.retry_entry(conn, schema, cid) is not None:
        records.clear_retry(conn, schema, cid)
    records.insert_item(conn, schema, run_id, cid, status, {"proposal": entry.get("proposal")})
    return status
