"""The four Validation logs in ``validation_log`` (review 027b, migration 0018): read in ``seq`` order, appended to.

* ``texts``: each log as the old file's text, its lines rejoined in ``seq`` order (gaps allowed). The read model
  parses that text exactly as it parsed the archived file (a line that does not parse is skipped on read). Every log
  ends with a line end, so a new row never joins a torn archived line (the declared difference of 027b). An archived
  line PostgreSQL text cannot hold (a NUL byte, never valid JSON) is stored NULL and read as an empty line, which the
  read model skips exactly as the old reader skipped that line (Codex H-241).
* ``append``: the lines one write produced, in order, as ``source = 'app'`` rows, inside the caller's transaction.
* ``lock``: the production write boundary (nothing before the import, 409) and the one Validation write lock. A
  caller that also writes intake data takes the intake lock first (the one lock order: intake, then validation).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import psycopg
from psycopg import sql

from projectzero.core.db import schema_ident
from projectzero.dealflow.intake.postgres import ensure_intake_open

LOGS = ("outcomes", "audits", "snapshots", "scout_feedback")
PATHS = {
    "outcomes": "validation/outcomes.jsonl",
    "audits": "validation/audits.jsonl",
    "snapshots": "validation/snapshots.jsonl",
    "scout_feedback": "validation/scout_feedback.jsonl",
}


def texts(conn: psycopg.Connection[Any], schema: str) -> dict[str, str]:
    """``{old path: text}`` for the four logs; a log without rows is ``""`` (the old missing file)."""
    lines: dict[str, list[str]] = {log: [] for log in LOGS}
    cur = conn.execute(sql.SQL("select log, line from {}.validation_log order by seq").format(schema_ident(schema)))
    for log, line in cur.fetchall():
        lines[str(log)].append("" if line is None else str(line))  # NULL: a line text cannot hold (0018)
    return {PATHS[log]: "".join(f"{line}\n" for line in rows) for log, rows in lines.items()}


def append(conn: psycopg.Connection[Any], schema: str, rows: Iterable[tuple[str, str]]) -> int:
    """Append ``(log, line)`` rows in order; returns how many were written."""
    n = 0
    query = sql.SQL("insert into {}.validation_log (log, line, source) values (%s, %s, 'app')").format(
        schema_ident(schema)
    )
    for log, line in rows:
        if log not in LOGS:
            raise ValueError(f"unknown Validation log {log!r}")
        conn.execute(query, (log, line))
        n += 1
    return n


def lock(conn: psycopg.Connection[Any], schema: str) -> None:
    ensure_intake_open(conn, schema)  # the production write boundary: nothing before the import
    conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (f"{schema}.validation",))
