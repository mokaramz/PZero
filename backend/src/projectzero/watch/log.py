"""The ONE reader of the WATCH trigger log (review 037a): the old ``watch/triggers.jsonl``.

The imported file is the byte-exact archive (``legacy_documents``); the lines written since are ``watch_events`` rows,
each holding the old line (sorted keys, ``json`` so the text is byte-kept). Every reader (Conviction's re-open
evidence, Today's WATCH actions, Home, Health's counts, the Map's WATCH layer and the Watchlist) reads the archived
lines FIRST, then the rows ``order by seq``: the log as the old file would have read after the appends. The lines are
parsed by the old rules (``conviction.operator.watch_triggers``): a line that is not a JSON object is skipped, a
trigger's CURRENT status is its last status line.

The archive is decoded as the importer reads it (``utf-8-sig``: an optional leading BOM never hides the first record,
the Map's rule since Codex H-201); undecodable bytes read as an empty log (the old ``storage.read_text``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg import sql

from projectzero.conviction.operator import watch_triggers
from projectzero.core.db import schema_ident

TRIGGERS = "watch/triggers.jsonl"
_ARCHIVE = "select raw from {}.legacy_documents where path = %s"
_ROWS = "select line::text from {}.watch_events order by seq"
_INSERT = "insert into {}.watch_events (kind, trigger_id, dedupe_key, line) values (%s, %s, %s, %s::json) returning seq"


def archived_text(raw: Any) -> str:
    """An archived log's text (``utf-8-sig``); ``None`` or undecodable bytes -> ``""``."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return bytes(raw).decode("utf-8-sig")
    except UnicodeDecodeError:
        return ""


def parse_text(text: str) -> list[dict[str, Any]]:
    """The old ``watch._events()``: every line that parses to a JSON object, in line order."""
    out: list[dict[str, Any]] = []
    for ln in text.splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def events_of(value: Any) -> list[dict[str, Any]]:
    """The log's dict lines from what a loader holds: the overlaid lines (a list), or an archive's raw bytes / text."""
    if isinstance(value, list):
        return [dict(e) for e in value if isinstance(e, dict)]
    return parse_text(archived_text(value))


def line(entry: Mapping[str, Any]) -> str:
    """The old writer's line: ``json.dumps(row, ensure_ascii=False, sort_keys=True)`` (``append_line`` replaced a
    newline by a space; the JSON text never holds one)."""
    return json.dumps(dict(entry), ensure_ascii=False, sort_keys=True).replace("\n", " ")


def joined(archived: str, lines: list[str]) -> str:
    """The archived text, then one line per row (newline-terminated). An archive whose last line has no newline gets
    one first (the old ``append_line`` would have glued the new line onto it, losing both)."""
    if not lines:
        return archived
    sep = "\n" if archived and not archived.endswith(("\n", "\r")) else ""
    return archived + sep + "".join(x + "\n" for x in lines)


def archive(conn: psycopg.Connection[Any], schema: str) -> str:
    row = conn.execute(sql.SQL(_ARCHIVE).format(schema_ident(schema)), (TRIGGERS,)).fetchone()
    return archived_text(row[0]) if row else ""


def row_lines(conn: psycopg.Connection[Any], schema: str) -> list[str]:
    return [str(r[0]) for r in conn.execute(sql.SQL(_ROWS).format(schema_ident(schema))).fetchall()]


def log_text(conn: psycopg.Connection[Any], schema: str) -> str:
    """The whole log as ONE text: the archive, then the rows."""
    return joined(archive(conn, schema), row_lines(conn, schema))


def load_events(conn: psycopg.Connection[Any], schema: str) -> list[dict[str, Any]]:
    """THE reader: the archived dict lines, then the rows' lines by ``seq``."""
    return parse_text(archive(conn, schema)) + [json.loads(x) for x in row_lines(conn, schema)]


def triggers(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The old ``watch.triggers()``: the fired triggers with their CURRENT status."""
    return watch_triggers(events)


def open_triggers(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The old ``watch.open_triggers()``."""
    return [t for t in triggers(events) if t["status"] == "new"]


def append_status(conn: psycopg.Connection[Any], schema: str, row: Mapping[str, Any]) -> int:
    """One acknowledgement line, in the caller's transaction."""
    found = conn.execute(
        sql.SQL(_INSERT).format(schema_ident(schema)), ("status", str(row["trigger_id"]), None, line(row))
    ).fetchone()
    assert found is not None
    return int(found[0])
