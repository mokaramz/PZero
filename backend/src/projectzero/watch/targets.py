"""The ONE answer to "which companies are on WATCH, with which pages" (review 037a, plan revision 2).

* **The effective targets** (the old ``watch.load_targets()["targets"]``): the imported ``watch/targets.json``
  targets as the base (the byte-exact archive first, so the old key order survives; else the ``documents`` row; an
  unreadable file reads as no targets, the old ``tolerant`` load), overlaid by the ``watch_targets`` rows: a row wins
  for its key, keys only in rows follow in ``ord`` order (the old dict order).
* **The watched set** (decision a; the old ``watch.watched()``): every Deal Flow candidate whose status is ``watch``
  (Scout planner leads included: since Deal Flow and Scout Intake merged, they are WATCH candidates in Deal Flow), as
  the old inbox records in the old inbox order (an absorbed inbox record at its own archived position with the
  survivor's status, review 025b; the candidates without an archived position follow in the view order), keyed
  ``norm_company(name) or id``; then the ACTIVE effective targets (``setdefault``: a candidate wins).

Its readers: ``GET /api/watch`` (the view) and Health's watch counts. The pure parts (``watched``, ``overlay``) hold
no database work.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.conviction.records import records
from projectzero.core.db import schema_ident
from projectzero.dealflow import inbox_records
from projectzero.dealflow.inbox_view import candidate_rows
from projectzero.dealflow.ranking.names import norm_company
from projectzero.dealflow.triage.view import proposal_record

TARGETS = "watch/targets.json"
_ARCHIVE = "select raw from {}.legacy_documents where path = %s"
_DOCUMENT = "select body from {}.documents where key = %s"
_ROWS = "select key, record::text as record from {}.watch_targets order by ord"
_ROW = "select record::text as record from {}.watch_targets where key = %s"
_CURRENT = "select * from {}.triage_proposals where is_current"


# ------------------------------------------------------------------ pure
def targets_of(doc: Any) -> dict[str, dict[str, Any]]:
    """The ``targets`` of an old targets document (anything else: no targets; a non-object target is skipped)."""
    t = doc.get("targets") if isinstance(doc, dict) else None
    if not isinstance(t, dict):
        return {}
    return {str(k): v for k, v in t.items() if isinstance(v, dict)}


def overlay(imported: Mapping[str, dict[str, Any]], rows: Iterable[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """The imported targets, each key's row winning (in place), then the keys only in rows (in row order)."""
    out = {k: copy.deepcopy(v) for k, v in imported.items()}
    for key, record in rows:
        out[key] = copy.deepcopy(record)
    return out


def watched(candidates: Any, targets: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The old ``watch.watched()`` over old-format candidate records and the effective targets."""
    out: dict[str, dict[str, Any]] = {}
    for c in records(candidates, ("id",)):
        if c.get("decision") == "watch" and c.get("name"):
            out[norm_company(c["name"]) or c["id"]] = {"name": c["name"], "candidate_id": c["id"], "candidate": c}
    for k, t in targets.items():
        if isinstance(t, dict) and t.get("active", True):
            out.setdefault(
                k, {"name": t.get("name") or k, "candidate_id": t.get("candidate_id") or "", "candidate": None}
            )
    return out


# ------------------------------------------------------------------ the database
def _parse(raw: Any) -> Any:
    try:
        return json.loads(bytes(raw).decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None


def imported_targets(conn: psycopg.Connection[Any], schema: str) -> dict[str, dict[str, Any]]:
    s = schema_ident(schema)
    row = conn.execute(sql.SQL(_ARCHIVE).format(s), (TARGETS,)).fetchone()
    if row is not None:
        return targets_of(_parse(row[0]))
    doc = conn.execute(sql.SQL(_DOCUMENT).format(s), (TARGETS,)).fetchone()
    return targets_of(doc[0] if doc else None)


def target_rows(conn: psycopg.Connection[Any], schema: str) -> list[tuple[str, dict[str, Any]]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(_ROWS).format(schema_ident(schema)))
        return [(str(r["key"]), json.loads(r["record"])) for r in cur.fetchall()]


def effective_targets(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    return overlay(imported_targets(conn, schema), target_rows(conn, schema))


def effective_record(conn: psycopg.Connection[Any], schema: str, key: str) -> dict[str, Any] | None:
    """One key's effective record: its live row if there is one, otherwise the imported target (revision 2)."""
    row = conn.execute(sql.SQL(_ROW).format(schema_ident(schema)), (key,)).fetchone()
    if row is not None:
        found: dict[str, Any] = json.loads(row[0])
        return found
    return imported_targets(conn, schema).get(key)


def save_record(conn: psycopg.Connection[Any], schema: str, key: str, record: Mapping[str, Any]) -> None:
    """The whole record as the key's row (in the caller's transaction, under the watch lock)."""
    conn.execute(
        sql.SQL(
            "insert into {s}.watch_targets (key, record) values (%s, %s::json) "
            "on conflict (key) do update set record = excluded.record, updated_at = now()"
        ).format(s=schema_ident(schema)),
        (key, json.dumps(dict(record), ensure_ascii=False)),
    )


def watch_candidates(conn: psycopg.Connection[Any], schema: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The candidates on WATCH as old inbox records (decision a: every candidate row, Scout planner leads included),
    and the CURRENT machine proposal of each record's survivor, keyed by the record's id (and the survivor's)."""
    rows = [r for r in candidate_rows(conn, schema) if r.get("status") == "watch"]
    old = inbox_records.old_inbox(rows, inbox_records.load_absorbed(conn, schema))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(_CURRENT).format(schema_ident(schema)))
        current = {str(r["candidate_id"]): proposal_record(r) for r in cur.fetchall()}
    proposals = inbox_records.proposals_of(old, current)
    for cid, p in current.items():
        proposals.setdefault(cid, p)  # a manual target may name its candidate by the survivor id
    return [r.record for r in old], proposals
