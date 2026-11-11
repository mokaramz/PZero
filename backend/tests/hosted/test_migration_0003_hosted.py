"""Migration 0003 under concurrency (review 010, Codex H-068), on the hosted server in a scratch schema.

A writer holds an uncommitted insert into ``conviction_entries``; the migration starts and must WAIT for the table
lock; the writer commits; the migration must then see the row and abort, leaving the row's boolean untouched.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest

from projectzero.core.config import Settings
from projectzero.core.db import connect
from projectzero.ops.db_check import MIGRATIONS

pytestmark = pytest.mark.hosted
FILES = sorted(MIGRATIONS.glob("*.sql"))
M3 = next(p for p in FILES if "conviction_verified_flags" in p.name)


def scoped(sql: str, schema: str) -> str:
    return re.sub(r"\bpz\b", schema, sql)


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def before_0003(settings: Settings) -> Iterator[str]:
    """A scratch schema with every migration BEFORE 0003 (verified still boolean)."""
    name = f"pz_itest_{secrets.token_hex(4)}"
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(scoped("\n".join(p.read_text(encoding="utf-8") for p in FILES if p < M3), name).encode())
        yield name
    finally:
        admin.execute(f"drop schema if exists {name} cascade".encode())
        admin.close()


def test_the_migration_waits_for_an_uncommitted_writer_then_refuses(settings: Settings, before_0003: str) -> None:
    s = before_0003
    writer = connect(settings.db_url)  # one transaction, held open
    company = writer.execute(f"insert into {s}.companies (name) values ('Racing Co') returning id".encode()).fetchone()
    assert company is not None
    writer.execute(
        f"insert into {s}.conviction_entries (company_id, slug, status, verified) values (%s, 'racing', 'new', true)".encode(),
        (company[0],),
    )
    outcome: dict[str, Any] = {}
    tag = f"pz-mig-{secrets.token_hex(4)}"  # through the pooler backend_pid is virtual: find the session by name

    def migrate() -> None:
        with connect(settings.db_url, autocommit=True) as conn:
            conn.execute(f"set application_name = '{tag}'".encode())
            outcome["tagged"] = True
            try:
                conn.execute(scoped(M3.read_text(encoding="utf-8"), s).encode())
                outcome["result"] = "applied"
            except Exception as exc:  # the refusal is the expected outcome
                outcome["result"] = f"refused: {exc}"

    t = threading.Thread(target=migrate)
    t.start()
    waited = False
    with connect(settings.db_url, autocommit=True) as watch:
        for _ in range(100):
            time.sleep(0.2)
            if "tagged" not in outcome:
                continue
            row = watch.execute(
                b"select wait_event_type from pg_stat_activity where application_name = %s", (tag,)
            ).fetchone()
            if row and row[0] == "Lock":
                waited = True
                break
    writer.commit()
    writer.close()
    t.join(timeout=60)
    assert waited, f"the migration did not wait for the writer's lock: {outcome}"
    assert outcome.get("result", "").startswith("refused") and "not empty" in outcome["result"]
    with connect(settings.db_url, autocommit=True) as conn:
        typ = conn.execute(
            b"select data_type from information_schema.columns where table_schema = %s and table_name = "
            b"'conviction_entries' and column_name = 'verified'",
            (s,),
        ).fetchone()
        kept = conn.execute(f"select verified from {s}.conviction_entries where slug = 'racing'".encode()).fetchone()
    assert typ == ("boolean",) and kept == (True,)  # nothing converted, the committed value intact


def test_on_an_empty_table_the_migration_applies(settings: Settings, before_0003: str) -> None:
    with connect(settings.db_url, autocommit=True) as conn:
        conn.execute(scoped(M3.read_text(encoding="utf-8"), before_0003).encode())
        typ = conn.execute(
            b"select data_type, column_default from information_schema.columns where table_schema = %s and "
            b"table_name = 'conviction_entries' and column_name = 'verified'",
            (before_0003,),
        ).fetchone()
    assert typ is not None and typ[0] == "jsonb" and "{}" in str(typ[1])
