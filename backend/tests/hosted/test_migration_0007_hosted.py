"""Migration 0007 under concurrency (review 014, the 0003 standard of H-068), on the hosted server in a scratch schema.

A writer holds an uncommitted insert into ``events``; the migration starts and must WAIT for the table lock; the writer
commits; the migration must then see the row and abort: no column added, no ``event_leads`` table, the row untouched.
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
M7 = next(p for p in FILES if "event_dates" in p.name)


def scoped(sql: str, schema: str) -> str:
    return re.sub(r"\bpz\b", schema, sql)


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def before_0007(settings: Settings) -> Iterator[str]:
    """A scratch schema with every migration BEFORE 0007."""
    name = f"pz_itest_{secrets.token_hex(4)}"
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(scoped("\n".join(p.read_text(encoding="utf-8") for p in FILES if p < M7), name).encode())
        yield name
    finally:
        admin.execute(f"drop schema if exists {name} cascade".encode())
        admin.close()


def _shape(settings: Settings, schema: str) -> tuple[int, bool]:
    with connect(settings.db_url, autocommit=True) as conn:
        cols = conn.execute(
            b"select count(*) from information_schema.columns where table_schema = %s and table_name = 'events' "
            b"and column_name in ('start_date', 'start_time', 'end_date', 'end_time')",
            (schema,),
        ).fetchone()
        leads = conn.execute(b"select to_regclass(%s) is not null", (f"{schema}.event_leads",)).fetchone()
    assert cols is not None and leads is not None
    return int(cols[0]), bool(leads[0])


def test_the_migration_waits_for_an_uncommitted_writer_then_refuses(settings: Settings, before_0007: str) -> None:
    s = before_0007
    writer = connect(settings.db_url)  # one transaction, held open
    # a row 0007's new checks accept: only the emptiness check (under the lock) can refuse the migration
    writer.execute(f"insert into {s}.events (id, name) values ('ev-racing', 'Racing')".encode())
    outcome: dict[str, Any] = {}
    tag = f"pz-mig-{secrets.token_hex(4)}"  # through the pooler backend_pid is virtual: find the session by name

    def migrate() -> None:
        with connect(settings.db_url, autocommit=True) as conn:
            conn.execute(f"set application_name = '{tag}'".encode())
            outcome["tagged"] = True
            try:
                conn.execute(scoped(M7.read_text(encoding="utf-8"), s).encode())
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
    assert outcome.get("result", "").startswith("refused") and "events is not empty" in outcome["result"]
    assert _shape(settings, s) == (0, False)  # nothing half-applied
    with connect(settings.db_url, autocommit=True) as conn:
        kept = conn.execute(f"select name, starts_at from {s}.events where id = 'ev-racing'".encode()).fetchone()
    assert kept == ("Racing", None)  # the committed row is untouched


def test_on_an_empty_table_the_migration_applies(settings: Settings, before_0007: str) -> None:
    with connect(settings.db_url, autocommit=True) as conn:
        conn.execute(scoped(M7.read_text(encoding="utf-8"), before_0007).encode())
    assert _shape(settings, before_0007) == (4, True)
