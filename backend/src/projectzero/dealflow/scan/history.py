"""The ONE reader of the Deal Flow scan's results (review 034a): every view that showed the old ``scan_history.json``
or the old inbox's ``report`` / ``last_run`` / ``last_summary`` reads them here.

* ``scan_history``: the imported ``scan_history.json`` (the byte-exact archive in ``legacy_documents``, in its key
  order; else the ``documents`` row) OVERLAID by the new ``scan_runs`` rows, appended in run order, each the old
  history entry ``{**summary, "sources": [...]}``; then the old ``[-60:]`` (the old file kept the last 60 scans).
  The Deal Flow history route, System health (``last_scan``, the sources' last errors) and the runner's ``last()``
  all read it.
* ``latest``: the newest run's ``run_id``, ``report`` and ``summary``, else ``None`` (then the imported
  ``inbox.json#rest`` values stand: ``overlay_rest``).
* ``scan_history_view``: the old ``GET /api/scan_history?n=`` body.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from projectzero.core.db import schema_ident

SCAN_HISTORY_FILE = "scan_history.json"
SCAN_HISTORY_KEEP = 60
PIPELINE_EXISTING_LABEL = "Existing pipeline — not discovered in this scan"  # old services.pipeline


def _rows(conn: psycopg.Connection[Any], schema: str, query: str, params: Any = ()) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(query).format(s=schema_ident(schema)), params)
        return list(cur.fetchall())


def _parsed(raw: Any) -> Any:
    try:
        return json.loads(bytes(raw).decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None


def imported_history(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    """The imported ``scan_history.json`` as the old tolerant read gave it (absent or unreadable: no scans)."""
    rows = _rows(conn, schema, "select raw from {s}.legacy_documents where path = %s", (SCAN_HISTORY_FILE,))
    doc: Any = _parsed(rows[0]["raw"]) if rows else None
    if doc is None and not rows:
        docs = _rows(conn, schema, "select body from {s}.documents where key = %s", (SCAN_HISTORY_FILE,))
        doc = docs[0]["body"] if docs else None
    return doc if isinstance(doc, dict) else {"scans": []}


def runs(conn: psycopg.Connection[Any], schema: str) -> list[dict[str, Any]]:
    """The new runs in run order, as text (``json`` keeps the key order)."""
    return [
        {
            "run_id": r["run_id"],
            "summary": json.loads(r["summary"]),
            "report": json.loads(r["report"]),
            "sources": json.loads(r["sources"]),
        }
        for r in _rows(
            conn,
            schema,
            "select run_id, summary::text as summary, report::text as report, sources::text as sources "
            "from {s}.scan_runs order by id",
        )
    ]


def entry(run: Mapping[str, Any]) -> dict[str, Any]:
    """One history entry, as the old ingest appended it."""
    return {**run["summary"], "sources": run["sources"]}


def overlay(imported: Any, runs: list[dict[str, Any]]) -> dict[str, Any]:
    """The imported history with the new runs appended, trimmed to the last 60 (pure)."""
    base = imported if isinstance(imported, dict) else {"scans": []}
    scans = [s for s in (base.get("scans") or [])] if isinstance(base.get("scans"), list) else []
    if not runs:
        return base if isinstance(base.get("scans"), list) else {**base, "scans": scans}
    return {**base, "scans": (scans + [entry(r) for r in runs])[-SCAN_HISTORY_KEEP:]}


def scan_history(conn: psycopg.Connection[Any], schema: str, imported: Any = None) -> dict[str, Any]:
    """``imported``: the imported document when the caller already read it (``validation.inputs.load_docs``)."""
    base = imported if imported is not None else imported_history(conn, schema)
    return overlay(base, runs(conn, schema))


def latest(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any] | None:
    rows = _rows(
        conn,
        schema,
        "select run_id, summary::text as summary, report::text as report from {s}.scan_runs order by id desc limit 1",
    )
    if not rows:
        return None
    r = rows[0]
    return {"run_id": r["run_id"], "summary": json.loads(r["summary"]), "report": json.loads(r["report"])}


def overlay_rest(rest: Mapping[str, Any], last: Mapping[str, Any] | None) -> dict[str, Any]:
    """The imported ``inbox.json#rest`` with the latest run's ``last_run``, ``report`` and ``last_summary`` (pure)."""
    out = dict(rest)
    if last is not None:
        out["last_run"] = last["run_id"]
        out["report"] = last["report"]
        out["last_summary"] = last["summary"]
    return out


def scan_history_view(conn: psycopg.Connection[Any], schema: str, n: int) -> dict[str, Any]:
    """The old ``scan_history_view(n)``."""
    h = scan_history(conn, schema)
    scans = h.get("scans") or []
    return {
        "scans": scans[-max(1, min(60, n)) :],
        "total": len(scans),
        "pipeline_label": PIPELINE_EXISTING_LABEL,
    }
