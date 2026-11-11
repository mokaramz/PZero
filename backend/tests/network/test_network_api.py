"""The Network endpoints offline: refusals happen before any connection; the import boundary is a 409."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.api.routers import network as router
from projectzero.core.config import Settings
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.network import store

UNREACHABLE = Settings(db_url="postgresql://nobody:nothing@127.0.0.1:1/none")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("PZ_AUTH_TOKEN", raising=False)

    def no_db(*_: Any, **__: Any) -> None:
        raise AssertionError("a refused request must not touch the database")

    monkeypatch.setattr(router, "transaction", no_db)
    with TestClient(create_app(UNREACHABLE), base_url="http://127.0.0.1:8177") as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("path", "payload", "error"),
    [
        ("person_save", {}, "name required"),
        ("person_save", {"name": " "}, "name required"),
        ("person_save", {"name": 5}, "name must be text"),
        ("person_save", {"id": 5}, "id must be text"),
        ("person_save", {"id": "p-a", "recommended": "p-b"}, "recommended must be a list of person ids"),
        ("talented", {"id": "p-a", "persons": "Ada"}, "persons must be a list of {name, note}"),
        ("talented", {"id": "p-a", "persons": [{"name": "Ada", "note": 3}]}, "persons must be a list of {name, note}"),
        ("watch_log", {"id": "p-a", "note": ["x"]}, "note must be text"),
    ],
)
def test_refusals_never_open_a_connection(client: TestClient, path: str, payload: dict[str, Any], error: str) -> None:
    r = client.post(f"/api/network/{path}", json=payload)
    assert r.status_code == 400 and r.json() == {"ok": False, "error": error}


@pytest.mark.parametrize("raw", [b"[1, 2]", b"{not json", b'{"name": NaN}'])
def test_a_body_that_is_not_a_json_object_is_refused(client: TestClient, raw: bytes) -> None:
    r = client.post("/api/network/person_save", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["ok"] is False and "not valid JSON" in r.json()["error"]


def test_writes_wait_for_the_legacy_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Writes into ``pz`` are refused (409) until the import marker exists: the intake / Conviction boundary."""
    monkeypatch.delenv("PZ_AUTH_TOKEN", raising=False)
    seen: list[str] = []

    @contextmanager
    def fake_transaction(_: str) -> Iterator[object]:
        yield object()

    def closed(_conn: Any, schema: str) -> None:
        seen.append(schema)
        raise IntakeClosedError("intake opens after the legacy import")

    monkeypatch.setattr(router, "transaction", fake_transaction)
    monkeypatch.setattr(store, "ensure_intake_open", closed)
    with TestClient(create_app(UNREACHABLE), base_url="http://127.0.0.1:8177") as client:
        for path, body in [("person_save", {"name": "Ada Quill"}), ("person_save", {"id": "p-a", "notes": "x"}),
                           ("talented", {"id": "p-a", "persons": [{"name": "B"}]}),
                           ("watch_log", {"id": "p-a", "note": "x"})]:  # fmt: skip
            r = client.post(f"/api/network/{path}", json=body)
            assert r.status_code == 409 and r.json() == {"ok": False, "error": "intake opens after the legacy import"}
    assert seen == ["pz"] * 4
