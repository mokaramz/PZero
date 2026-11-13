"""The operator's triage decision log (review 035a): the old ``triage_decisions.jsonl``, as ONE text.

The imported file is the byte-exact archive (``legacy_documents``); the decisions made since are ``triage_decisions``
rows, each holding the old line (sorted keys, ``json`` so the text is byte-kept). Every reader (the triage view's
verdicts and calibration, Validation, Today through the view) reads the archived lines FIRST, then the rows
``order by seq``: ``log_text`` joins them as the old file would have read after the appends. One deliberate
difference: an archive whose last line has no newline gets one before the first row (the old ``append_line`` would
have glued the new line onto it, losing both).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql

from projectzero.core.db import schema_ident

_ROWS = "select entry::text from {}.triage_decisions order by seq"
_INSERT = "insert into {}.triage_decisions (candidate_id, recorded_at, entry) values (%s, %s, %s::json) returning seq"
# review 035d: many lines in ONE statement, ``seq`` in the given order (the old sequential appends)
_INSERT_MANY = (
    "insert into {}.triage_decisions (candidate_id, recorded_at, entry) "
    "select t.cid, %s, t.line::json from unnest(%s::text[], %s::text[]) with ordinality as t(cid, line, ord) "
    "order by t.ord"
)


def line(entry: Mapping[str, Any]) -> str:
    """The old writer's line: ``json.dumps(entry, ensure_ascii=False, sort_keys=True)`` (``append_line`` replaced
    a newline by a space; the JSON text never holds one)."""
    return json.dumps(dict(entry), ensure_ascii=False, sort_keys=True).replace("\n", " ")


def joined(archived: str, lines: list[str]) -> str:
    """The archived text, then one line per row (newline-terminated)."""
    if not lines:
        return archived
    sep = "\n" if archived and not archived.endswith(("\n", "\r")) else ""
    return archived + sep + "".join(x + "\n" for x in lines)


def rows(conn: psycopg.Connection[Any], schema: str) -> list[str]:
    return [str(r[0]) for r in conn.execute(sql.SQL(_ROWS).format(schema_ident(schema))).fetchall()]


def log_text(conn: psycopg.Connection[Any], schema: str, archived: str) -> str:
    return joined(archived, rows(conn, schema))


def append(
    conn: psycopg.Connection[Any], schema: str, candidate_id: str, entry: Mapping[str, Any], recorded_at: datetime
) -> int:
    """One row, in the caller's transaction (the decision and its line commit together, decision b)."""
    row = conn.execute(
        sql.SQL(_INSERT).format(schema_ident(schema)), (candidate_id, recorded_at, line(entry))
    ).fetchone()
    assert row is not None
    return int(row[0])


def append_many(
    conn: psycopg.Connection[Any],
    schema: str,
    entries: list[tuple[str, Mapping[str, Any]]],
    recorded_at: datetime,
) -> None:
    """``(candidate_id, entry)`` pairs as rows in ONE statement, in the given order (the batch confirm, review 035d):
    each row is the one ``append`` writes, and their ``seq`` follow the list."""
    if not entries:
        return
    conn.execute(
        sql.SQL(_INSERT_MANY).format(schema_ident(schema)),
        (recorded_at, [cid for cid, _ in entries], [line(e) for _, e in entries]),
    )
