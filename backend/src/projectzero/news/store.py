"""The News tables (review 028b, migration 0019): the events document and the action log, read and written.

* ``events_doc``: the old ``news/events.json`` rebuilt from ``news_events_rest`` (the top-level keys in their archived
  order, ``events`` at its own position) and ``news_events`` (the events in ``pos`` order, each record's own key
  order); ``None`` when nothing was imported (the old missing file).
* ``event_count``: the number of stored events (the refresh status's ``events_total``).
* ``actions_text``: the old ``news/actions.jsonl``, its lines in ``seq`` order (a NULL line, which text could not hold,
  is an empty line, skipped on read as before).
* ``lock``: the production boundary (409 before the import) and the News write lock. The one lock order is intake,
  then news, then validation (``validation.store.lock``).
* ``ensure_seeded``: the old ``seed_cases`` with the old view's guard, STORED (028a decision a, completed): each new or
  refreshed curated event is written with a ``seed`` history row, and the ``seeded`` list is updated; idempotent. It
  runs inside the caller's transaction, so a refusal later in that transaction rolls the seed back too.
* ``save_event`` / ``append_action``: one write's rows.
* ``log_texts`` / ``documents`` (review 028c, migration 0020): the run's logs (``news/{runs,disagreements,source_log,
  source_history,weekly}.jsonl``, lines in ``seq`` order) and documents (``news/{source_metrics,source_state,
  feeds_extra,run_state,feed_cooldown}.json``, json in their key order); ``append_log`` / ``save_document`` write them.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json, Jsonb

from projectzero.core.db import schema_ident
from projectzero.dealflow.intake.postgres import ensure_intake_open
from projectzero.news.core import load, seed_cases
from projectzero.news.inputs_model import Cases


def _rows(conn: psycopg.Connection[Any], query: str, schema: str, params: Any = ()) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql.SQL(query).format(s=schema_ident(schema)), params)
        return list(cur.fetchall()) if cur.description else []


def events_doc(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any] | None:
    rest = _rows(conn, "select body from {s}.news_events_rest", schema)
    rows = _rows(conn, "select event_id, record from {s}.news_events order by pos", schema)
    events = {str(r["event_id"]): r["record"] for r in rows}
    if not rest and not events:
        return None
    body: dict[str, Any] = dict(rest[0]["body"]) if rest and isinstance(rest[0]["body"], dict) else {}
    if "events" in body or events:
        body["events"] = events  # at its archived position (a new key goes last)
    return body


def event_count(conn: psycopg.Connection[Any], schema: str) -> int:
    row = _rows(conn, "select count(*) as n from {s}.news_events", schema)
    return int(row[0]["n"]) if row else 0


def actions_text(conn: psycopg.Connection[Any], schema: str) -> str:
    rows = _rows(conn, "select line from {s}.news_actions order by seq", schema)
    return "".join(("" if r["line"] is None else str(r["line"])) + "\n" for r in rows)


def lock(conn: psycopg.Connection[Any], schema: str) -> None:
    ensure_intake_open(conn, schema)  # the production write boundary: nothing before the import
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{schema}.news",))


def append_action(conn: psycopg.Connection[Any], schema: str, line: str) -> None:
    conn.execute(
        sql.SQL("insert into {}.news_actions (line, source) values (%s, 'app')").format(schema_ident(schema)), (line,)
    )


def save_event(
    conn: psycopg.Connection[Any],
    schema: str,
    event_id: str,
    record: dict[str, Any],
    action: str,
    detail: dict[str, Any],
) -> None:
    """Write one event's current record (a new event goes after every stored one) and its history row."""
    s = schema_ident(schema)
    before = conn.execute(
        sql.SQL("select record from {}.news_events where event_id = %s").format(s), (event_id,)
    ).fetchone()
    if before is None:
        conn.execute(
            sql.SQL(
                "insert into {s}.news_events (event_id, pos, record) "
                "values (%s, (select coalesce(max(pos), -1) + 1 from {s}.news_events), %s)"
            ).format(s=s),
            (event_id, Json(record)),
        )
    else:
        conn.execute(
            sql.SQL("update {}.news_events set record = %s, updated_at = now() where event_id = %s").format(s),
            (Json(record), event_id),
        )
    conn.execute(
        sql.SQL(
            "insert into {}.news_event_history (event_id, action, before, after, detail) values (%s, %s, %s, %s, %s)"
        ).format(s),
        (event_id, action, Json(before[0]) if before else None, Json(record), Jsonb(detail)),
    )


def save_rest(conn: psycopg.Connection[Any], schema: str, doc: dict[str, Any]) -> None:
    body = {k: (None if k == "events" else v) for k, v in doc.items()}
    conn.execute(
        sql.SQL(
            "insert into {}.news_events_rest (body) values (%s) "
            "on conflict (singleton) do update set body = excluded.body, updated_at = now()"
        ).format(schema_ident(schema)),
        (Json(body),),
    )


def ensure_seeded(conn: psycopg.Connection[Any], schema: str, cases: Cases | None, now: datetime) -> int:
    """Store the curated seeding the reads apply in memory; returns how many events were written."""
    doc = events_doc(conn, schema) or {}
    if cases is None or not isinstance(doc, dict) or len(load(doc)["seeded"]) >= len(cases):
        return 0  # the old view's guard: nothing to seed
    seeded, added = seed_cases(doc, cases, now)
    if not added:
        return 0
    old_events = load(doc)["events"]
    written = 0
    for event_id, record in seeded["events"].items():
        if json.dumps(old_events.get(event_id), ensure_ascii=False) != json.dumps(record, ensure_ascii=False):
            save_event(conn, schema, event_id, record, "seed", {"seeded": event_id in seeded["seeded"]})
            written += 1
    save_rest(conn, schema, seeded)
    return written


# ── the run's logs and documents (review 028c, migration 0020) ─────────────────────────────────────────────────────
LOGS = {
    "runs": "news/runs.jsonl",
    "disagreements": "news/disagreements.jsonl",
    "source_log": "news/source_log.jsonl",
    "source_history": "news/source_history.jsonl",
    "weekly": "news/weekly.jsonl",
    "run_notes": "news/run_notes.jsonl",  # new in 028c: what each run deferred (read by no view)
}
DOCUMENTS = (
    "news/source_metrics.json",
    "news/source_state.json",
    "news/feeds_extra.json",
    "news/run_state.json",
    "news/feed_cooldown.json",
)


def log_texts(conn: psycopg.Connection[Any], schema: str, logs: tuple[str, ...] = tuple(LOGS)) -> dict[str, str]:
    """``{old path: text}`` for ``logs``; a log without rows is ``""`` (the old missing file)."""
    lines: dict[str, list[str]] = {log: [] for log in logs}
    query = "select log, line from {s}.news_logs where log = any(%s) order by seq"
    for r in _rows(conn, query, schema, (list(logs),)):
        lines[str(r["log"])].append("" if r["line"] is None else str(r["line"]))
    return {LOGS[log]: "".join(line + "\n" for line in rows) for log, rows in lines.items()}


def documents(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    """``{old path: body}`` for the stored run documents (an absent one is the old missing file)."""
    return {str(r["key"]): r["body"] for r in _rows(conn, "select key, body from {s}.news_documents", schema)}


def append_log(conn: psycopg.Connection[Any], schema: str, log: str, line: str) -> None:
    if log not in LOGS:
        raise ValueError(f"unknown News log {log!r}")
    conn.execute(
        sql.SQL("insert into {}.news_logs (log, line, source) values (%s, %s, 'app')").format(schema_ident(schema)),
        (log, line),
    )


def save_document(conn: psycopg.Connection[Any], schema: str, key: str, body: Any) -> None:
    conn.execute(
        sql.SQL(
            "insert into {}.news_documents (key, body) values (%s, %s) "
            "on conflict (key) do update set body = excluded.body, updated_at = now()"
        ).format(schema_ident(schema)),
        (key, Json(body)),
    )


RUN_LOCK = "{schema}.news.refresh"  # the SESSION advisory lock one refresh or evaluation run holds (review 028c)
_RUN_ACTIVE = (
    "select exists (select 1 from pg_locks where locktype = 'advisory' and granted and objsubid = 1 "
    "and ((classid::bigint << 32) | objid::bigint) = hashtext(%s)::bigint) as active"
)


def run_active(conn: psycopg.Connection[Any], schema: str) -> bool:
    """Whether a refresh or evaluation run holds its session lock right now (the status's ``job.running``)."""
    row = conn.execute(_RUN_ACTIVE, (RUN_LOCK.format(schema=schema),)).fetchone()
    return bool(row and row[0])


def save_event_passes(
    conn: psycopg.Connection[Any],
    schema: str,
    event_id: str,
    record: dict[str, Any],
    states: list[tuple[str, dict[str, Any]]],
    detail: dict[str, Any],
) -> None:
    """A run's change to one event (review 028c, Codex H-261): the final record written once, and one history row per
    pass with THAT pass's resulting state, chained (each row's ``before`` is the previous row's ``after``; the first
    row's ``before`` is the stored record, null for a new event; the last ``after`` equals the stored record)."""
    s = schema_ident(schema)
    row = conn.execute(
        sql.SQL("select record from {}.news_events where event_id = %s").format(s), (event_id,)
    ).fetchone()
    before: Any = row[0] if row else None
    if row is None:
        conn.execute(
            sql.SQL(
                "insert into {s}.news_events (event_id, pos, record) "
                "values (%s, (select coalesce(max(pos), -1) + 1 from {s}.news_events), %s)"
            ).format(s=s),
            (event_id, Json(record)),
        )
    else:
        conn.execute(
            sql.SQL("update {}.news_events set record = %s, updated_at = now() where event_id = %s").format(s),
            (Json(record), event_id),
        )
    for action, after in states:
        conn.execute(
            sql.SQL(
                "insert into {}.news_event_history (event_id, action, before, after, detail) "
                "values (%s, %s, %s, %s, %s)"
            ).format(s),
            (event_id, action, Json(before) if before is not None else None, Json(after), Jsonb(detail)),
        )
        before = after
