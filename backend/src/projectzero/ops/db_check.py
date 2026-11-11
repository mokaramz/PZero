"""Hosted-database checks (``scripts/db.ps1 status|verify``).

``verify`` proves, on the real Supabase project and through the real session pooler, what PGlite (one connection)
cannot: two independent sessions contending on ``pz.record_submission`` and on session-level advisory locks. It runs
against a throw-away copy of the migration in a scratch schema (``pz_verify_<random>``) that is dropped at the end, so
the append-only production tables never receive test rows. It also checks that the public API key can read nothing.

Reads ``SUPABASE_DB_URL`` (session pooler, port 5432) from the environment. The URL is never printed.
"""

from __future__ import annotations

import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable

import psycopg

from projectzero.core.paths import REPO_ROOT

MIGRATIONS = REPO_ROOT / "supabase" / "migrations"


def _url() -> str:
    url = os.environ.get("SUPABASE_DB_URL", "")
    if not url:
        sys.exit("SUPABASE_DB_URL is not set")
    return url


def _connect(autocommit: bool = True) -> psycopg.Connection:
    from projectzero.core.db import connect

    return connect(_url(), autocommit=autocommit)


class Report:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, fn: Callable[[], str]) -> None:
        try:
            detail = fn()
            print(f"  PASS  {name}" + (f" - {detail}" if detail else ""))
        except Exception as exc:  # report every check, keep going
            self.failures += 1
            print(f"  FAIL  {name} - {type(exc).__name__}: {exc}")


def status() -> int:
    with _connect() as conn:
        row = conn.execute("select current_setting('server_version'), current_user, inet_server_port()").fetchone()
        assert row is not None
        print(f"connected: Postgres {row[0]} as {row[1]} (server port {row[2]})")
        has_pz = conn.execute("select exists(select 1 from pg_namespace where nspname = 'pz')").fetchone()
        tables = conn.execute("select count(*) from pg_tables where schemaname = 'pz'").fetchone()
        print(f"schema pz present: {has_pz and has_pz[0]} ({tables[0] if tables else 0} tables)")
        try:
            applied = conn.execute("select version, name from supabase_migrations.schema_migrations order by version")
            rows = applied.fetchall()
            print("applied migrations:", ", ".join(f"{v} {n}" for v, n in rows) or "none")
        except psycopg.errors.UndefinedTable:
            print("applied migrations: none (history table not created yet)")
    return 0


def _scratch_sql(schema: str) -> str:
    sql = "\n".join(p.read_text(encoding="utf-8") for p in sorted(MIGRATIONS.glob("*.sql")))
    return re.sub(r"\bpz\b", schema, sql)


def verify() -> int:
    report = Report()
    schema = f"pz_verify_{secrets.token_hex(4)}"
    print(f"scratch schema: {schema}")
    setup = _connect()
    try:
        setup.execute(_scratch_sql(schema))
        report.check("migration applies cleanly on the hosted server", lambda: "")
        report.check("lockdown: anon role cannot reach the schema", lambda: _anon_denied(setup, schema))
        report.check("lockdown: RLS on every table, no API-role grants", lambda: _rls_and_grants(setup, schema))
        report.check("record_submission: loser waits, then gets the winner's id", lambda: _race_commit(schema))
        report.check("record_submission: winner rolls back, waiting caller inserts", lambda: _race_rollback(schema))
        report.check("advisory lock: second session is refused while held", lambda: _advisory_contention())
        report.check("advisory lock: released on unlock and on disconnect", lambda: _advisory_release())
    finally:
        setup.execute(f"drop schema if exists {schema} cascade")
        setup.close()
        print(f"scratch schema dropped: {schema}")
    report.check("public API key reads nothing (REST)", _rest_denied)
    print("VERIFY PASSED" if report.failures == 0 else f"VERIFY FAILED ({report.failures})")
    return 1 if report.failures else 0


def _anon_denied(conn: psycopg.Connection, schema: str) -> str:
    try:
        with conn.transaction():
            conn.execute("set local role anon")
            conn.execute(f"select * from {schema}.candidates")
    except psycopg.errors.InsufficientPrivilege:
        return "permission denied"
    raise AssertionError("anon could read the table")


def _rls_and_grants(conn: psycopg.Connection, schema: str) -> str:
    off = conn.execute(
        "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = %s and c.relkind = 'r' and not c.relrowsecurity",
        (schema,),
    ).fetchall()
    grants = conn.execute(
        "select table_name, grantee from information_schema.role_table_grants "
        "where table_schema = %s and grantee in ('anon', 'authenticated', 'PUBLIC')",
        (schema,),
    ).fetchall()
    assert not off, f"RLS off: {off}"
    assert not grants, f"grants: {grants}"
    count = conn.execute("select count(*) from pg_tables where schemaname = %s", (schema,)).fetchone()
    return f"{count[0] if count else 0} tables"


def _record(conn: psycopg.Connection, schema: str, sha: str) -> tuple[str, bool]:
    row = conn.execute(
        f"select * from {schema}.record_submission("
        "'manual', 'db_check', 'verify', %s, '1.0', '{\"entities\": []}'::jsonb, 'accepted', '{}'::jsonb)",
        (sha,),
    ).fetchone()
    assert row is not None
    return str(row[0]), bool(row[1])


def _race(schema: str, winner_commits: bool) -> tuple[tuple[str, bool], tuple[str, bool], float]:
    sha = secrets.token_hex(32)
    a, b = _connect(autocommit=False), _connect(autocommit=False)
    try:
        first = _record(a, schema, sha)  # A inserted, not committed yet
        result: dict[str, object] = {}

        def second() -> None:
            started = time.monotonic()
            try:
                result["row"] = _record(b, schema, sha)  # blocks on A's uncommitted row
            except Exception as exc:
                result["error"] = exc
            result["waited"] = time.monotonic() - started

        thread = threading.Thread(target=second)
        thread.start()
        time.sleep(1.5)
        assert thread.is_alive(), "second session did not wait for the first"
        if winner_commits:
            a.commit()
        else:
            a.rollback()
        thread.join(15)
        if "error" in result:
            raise AssertionError(f"second session raised {result['error']!r}")
        b.commit()
        row, waited = result["row"], result["waited"]
        assert isinstance(row, tuple) and isinstance(waited, float)
        return first, (str(row[0]), bool(row[1])), waited
    finally:
        a.close()
        b.close()


def _race_commit(schema: str) -> str:
    (id_a, inserted_a), (id_b, inserted_b), waited = _race(schema, winner_commits=True)
    assert inserted_a and not inserted_b, (inserted_a, inserted_b)
    assert id_a == id_b
    return f"waited {waited:.1f}s, inserted [True, False], same id, no unique violation"


def _race_rollback(schema: str) -> str:
    (_, inserted_a), (_, inserted_b), waited = _race(schema, winner_commits=False)
    assert inserted_a and inserted_b
    return f"waited {waited:.1f}s, then inserted itself"


_LOCK_KEY = 0x5A_0001  # application-chosen key for this check only


def _advisory_contention() -> str:
    with _connect() as a, _connect() as b:
        assert a.execute("select pg_try_advisory_lock(%s)", (_LOCK_KEY,)).fetchone() == (True,)
        assert b.execute("select pg_try_advisory_lock(%s)", (_LOCK_KEY,)).fetchone() == (False,)
        pids = a.execute("select pg_backend_pid()").fetchone(), b.execute("select pg_backend_pid()").fetchone()
        assert pids[0] != pids[1]
        a.execute("select pg_advisory_unlock(%s)", (_LOCK_KEY,))
    return f"two backends {pids[0][0] if pids[0] else '?'} / {pids[1][0] if pids[1] else '?'}"


def _advisory_release() -> str:
    with _connect() as a, _connect() as b:
        a.execute("select pg_advisory_lock(%s)", (_LOCK_KEY,))
        a.execute("select pg_advisory_unlock(%s)", (_LOCK_KEY,))
        assert b.execute("select pg_try_advisory_lock(%s)", (_LOCK_KEY,)).fetchone() == (True,)
        b.execute("select pg_advisory_unlock(%s)", (_LOCK_KEY,))
        a.execute("select pg_advisory_lock(%s)", (_LOCK_KEY,))
    # `a` is closed now while still holding the lock: the server must release it with the session
    with _connect() as c:
        deadline = time.monotonic() + 10
        while c.execute("select pg_try_advisory_lock(%s)", (_LOCK_KEY,)).fetchone() != (True,):
            assert time.monotonic() < deadline, "lock survived the session that held it"
            time.sleep(0.5)
        c.execute("select pg_advisory_unlock(%s)", (_LOCK_KEY,))
    return "unlock frees it; closing the holder's session frees it"


def _rest_denied() -> str:
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_PUBLISHABLE_KEY")
    if not base or not key:
        return "skipped (SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY not set)"
    request = urllib.request.Request(
        f"{base}/rest/v1/candidates?select=id&limit=1",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept-Profile": "pz"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read(300)
        raise AssertionError(f"REST returned {response.status}: {body!r}")
    except urllib.error.HTTPError as err:
        return f"HTTP {err.code} ({err.read(160).decode('utf-8', 'replace')})"


SCRATCH_PATTERN = r"^pz_(verify|rehearse|conflict|itest)_[0-9a-f]{8}$"


def cleanup() -> int:
    """Drop scratch schemas left behind by an interrupted run (e.g. a network drop before the final DROP).

    Only names matching the exact scratch pattern are touched; ``pz`` and anything else are never dropped.
    """
    with _connect() as conn:
        rows = conn.execute("select nspname from pg_namespace where nspname ~ %s order by 1", (SCRATCH_PATTERN,))
        names = [str(name) for (name,) in rows.fetchall()]
        for name in names:
            assert re.fullmatch(SCRATCH_PATTERN, name) and name != "pz"
            conn.execute(f"drop schema {name} cascade".encode())
            print(f"dropped scratch schema {name}")
    print(f"cleanup done: {len(names)} scratch schema(s) dropped")
    return 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["cleanup"]:
        return cleanup()
    if argv[1:] == ["status"]:
        return status()
    if argv[1:] == ["verify"]:
        return verify()
    print("usage: python -m projectzero.ops.db_check status|verify|cleanup")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
