"""The operator's machine-triage decisions (review 035a): the old ``triage_review.decide`` and ``batch_reject`` over pz.

A machine proposal never becomes a decision by itself. Each action is one explicit operator decision, logged against
the machine proposal (``triage_decisions``, ``triage.log``), and every status change goes through the approved
decision path ``DealFlowStore.decide`` (both locks, ``expected_status``, the event with its feedback and sources
snapshot, the reopen guard). The old verdict mapping (``VERDICT_TO_INBOX``): REJECT -> ``rejected``, WATCH ->
``watch``, RESEARCH -> ``reviewing`` (the old ``research``, kept in the answer and the log line), KEEP -> no status
change (``open_keep``: the page opens the existing Keep drawer, whose Conviction save sets ``kept``).

* ``decide`` (decision a, revision 2): the id resolves to its survivor; ``DealFlowStore.lock_for_triage`` takes the
  company then the candidate lock and checks ``expected_status`` under them (409); the current proposal is read under
  the locks and the old validation runs (accept must equal it); REJECT / WATCH / RESEARCH decide in the SAME
  transaction (``expected_status`` = the locked status), then the line is appended. KEEP appends the line only. The
  decision and its line commit together (decision b): a failed insert rolls the status back. The event's ``reason``
  is ``machine triage: accept`` / ``override`` / ``batch_accept`` (additive). The old RESEARCH side effect (a paid
  case preparation) is not run (decision c).
* ``batch_reject`` (decision d, revision 2): the preview is one read-only snapshot. The confirm resolves and dedupes
  the ids (a raw id naming the same survivor as an earlier one: ``same candidate as another id``, declared), locks
  the distinct companies in company-id order then the candidates in candidate-id order
  (``lock_for_triage_batch``: a moved company is the retryable 409), re-reads eligibility under the locks from the
  same view build (log rows committed meanwhile included; a latest log-only KEEP is ``already decided``, declared),
  then decides and logs each eligible candidate in ONE transaction: all or nothing.

Errors are ``TriageError`` (400, the old texts) and ``DecisionError`` (the decision route's 404 / 409). The pure parts
(``parse_decide``, ``check_accept``, ``log_entry``, ``batch_ids``, ``ineligible``, ``classify_batch``) hold no
database work.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from projectzero.dealflow.candidates import DealFlowStore
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.dealflow.triage import log, view
from projectzero.network.view import berlin_now

VERDICTS = ("KEEP", "RESEARCH", "WATCH", "REJECT")
VERDICT_TO_INBOX: dict[str, str | None] = {"REJECT": "rejected", "WATCH": "watch", "RESEARCH": "research", "KEEP": None}
INBOX_TO_STATUS = {"rejected": "rejected", "watch": "watch", "research": "reviewing"}  # the new statuses
MODES = ("accept", "override")
TS_FORMAT = "%Y-%m-%dT%H:%M:%S"  # the old ``ledger.now_ts()``: naive Berlin wall time
NOTE_MAX = 500
NO_PROPOSAL = "no proposal"
ALREADY_DECIDED = "already decided"
NOT_OBVIOUS = "not an obvious reject (stale, flagged or single-model)"
SAME_CANDIDATE = "same candidate as another id"  # revision 2 (declared): the old batch deduped raw ids only


class TriageError(ValueError):
    """An operator-readable refusal (the old ``TriageError`` -> ``ApiError``: 400)."""

    status = 400


@dataclass(frozen=True)
class DecideRequest:
    candidate_id: str
    verdict: str
    mode: str
    note: str  # the logged note (``str(body.get("note") or "")``)
    notes: str | None  # what the decision saves as the candidate's notes (only a truthy note, as before)
    expected_status: str | None


# ------------------------------------------------------------------ pure
def parse_decide(body: Mapping[str, Any]) -> DecideRequest:
    """The old checks in their order: the verdict, then the mode (the candidate and its proposal come after)."""
    verdict = str(body.get("verdict") or "").upper()
    mode = str(body.get("mode") or "accept")
    if verdict not in VERDICTS:
        raise TriageError(f"verdict must be one of {', '.join(VERDICTS)}")
    if mode not in MODES:
        raise TriageError("mode must be accept or override")
    expected = body.get("expected_status")
    return DecideRequest(
        candidate_id=str(body.get("id") or ""),
        verdict=verdict,
        mode=mode,
        note=str(body.get("note") or ""),
        notes=str(body["note"]) if body.get("note") else None,
        expected_status=None if expected is None else str(expected),
    )


def check_accept(mode: str, verdict: str, proposal: Mapping[str, Any]) -> None:
    if mode == "accept" and verdict != proposal.get("proposal"):
        raise TriageError(
            f"accept means taking the machine proposal ({proposal.get('proposal')}); use override for {verdict}"
        )


def log_entry(
    c: Mapping[str, Any], p: Mapping[str, Any], verdict: str, mode: str, applied: str | None, note: str, ts: str
) -> dict[str, Any]:
    """The old ``_log`` line (its key set; ``log.line`` sorts the keys)."""
    return {
        "ts": ts,
        "candidate_id": c["id"],
        "name": c.get("name"),
        "machine": p.get("proposal"),
        "machine_path": p.get("path"),
        "machine_reject_basis": p.get("reject_basis"),
        "machine_model": p.get("model"),
        "machine_run_id": p.get("run_id"),
        "prompt_version": p.get("prompt_version"),
        "verdict": verdict,
        "mode": mode,
        "agreed": verdict == p.get("proposal"),
        "inbox_decision_applied": applied,
        "note": note[:NOTE_MAX],
    }


def batch_ids(body: Mapping[str, Any]) -> list[str]:
    """The raw ids, deduped in order (the old ``dict.fromkeys(str(i) for i in ids)``)."""
    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        raise TriageError("ids must be a non-empty list")
    return list(dict.fromkeys(str(i) for i in ids))


def batch_confirm(body: Mapping[str, Any]) -> bool:
    """H-351: only the JSON boolean ``true`` applies a batch; ``false`` or no ``confirm`` previews; anything else (the
    string ``"false"``, ``1``, ``null``) is a 400, so a malformed value can never apply rejections."""
    if "confirm" not in body or body["confirm"] is False:
        return False
    if body["confirm"] is True:
        return True
    raise TriageError("confirm must be true or false")


def parse_batch(body: Mapping[str, Any]) -> tuple[list[str], bool]:
    """The batch request's pure checks, before any connection: the ids, then ``confirm``."""
    return batch_ids(body), batch_confirm(body)


def log_only_keep(latest: Mapping[str, Any] | None) -> bool:
    """The latest verdict is a KEEP that changed no status (the Keep drawer may still be open): revision 2 reads it
    as decided, so a batch never rejects a candidate the operator just kept."""
    return bool(latest) and (latest or {}).get("verdict") == "KEEP" and not (latest or {}).get("inbox_decision_applied")


def ineligible(
    summary: Mapping[str, Any] | None, record: Mapping[str, Any] | None, latest: Mapping[str, Any] | None
) -> str | None:
    """Why a candidate is skipped by the batch (the old order of the checks), else ``None``."""
    if not summary or not record:
        return NO_PROPOSAL
    if record.get("decision") != "new" or log_only_keep(latest):
        return ALREADY_DECIDED
    if not summary["obvious_reject"]:
        return NOT_OBVIOUS
    return None


def classify_batch(
    ids: list[str],
    resolved: Mapping[str, str | None],
    summaries: Mapping[str, Any],
    records: Mapping[str, Mapping[str, Any]],
    latest: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], dict[str, int]]:
    """The eligible survivors (in id order of the request) and the skip counts (keys in first-seen order, as the old
    ``Counter``). ``resolved``: raw id -> survivor (``None``: unknown, the old "no proposal")."""
    eligible: list[str] = []
    skipped: Counter[str] = Counter()
    seen: set[str] = set()
    for raw in ids:
        sid = resolved.get(raw)
        if sid is not None and sid in seen:
            skipped[SAME_CANDIDATE] += 1
            continue
        if sid is not None:
            seen.add(sid)
        reason = NO_PROPOSAL if sid is None else ineligible(summaries.get(sid), records.get(sid), latest.get(sid))
        if reason:
            skipped[reason] += 1
        else:
            eligible.append(str(sid))
    return eligible, dict(skipped)


def now_ts(now: datetime) -> str:
    return berlin_now(now).strftime(TS_FORMAT)


# ------------------------------------------------------------------ pz
@dataclass(frozen=True)
class _Judged:
    inputs: view.TriageInputs
    summaries: dict[str, Any]
    records: dict[str, dict[str, Any]]
    latest: dict[str, dict[str, Any]]


def _judge(conn: psycopg.Connection[Any], schema: str, ids: list[str]) -> _Judged:
    """The view build over ``ids`` (their proposals and records, with the whole checker context and log)."""
    inp = view.load(conn, schema, only=ids)
    return _Judged(
        inputs=inp,
        summaries=view.build(inp)["proposals"],
        records={str(c["id"]): c for c in inp.candidates},
        latest=view.latest_verdicts(view.decisions(inp.decision_log), inp.aliases),
    )


def decide(conn: psycopg.Connection[Any], schema: str, body: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """One explicit operator decision, in the caller's transaction (the answer is only sent after it commits)."""
    req = parse_decide(body)
    ensure_intake_open(conn, schema)  # the production write boundary: nothing before the import
    store = DealFlowStore(conn, schema)
    resolved = store.resolve_id("candidate", req.candidate_id) if req.candidate_id else None
    if resolved is None:
        raise TriageError(f"unknown candidate {req.candidate_id!r}")
    locked = store.lock_for_triage(resolved, req.expected_status)
    j = _judge(conn, schema, [resolved])
    p = j.inputs.proposals.get(resolved)
    c = j.records.get(resolved)
    if c is None or not isinstance(p, dict) or p.get("status") not in view.OPEN_STATUSES:
        raise TriageError("this candidate has no machine proposal")
    check_accept(req.mode, req.verdict, p)
    applied = VERDICT_TO_INBOX[req.verdict]
    if applied:
        store.decide(
            resolved,
            INBOX_TO_STATUS[applied],
            reason=f"machine triage: {req.mode}",
            notes=req.notes,
            expected_status=locked["status"],
        )
    entry = log_entry(c, p, req.verdict, req.mode, applied, req.note, now_ts(now))
    log.append(conn, schema, resolved, entry, now)
    return {
        "ok": True,
        "verdict": req.verdict,
        "agreed": entry["agreed"],
        "inbox_decision": applied,
        "open_keep": req.verdict == "KEEP",
    }


def batch_reject(conn: psycopg.Connection[Any], schema: str, body: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """Preview (no ``confirm``, or ``false``) or apply (``confirm: true``) the batch acceptance of obvious machine
    REJECTs. The caller opens a ``snapshot_transaction`` for the preview (one read-only snapshot, H-351) and the write
    transaction for the confirm (its eligibility read, after the locks, sees what committed while it waited)."""
    ids, confirm = parse_batch(body)
    if confirm:
        ensure_intake_open(conn, schema)
    store = DealFlowStore(conn, schema)
    resolved = store.resolve_many(ids)
    survivors = list(dict.fromkeys(s for s in resolved.values() if s is not None))
    if confirm:
        store.lock_for_triage_batch(survivors)  # companies by id, then candidates by id; a moved company: 409
    j = _judge(conn, schema, survivors)  # read under the locks on confirm: the rows as they are now
    eligible, skipped = classify_batch(ids, resolved, j.summaries, j.records, j.latest)
    if not confirm:
        return {"ok": True, "preview": True, "eligible": len(eligible), "skipped": skipped}
    ts = now_ts(now)  # review 035d: set-based, a fixed number of statements, in the request order of ``eligible``
    store.reject_new_batch(eligible, reason="machine triage: batch_accept")
    log.append_many(
        conn,
        schema,
        [
            (sid, log_entry(j.records[sid], j.inputs.proposals[sid], "REJECT", "batch_accept", "rejected", "", ts))
            for sid in eligible
        ],
        now,
    )
    return {"ok": True, "applied": len(eligible), "skipped": skipped}
