"""The Events write endpoints offline (review 016): bad requests are refused before any connection; every write
waits for the legacy import (409); a body that is not a JSON object is a 400."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.api.routers import events as router
from projectzero.core.config import Settings
from projectzero.dealflow.intake.postgres import IntakeClosedError
from projectzero.events import writes

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
        ("save", {}, "event name required"),
        ("save", {"name": " "}, "event name required"),
        ("save", {"name": 5}, "name must be text"),
        ("save", {"id": ["x"]}, "id must be text"),
        ("save", {"name": "A", "start": 20261204}, "start must be text"),
        ("lead", {"id": "evlead-1", "decision": "maybe"}, "decision must be one of new, dismissed, converted"),
        ("debrief", {"id": "ev-a", "people_met": "Ada"}, "people_met must be a list of objects"),
        ("debrief", {"id": "ev-a", "leads": [{"name": "X", "url": 3}]}, "leads must be a list of {name, desc, url}"),
    ],
)
def test_refusals_never_open_a_connection(client: TestClient, path: str, payload: dict[str, Any], error: str) -> None:
    r = client.post(f"/api/events/{path}", json=payload)
    assert r.status_code == 400 and r.json() == {"ok": False, "error": error}


@pytest.mark.parametrize("raw", [b"[1, 2]", b"{not json", b'{"name": NaN}'])
def test_a_body_that_is_not_a_json_object_is_refused(client: TestClient, raw: bytes) -> None:
    r = client.post("/api/events/save", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["ok"] is False


def test_writes_wait_for_the_legacy_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PZ_AUTH_TOKEN", raising=False)
    seen: list[str] = []

    @contextmanager
    def fake_transaction(_: str) -> Iterator[object]:
        yield object()

    def closed(_conn: Any, schema: str) -> None:
        seen.append(schema)
        raise IntakeClosedError("intake opens after the legacy import")

    monkeypatch.setattr(router, "transaction", fake_transaction)
    monkeypatch.setattr(writes, "ensure_intake_open", closed)
    with TestClient(create_app(UNREACHABLE), base_url="http://127.0.0.1:8177") as client:
        for path, body in [
            ("save", {"name": "Robotics Night"}),
            ("save", {"id": "ev-a", "status": "planned"}),
            ("verify", {"id": "ev-a"}),
            ("lead", {"id": "evlead-1"}),
            ("debrief", {"id": "ev-a"}),
            ("scout", {"id": "se-1", "action": "add"}),
            ("scout", {"id": "se-1", "action": "monitor"}),
        ]:
            r = client.post(f"/api/events/{path}", json=body)
            assert r.status_code == 409 and r.json() == {"ok": False, "error": "intake opens after the legacy import"}
    assert seen == ["pz"] * 7


def test_a_write_from_another_origin_is_refused(client: TestClient) -> None:
    r = client.post("/api/events/save", json={"name": "A"}, headers={"origin": "https://evil.example.com"})
    assert r.status_code == 403
