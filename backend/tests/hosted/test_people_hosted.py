"""Review 012 on the hosted project, in a throw-away scratch schema: the people write model as Conviction reads it
(``attrs.record`` wins over ``legacy``; archived ``people.json`` order, then new rows by ``created_at``) and the weak
``url`` identifier of migration 0005."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from projectzero.conviction import imq
from projectzero.conviction.inputs import load_inputs, load_people
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.ops.db_check import _scratch_sql

pytestmark = pytest.mark.hosted
T0 = datetime.fromisoformat("2026-11-11T12:00:00+01:00")


@pytest.fixture(scope="module")
def settings() -> Settings:
    try:
        return Settings.from_env()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def schema(settings: Settings) -> Iterator[str]:
    name = f"pz_itest_{secrets.token_hex(4)}"
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(name).encode())
        yield name
    finally:
        admin.execute(f"drop schema if exists {name} cascade".encode())
        admin.close()


def person(
    conn: psycopg.Connection[Any], schema: str, pid: str, *, legacy: Any, record: Any = None, created: datetime
) -> None:
    attrs = {"record": record} if record is not None else {}
    conn.execute(
        f"insert into {schema}.people (id, name, legacy, attrs, created_at) values (%s, %s, %s, %s, %s)".encode(),
        (pid, (record or legacy)["name"], None if legacy is None else Jsonb(legacy), Jsonb(attrs), created),
    )


def test_conviction_reads_the_current_person_record_in_the_old_order(settings: Settings, schema: str) -> None:
    ada = {"id": "p-ada", "name": "Ada Lovelace", "identity_status": "needs identity resolution"}
    bea = {"id": "p-bea", "name": "Bea Roe", "identity_status": "needs identity resolution"}
    raw = json.dumps({"people": [bea, ada]}).encode()  # the archived file lists Bea first
    with transaction(settings.db_url) as conn:
        conn.execute(
            f"insert into {schema}.legacy_documents (path, sha256, bytes, raw, parsed) values (%s, %s, %s, %s, %s)".encode(),
            ("people.json", hashlib.sha256(raw).hexdigest(), len(raw), raw, Jsonb(json.loads(raw))),
        )
        person(conn, schema, "p-ada", legacy=ada, record={**ada, "identity_status": "resolved"}, created=T0)
        person(conn, schema, "p-bea", legacy=bea, created=T0 - timedelta(days=9))
        late = {"id": "p-late", "name": "Late Person", "identity_status": "resolved"}
        early = {"id": "p-early", "name": "Early Person", "identity_status": "resolved"}
        person(conn, schema, "p-late", legacy=None, record=late, created=T0 + timedelta(hours=2))
        person(conn, schema, "p-early", legacy=None, record=early, created=T0 + timedelta(hours=1))

    with transaction(settings.db_url) as conn:
        people = load_people(conn, schema)
        inputs = load_inputs(conn, schema)
    assert [p["id"] for p in people] == ["p-bea", "p-ada", "p-early", "p-late"]  # archive order, then created_at
    assert people[1] == {**ada, "identity_status": "resolved"}  # the attrs.record edit, not the imported legacy
    assert inputs.imq.people == people
    (founder,) = imq.founder_identities({"founders": [{"name": "Ada Lovelace"}]}, inputs.imq.people)
    assert founder["resolved"] is True and founder["person_id"] == "p-ada"


def test_a_url_is_weak_and_a_profile_is_strong(settings: Settings, schema: str) -> None:
    with transaction(settings.db_url) as conn:
        for pid in ("p-a", "p-b"):
            person(conn, schema, pid, legacy={"id": pid, "name": pid}, created=T0)
            conn.execute(
                f"insert into {schema}.person_identifiers (person_id, kind, value) values (%s, 'url', %s)".encode(),
                (pid, "https://acme.example.com"),
            )
        conn.execute(
            f"insert into {schema}.person_identifiers (person_id, kind, value) "
            "values ('p-a', 'profile_url', 'https://github.com/ada')".encode()
        )
        strengths = conn.execute(
            f"select kind, strength, count(*) from {schema}.person_identifiers group by 1, 2 order by 1".encode()
        ).fetchall()
    assert strengths == [("profile_url", "strong", 1), ("url", "weak", 2)]
    with pytest.raises(psycopg.errors.UniqueViolation), transaction(settings.db_url) as conn:
        conn.execute(
            f"insert into {schema}.person_identifiers (person_id, kind, value) "
            "values ('p-b', 'profile_url', 'https://github.com/ada')".encode()
        )
