"""Review 005: reopening closed candidates against the one-open-candidate rule, and literal search, on the hosted DB."""

from __future__ import annotations

import secrets
import threading
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.candidates import DealFlowStore, DecisionError, ListQuery
from projectzero.ops.db_check import _scratch_sql

pytestmark = pytest.mark.hosted


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


def seed(settings: Settings, schema: str, name: str, statuses: dict[str, str]) -> str:
    """A company with several candidates in the given statuses, as the legacy import writes them."""
    with connect(settings.db_url, autocommit=True) as conn:
        row = conn.execute(
            f"insert into {schema}.companies (name) values (%s) returning id".encode(), (name,)
        ).fetchone()
        assert row is not None
        for candidate_id, status in statuses.items():
            conn.execute(
                f"insert into {schema}.candidates (id, company_id, name, status) values (%s, %s, %s, %s)".encode(),
                (candidate_id, row[0], name, status),
            )
        return str(row[0])


def rows(settings: Settings, query: str, *params: Any) -> list[tuple[Any, ...]]:
    with connect(settings.db_url, autocommit=True) as conn:
        return conn.execute(query.encode(), params or None).fetchall()


def decide(settings: Settings, schema: str, candidate_id: str, status: str, **kw: Any) -> dict[str, Any]:
    with transaction(settings.db_url) as conn:
        return DealFlowStore(conn, schema).decide(candidate_id, status, **kw)


def test_reopening_next_to_an_open_sibling_is_a_409_that_changes_nothing(settings: Settings, schema: str) -> None:
    seed(settings, schema, "Sibling Co", {"open00000001": "new", "closed000001": "rejected"})
    with pytest.raises(DecisionError) as refused:
        decide(settings, schema, "closed000001", "watch", notes="should not be saved", reason="retry")
    assert refused.value.status == 409 and refused.value.extra["open_candidate"] == "open00000001"
    assert rows(settings, f"select status, attrs ? 'notes' from {schema}.candidates where id = %s", "closed000001") == [
        ("rejected", False)
    ]
    assert rows(settings, f"select count(*) from {schema}.candidate_events") == [(0,)]  # no status event, no note
    # closed -> closed is still fine
    assert decide(settings, schema, "closed000001", "archived")["changed"] is True


def test_simultaneous_reopen_of_two_closed_siblings_opens_exactly_one(settings: Settings, schema: str) -> None:
    seed(settings, schema, "Twin Closed Co", {"closedaaaaaa": "rejected", "closedbbbbbb": "archived"})
    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}

    def reopen(candidate_id: str) -> None:
        barrier.wait()
        try:
            decide(settings, schema, candidate_id, "reviewing", notes="reopened")
            outcomes[candidate_id] = "opened"
        except DecisionError as exc:
            outcomes[candidate_id] = f"refused {exc.status}"

    threads = [threading.Thread(target=reopen, args=(c,)) for c in ("closedaaaaaa", "closedbbbbbb")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(outcomes.values()) == ["opened", "refused 409"]
    open_rows = rows(settings, f"select id from {schema}.candidates where status not in ('rejected', 'archived')")
    assert len(open_rows) == 1 and outcomes[open_rows[0][0]] == "opened"
    events = rows(settings, f"select candidate_id, action from {schema}.candidate_events order by id")
    assert events == [(open_rows[0][0], "status")]  # the refused attempt left neither a status event nor a note


def test_http_reopen_conflict_is_an_actionable_409(settings: Settings, schema: str) -> None:
    seed(settings, schema, "Http Co", {"httpopen0001": "watch", "httpclosed01": "rejected"})
    with TestClient(
        create_app(Settings(db_url=settings.db_url, schema=schema)), base_url="http://127.0.0.1:8177"
    ) as client:
        response = client.post("/api/deal-flow/candidates/httpclosed01/decision", json={"status": "new"})
    assert response.status_code == 409
    assert response.json()["ok"] is False and response.json()["open_candidate"] == "httpopen0001"


def test_literal_search_with_backslash_and_underscore(settings: Settings, schema: str) -> None:
    seed(settings, schema, "Path\\_Finder Labs", {"backslash001": "new"})
    seed(settings, schema, "Path_Finder Labs", {"underscore01": "new"})
    seed(settings, schema, "PathXFinder Labs", {"letterx00001": "new"})

    def search(text: str) -> list[str]:
        with transaction(settings.db_url) as conn:
            return sorted(i["id"] for i in DealFlowStore(conn, schema).list_candidates(ListQuery(text=text))["items"])

    assert search("\\_") == ["backslash001"]  # only the name with a literal backslash-underscore
    assert search("Path\\") == ["backslash001"]  # trailing backslash keeps the wildcard after it
    assert search("h_F") == ["underscore01"]  # underscore is literal, not "any character"
