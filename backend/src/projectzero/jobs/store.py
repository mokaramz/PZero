"""The runner's state in the database (review 032c, migration 0023). Every function works inside the caller's
connection; nothing here opens one.

* **The lock**: a SESSION advisory lock, ``pg_try_advisory_lock(hashtext('<schema>.jobs'))``, taken on a dedicated
  autocommit connection (``try_lock``). It dies with its connection, so it is never left stale; whether it is held is
  read from ``pg_locks`` (``held``).
* **The lease** (revision 2): ``take_lease`` increments ``job_lease.generation`` and records the holder (source, pid,
  since) in ONE statement on the lock's connection; the taker keeps its value ``G``. ``lease_for_update`` reads the
  generation ``FOR UPDATE`` at the start of every claim and completion transaction.
* **The job records** (``job_state.detail``, the old ``jobs.json`` record whole) and the **history**
  (``job_runs``: a new row's real ``started_at`` / ``finished_at``, ``detail`` the old line).
* **The runner records** (``job_runner``): ``runner_records`` is the ONE reader, used by System health and by
  ``GET /api/catchup``: the archived ``schedule/runner.json`` (byte-exact, in its key order) OVERLAID by source with
  the new rows; a source the new runner has written shows its new record in its place, every other source keeps its
  imported record, a new source follows in the order it was first written.
* ``config``: ``config.json`` (the archive first, in its key order, else the ``documents`` row; tolerant).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from projectzero.core.db import schema_ident
from projectzero.health.catalog import _ts
from projectzero.validation.inputs import parse_archived

LOCK_KEY = "{schema}.jobs"
RUNNER_FILE = "schedule/runner.json"
LOCK_WARN_H = 3  # a lock held longer than this is reported as suspect (never broken)
_HELD = (
    "select exists (select 1 from pg_locks where locktype = 'advisory' and granted and objsubid = 1 "
    "and database = (select oid from pg_database where datname = current_database()) "
    "and ((classid::bigint << 32) | objid::bigint) = hashtext(%s)::bigint)"
)


def _q(schema: str, query: str) -> sql.Composed:
    return sql.SQL(query).format(s=schema_ident(schema))


def lock_key(schema: str) -> str:
    return LOCK_KEY.format(schema=schema)


# ---------------------------------------------------------------------------------------------- lock and lease
def try_lock(conn: psycopg.Connection[Any], schema: str) -> bool:
    row = conn.execute("select pg_try_advisory_lock(hashtext(%s))", (lock_key(schema),)).fetchone()
    return bool(row and row[0])


def unlock(conn: psycopg.Connection[Any], schema: str) -> None:
    conn.execute("select pg_advisory_unlock(hashtext(%s))", (lock_key(schema),))


def held(conn: psycopg.Connection[Any], schema: str) -> bool:
    row = conn.execute(_HELD, (lock_key(schema),)).fetchone()
    return bool(row and row[0])


def take_lease(conn: psycopg.Connection[Any], schema: str, holder: dict[str, Any]) -> int:
    """The new generation ``G`` (one statement: atomic on an autocommit connection)."""
    row = conn.execute(
        _q(schema, "update {s}.job_lease set generation = generation + 1, holder = %s::json, taken_at = now() "
                   "where id = 1 returning generation"),
        (json.dumps(holder, ensure_ascii=False),),
    ).fetchone()  # fmt: skip
    if row is None:
        raise RuntimeError("the job lease row is missing (migration 0023)")
    return int(row[0])


def lease(conn: psycopg.Connection[Any], schema: str) -> tuple[int, dict[str, Any] | None]:
    row = conn.execute(_q(schema, "select generation, holder from {s}.job_lease where id = 1")).fetchone()
    if row is None:
        return 0, None
    return int(row[0]), row[1] if isinstance(row[1], dict) else None


def lease_for_update(conn: psycopg.Connection[Any], schema: str) -> int:
    row = conn.execute(_q(schema, "select generation from {s}.job_lease where id = 1 for update")).fetchone()
    return int(row[0]) if row else -1


def lock_status(conn: psycopg.Connection[Any], schema: str, now: datetime) -> dict[str, Any]:
    """The old ``lock_status()``: ``{"held": false}``, or the holder with its age (``now``: naive Berlin wall time).
    The advisory lock dies with its connection, so a held lock's holder is always alive."""
    if not held(conn, schema):
        return {"held": False}
    _gen, h = lease(conn, schema)
    h = h or {}
    started = _ts(h.get("since"))
    age_h = round((now - started).total_seconds() / 3600, 2) if started else None
    return {"held": True, "alive": True, "source": h.get("source"), "pid": h.get("pid"), "since": h.get("since"),
            "age_h": age_h, "suspect": bool(age_h is not None and age_h > LOCK_WARN_H)}  # fmt: skip


def held_generation(conn: psycopg.Connection[Any], schema: str) -> int | None:
    """The generation of the runner holding the lock now (``None`` when nobody holds it)."""
    return lease(conn, schema)[0] if held(conn, schema) else None


# ---------------------------------------------------------------------------------------------- job records
def job_records(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_q(schema, "select job, detail from {s}.job_state order by job"))
        return {str(r["job"]): r["detail"] for r in cur.fetchall()}


def record_for_update(conn: psycopg.Connection[Any], schema: str, job: str) -> dict[str, Any] | None:
    row = conn.execute(_q(schema, "select detail from {s}.job_state where job = %s for update"), (job,)).fetchone()
    return row[0] if row and isinstance(row[0], dict) else None


def claim_record(
    conn: psycopg.Connection[Any], schema: str, job: str, interval_h: float, record: dict[str, Any]
) -> datetime:
    """Write the job's record as claimed (``running``); returns the real claim instant."""
    row = conn.execute(
        _q(schema, "insert into {s}.job_state (job, interval_hours, last_started_at, last_outcome, detail) "
                   "values (%s, %s, clock_timestamp(), 'running', %s) on conflict (job) do update set "
                   "detail = excluded.detail, last_started_at = excluded.last_started_at, "
                   "last_outcome = excluded.last_outcome returning last_started_at"),
        (job, interval_h, Jsonb(record)),
    ).fetchone()  # fmt: skip
    assert row is not None
    started: datetime = row[0]
    return started


def complete_record(
    conn: psycopg.Connection[Any], schema: str, job: str, record: dict[str, Any], outcome: str
) -> datetime:
    row = conn.execute(
        _q(schema, "update {s}.job_state set detail = %s, last_finished_at = clock_timestamp(), last_outcome = %s "
                   "where job = %s returning last_finished_at"),
        (Jsonb(record), outcome, job),
    ).fetchone()  # fmt: skip
    assert row is not None
    finished: datetime = row[0]
    return finished


def write_record(conn: psycopg.Connection[Any], schema: str, job: str, record: dict[str, Any]) -> None:
    conn.execute(_q(schema, "update {s}.job_state set detail = %s where job = %s"), (Jsonb(record), job))


def append_run(
    conn: psycopg.Connection[Any],
    schema: str,
    job: str,
    started_at: datetime,
    finished_at: datetime,
    ok: bool,
    line: dict[str, Any],
) -> None:
    conn.execute(
        _q(
            schema,
            "insert into {s}.job_runs (job, started_at, finished_at, outcome, detail) values (%s, %s, %s, %s, %s)",
        ),
        (job, started_at, max(finished_at, started_at), "ok" if ok else "failed", Jsonb(line)),
    )


def runs(conn: psycopg.Connection[Any], schema: str) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_q(schema, "select detail from {s}.job_runs order by id"))
        return [r["detail"] for r in cur.fetchall()]


# ---------------------------------------------------------------------------------------------- runner records
def document(conn: psycopg.Connection[Any], schema: str, key: str) -> Any:
    row = conn.execute(_q(schema, "select body from {s}.documents where key = %s"), (key,)).fetchone()
    return row[0] if row is not None else None


def archived(conn: psycopg.Connection[Any], schema: str, path: str) -> Any:
    """A document in the OLD KEY ORDER: the byte-exact archive, else the ``documents`` row (``None``: neither)."""
    row = conn.execute(_q(schema, "select raw from {s}.legacy_documents where path = %s"), (path,)).fetchone()
    if row is not None:
        return parse_archived(row[0])
    return document(conn, schema, path)


def runner_records(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    """The ONE runner-record reader (System health's diagnostics and ``GET /api/catchup``): the archived
    ``schedule/runner.json`` overlaid by source with the ``job_runner`` rows."""
    base = archived(conn, schema, RUNNER_FILE)
    out: dict[str, Any] = dict(base) if isinstance(base, dict) else {}
    rows = conn.execute(_q(schema, "select source, record from {s}.job_runner order by created_at, source")).fetchall()
    for source, record in rows:
        out[str(source)] = record  # an existing source keeps its place; a new one is appended
    return out


def new_runner_records(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    """The runner records the NEW runner wrote (``job_runner`` only, never the archive), by source."""
    rows = conn.execute(_q(schema, "select source, record from {s}.job_runner order by created_at, source")).fetchall()
    return {str(source): record for source, record in rows}


def write_runner(conn: psycopg.Connection[Any], schema: str, source: str, record: dict[str, Any]) -> None:
    conn.execute(
        _q(schema, "insert into {s}.job_runner (source, record) values (%s, %s::json) on conflict (source) do update "
                   "set record = excluded.record, updated_at = now()"),
        (source, json.dumps(record, ensure_ascii=False)),
    )  # fmt: skip


def config(conn: psycopg.Connection[Any], schema: str) -> dict[str, Any]:
    """The old ``storage.load_json("config.json", {}, tolerant=True)``."""
    doc = archived(conn, schema, "config.json")
    return doc if isinstance(doc, dict) else {}
