"""The two WATCH writes (review 037a, decision b): saving a company's official pages and acknowledging a trigger.

Each runs in ONE short transaction (the caller's), after the pure checks (a bad request opens nothing) and
``ensure_intake_open`` (nothing is written on the live schema before the import), under ONE transaction-scoped
advisory lock ``<schema>.watch`` (the key derived from the schema name at run time), shared by both writes:

* ``set_target`` (the old ``watch.set_target``): the key is ``norm_company(name)``; the URLs are stripped, the empty
  ones dropped, the first 6 kept, each checked by the old regex (decision c: the private-host refusal happens at fetch,
  037b). Under the lock it reads the key's EFFECTIVE record (revision 2: its live row, otherwise the imported target),
  applies the old merge (a new record starts ``{name, added_at, checks: {}}``; ``name``, ``urls``, ``candidate_id``
  (the body's, else the record's), ``active`` (false only for a JSON ``false``) and ``updated_at`` are set; ``added_at``
  and ``checks`` are kept) and writes the whole record as the row. It never touches a candidate.
* ``acknowledge`` (the old ``watch.acknowledge``): the status first, then (under the lock) the trigger must exist in
  the overlaid log ("no such trigger"); one status line is appended. No state check, as before: acknowledging twice
  appends twice, and the last status line wins.

The timestamps are the old ``ledger.now_ts()``: naive Berlin wall time ``%Y-%m-%dT%H:%M:%S`` of the request clock.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.dealflow.ranking.names import norm_company
from projectzero.network.view import berlin_now
from projectzero.watch import log as watch_log
from projectzero.watch import targets as watch_targets

MAX_URLS = 6
NOTE_MAX = 300
STATUSES = ("reviewed", "dismissed")
TS_FORMAT = "%Y-%m-%dT%H:%M:%S"
URL_RE = re.compile(r"^https?://[^\s/]+\.[^\s]+")
LOCK = "{schema}.watch"


class WatchError(ValueError):
    """An operator-readable refusal (the old ``WatchError`` -> ``ApiError``: 400)."""

    status = 400


@dataclass(frozen=True)
class TargetRequest:
    name: str
    key: str
    urls: list[str]
    candidate_id: Any  # the body's value (the merge falls back to the record's when it is empty)
    active: bool


def now_ts(now: datetime) -> str:
    return berlin_now(now).strftime(TS_FORMAT)


def lock(conn: psycopg.Connection[Any], schema: str) -> None:
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (LOCK.format(schema=schema),))


# ------------------------------------------------------------------ pure
def parse_target(body: Mapping[str, Any]) -> TargetRequest:
    """The old checks in their order: the name, then each kept URL."""
    name = str(body.get("name") or "").strip()
    key = norm_company(name)
    if not key:
        raise WatchError("company name required")
    # H-379: only an ABSENT field defaults to the empty list (the old behaviour); every supplied value is validated,
    # so a malformed one (false, 0, "", {}, null) is a 400 and never clears the saved pages. [] still clears them.
    raw = body.get("urls", [])
    if not isinstance(raw, list) or not all(isinstance(u, str) for u in raw):
        raise WatchError("urls must be a list of strings")  # declared: the old code crashed (500) on these
    urls = [u.strip() for u in raw if u.strip()][:MAX_URLS]
    for u in urls:
        if not URL_RE.match(u):
            raise WatchError(f"not a public http(s) URL: {u}")
    return TargetRequest(name, key, urls, body.get("candidate_id"), body.get("active", True) is not False)


def merged(existing: Mapping[str, Any] | None, req: TargetRequest, ts: str) -> dict[str, Any]:
    """The old merge: the effective record (or a new one) updated in place, its key order kept."""
    t: dict[str, Any] = dict(existing) if existing is not None else {"name": req.name, "added_at": ts, "checks": {}}
    t.update(
        name=req.name,
        urls=list(req.urls),
        candidate_id=str(req.candidate_id or t.get("candidate_id") or ""),
        active=req.active,
        updated_at=ts,
    )
    return t


def parse_ack(body: Mapping[str, Any]) -> tuple[str, str, str]:
    tid = str(body.get("id") or "")
    status = body.get("status")
    if status not in STATUSES:
        raise WatchError("status must be reviewed or dismissed")
    return tid, str(status), str(body.get("note") or "")[:NOTE_MAX]


# ------------------------------------------------------------------ the writes
def set_target(conn: psycopg.Connection[Any], schema: str, body: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    req = parse_target(body)
    ensure_intake_open(conn, schema)  # the production write boundary: nothing before the import
    lock(conn, schema)
    record = merged(watch_targets.effective_record(conn, schema, req.key), req, now_ts(now))
    watch_targets.save_record(conn, schema, req.key, record)
    return {"ok": True, "target": record}


def acknowledge(conn: psycopg.Connection[Any], schema: str, body: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    tid, status, note = parse_ack(body)
    ensure_intake_open(conn, schema)
    lock(conn, schema)
    if not any(t["id"] == tid for t in watch_log.triggers(watch_log.load_events(conn, schema))):
        raise WatchError("no such trigger")
    row = {"kind": "status", "trigger_id": tid, "status": status, "at": now_ts(now), "note": note}
    watch_log.append_status(conn, schema, row)
    return {"ok": True, **row}
