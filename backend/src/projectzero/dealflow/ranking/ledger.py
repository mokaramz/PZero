"""The feedback ledger's WRITE side (review 008): the old ``feedback.record_decision`` as decision events.

The old app rewrote ``feedback.json`` on every Deal Flow decision. Here the operator's status event carries what that
call recorded (``detail.feedback = {decision, source_ids, name}``, taken at decision time), and the ledger the
protected read rules see is rebuilt on read:

    effective = the imported ledger (byte-exact copy, so key order is the old file's)
                + every operator status event, replayed in event-id order with the old record_decision semantics

* a reviewed decision (kept / research / rejected / watch) sets ``decisions[candidate_id]``, replacing the entry in
  place (a dict assignment keeps the key's position, as in the old file);
* ``new`` (undo) / ``baseline`` removes it;
* no source ids -> nothing is recorded (the old early return): the entry is neither set nor removed.

Merged candidates (the import folds several old records into one survivor): the snapshot also lists every old id that
now resolves to the candidate (``keys``, survivor first). Applying a decision then drops the votes stored under the
absorbed ids, so the company counts once, and points Omar outcomes linked to an absorbed id at the survivor, so a Keep
plus an Omar outcome stays ONE reviewed company. Until the first new decision, the imported ledger is read as it is.

Omar's outcomes belong to the Conviction port and stay as imported.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from projectzero.dealflow.ranking import feedback

REVIEWED = ("kept", "research", "rejected", "watch")
OPERATOR = "Mohamed"
LEDGER_FILE = "feedback.json"  # path of the imported ledger in legacy_documents (relative to the old data folder)


def decision_record(c: Mapping[str, Any], decision: str, keys: list[str]) -> dict[str, Any]:
    """What the old ``record_decision`` captured from the candidate at decision time, plus the ledger keys that
    belong to it (its own id first, then the old ids merged into it)."""
    return {"decision": decision, "source_ids": feedback.source_ids_of(c), "name": c.get("name", ""), "keys": keys}


def ordered_keys(candidate_id: str, alias_ids: Iterable[str]) -> list[str]:
    """The ledger keys of a candidate: its own id first, then the old ids merged into it, sorted."""
    return [candidate_id, *sorted({str(a) for a in alias_ids} - {candidate_id})]


def has_snapshot(event: Mapping[str, Any]) -> bool:
    return isinstance((event.get("detail") or {}).get("feedback"), Mapping)


def parse_base(raw: bytes | memoryview | None, body: Any) -> Any:
    """The imported ledger. The byte-exact file keeps the old key order (jsonb does not); a missing or unreadable
    file falls back to the jsonb copy, and then to "no ledger" (None), like a missing feedback.json."""
    if raw is not None:
        try:
            return json.loads(bytes(raw).decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError):
            pass
    return body


def _ts(at: Any) -> str:
    return at.strftime("%Y-%m-%d %H:%M:%S") if isinstance(at, datetime) else str(at or "")


def effective(base: Any, events: Iterable[Mapping[str, Any]]) -> Any:
    """``events``: operator status events in event-id order, each ``{candidate_id, detail, at}``."""
    events = list(events)
    if not events:
        return base  # untouched: the read path then behaves exactly as with the imported file
    d = feedback.normalize(base)
    for ev in events:
        rec = (ev.get("detail") or {}).get("feedback")
        if not isinstance(rec, Mapping):
            continue  # pre-008 event the caller could not backfill (``service.backfill_snapshots``)
        sids = list(rec.get("source_ids") or [])
        cid = str(ev["candidate_id"])
        if not sids or not cid:
            continue  # the old early return: the prior vote (imported or earlier) stays
        absorbed = [str(k) for k in rec.get("keys") or [] if str(k) != cid]
        for key in absorbed:
            d["decisions"].pop(key, None)
        for outcome in d["omar"].values():
            if outcome.get("candidate_id") in absorbed:
                outcome["candidate_id"] = cid
        if rec.get("decision") in REVIEWED:
            d["decisions"][cid] = {"source_ids": sids, "decision": rec["decision"], "name": rec.get("name", ""),
                                   "ts": _ts(ev.get("at")), "by": OPERATOR}  # fmt: skip
        else:
            d["decisions"].pop(cid, None)
    return d
