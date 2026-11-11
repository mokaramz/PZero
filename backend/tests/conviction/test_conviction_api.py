"""The Conviction endpoints' refusal paths and the static meta, offline: refusals happen before any connection."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.api.routers import conviction as router
from projectzero.conviction import taste
from projectzero.core.config import Settings

UNREACHABLE = Settings(db_url="postgresql://nobody:nothing@127.0.0.1:1/none")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("PZ_AUTH_TOKEN", raising=False)

    def no_db(*_: Any, **__: Any) -> None:
        raise AssertionError("a refused request must not touch the database")

    monkeypatch.setattr(router, "transaction", no_db)
    with TestClient(create_app(UNREACHABLE), base_url="http://127.0.0.1:8177") as test_client:
        yield test_client


def test_meta_is_the_old_meta(client: TestClient) -> None:
    body = client.get("/api/conviction/meta").json()
    assert body == json.loads(json.dumps(taste.meta()))
    assert body["ladders"]["founder"][0] == ["Unknown / not researched yet", 0]
    assert (
        body["tiers"]["announcement"].startswith("Announcement feed — ")
        and body["tiers"]["register"] == "Company register"
    )
    assert [a["id"] for a in body["archetypes"]] == list(range(1, 16)) and len(body["portfolio"]) == 40


@pytest.mark.parametrize(
    ("path", "payload", "error"),
    [
        ("save", {"company": "A", "scores": {"founder": 30}},
         "Not saved — score 'founder' = 30 is outside 0–25. Nothing was changed."),
        ("save", {"company": "A", "discovery_date": "2999-01-01"},
         "Not saved — signal date 2999-01-01 is in the future. Nothing was changed."),
        ("status", {"slug": "a", "status": "won"},
         "status must be one of: new, contacted, replied, forwarded, dropped"),
        ("status", {}, "status must be one of: new, contacted, replied, forwarded, dropped"),
    ],
)  # fmt: skip
def test_refusals_never_open_a_connection(client: TestClient, path: str, payload: dict[str, Any], error: str) -> None:
    r = client.post(f"/api/conviction/{path}", json=payload)
    assert r.status_code == 400 and r.json() == {"ok": False, "error": error}


@pytest.mark.parametrize("raw", [b"[1, 2]", b"{not json", b'{"company": NaN}'])
def test_a_body_that_is_not_a_json_object_is_refused(client: TestClient, raw: bytes) -> None:
    r = client.post("/api/conviction/save", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["ok"] is False and "not valid JSON" in r.json()["error"]


def test_case_needs_a_slug(client: TestClient) -> None:
    r = client.get("/api/conviction/case")
    assert r.status_code == 400 and r.json() == {"ok": False, "error": "slug required"}
