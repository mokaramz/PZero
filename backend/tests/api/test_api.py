"""API hardening and the intake endpoint's refusal paths (no database: refusals happen before any connection)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.dealflow.intake import postgres as intake_postgres

UNREACHABLE = Settings(db_url="postgresql://nobody:nothing@127.0.0.1:1/none")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.delenv("PZ_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("PZ_ALLOWED_HOSTS", raising=False)

    def no_db(*_: Any, **__: Any) -> None:
        raise AssertionError("a refused request must not touch the database")

    monkeypatch.setattr(intake_postgres.PostgresIntake, "__init__", no_db)
    # as a context manager: ONE event loop serves every request, like the real server (needed to detect blocking)
    with TestClient(create_app(UNREACHABLE), base_url="http://127.0.0.1:8177") as test_client:
        yield test_client


def delivery(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "contract_version": "1.0",
        "origin": "manual",
        "submitted_at": "2026-11-11T09:00:00+01:00",
        "entities": [
            {
                "kind": "company",
                "name": "Acme",
                "key_fact": "Spun out of TUM in 2026",
                "evidence": [{"url": "https://www.tum.de/x"}],
            }
        ],
    }
    return doc | overrides


def test_health_and_security_headers(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.json() == {"ok": True}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


def test_foreign_host_is_refused(client: TestClient) -> None:
    response = client.get("/api/health", headers={"host": "evil.example.com"})
    assert response.status_code == 403 and response.json() == {"ok": False, "error": "host not allowed"}


@pytest.mark.parametrize(
    "headers",
    [{"origin": "https://evil.example.com"}, {"sec-fetch-site": "cross-site"}],
)
def test_cross_site_writes_are_refused(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post("/api/intake/submissions", json=delivery(), headers=headers)
    assert response.status_code == 403


def test_same_origin_write_passes_the_middleware(client: TestClient) -> None:
    response = client.post(
        "/api/intake/submissions", json=delivery(origin="registry_scan"), headers={"origin": "http://127.0.0.1:8177"}
    )
    assert response.status_code == 422  # reached the endpoint; refused by the contract, not by CSRF protection


def test_contract_refusal_is_422_with_issues_and_no_database(client: TestClient) -> None:
    response = client.post("/api/intake/submissions", json=delivery(origin="registry_scan"))
    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False and any("server-side only" in i for i in body["issues"])


def test_invalid_json_is_400(client: TestClient) -> None:
    response = client.post(
        "/api/intake/submissions", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400 and response.json()["ok"] is False


def test_bearer_token_when_configured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PZ_AUTH_TOKEN", "s3cret-token")
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", headers={"authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/health", headers={"authorization": "Bearer s3cret-token"}).status_code == 200


def test_a_waiting_delivery_does_not_block_other_requests(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review 004 #3: the blocking database work runs in a worker thread, not on the event loop."""
    import threading

    from projectzero.api.routers import intake as intake_router

    entered, release = threading.Event(), threading.Event()

    def slow_submit(*_: Any) -> tuple[int, dict[str, Any]]:
        entered.set()
        assert release.wait(10), "test never released the delivery"
        return 200, {"ok": True, "outcome": "accepted"}

    monkeypatch.setattr(intake_router, "submit_delivery", slow_submit)
    responses: list[int] = []
    worker = threading.Thread(
        target=lambda: responses.append(client.post("/api/intake/submissions", json=delivery()).status_code)
    )
    worker.start()
    try:
        assert entered.wait(10), "delivery never reached the database step"
        health = client.get("/api/health")  # must complete while the delivery is still waiting
        assert health.status_code == 200 and not release.is_set()
    finally:
        release.set()
        worker.join(10)
    assert responses == [200]


# ── Deal Flow endpoints: refusals happen before any database connection ─────────────────────────────────────────


def test_keep_via_decision_endpoint_is_409_without_database(client: TestClient) -> None:
    response = client.post("/api/deal-flow/candidates/4225c719f2f2/decision", json={"status": "kept"})
    assert response.status_code == 409 and response.json()["keep_via"] == "conviction"


def test_unknown_decision_status_is_400_without_database(client: TestClient) -> None:
    response = client.post("/api/deal-flow/candidates/4225c719f2f2/decision", json={"status": "research"})
    assert response.status_code == 400 and "reviewing" in response.json()["allowed"]


def test_unknown_list_filter_is_400_without_database(client: TestClient) -> None:
    response = client.get("/api/deal-flow/candidates", params={"status": "NEW INTAKE"})
    assert response.status_code == 400 and response.json()["ok"] is False


def test_decision_body_is_validated_with_the_error_contract(client: TestClient) -> None:
    response = client.post("/api/deal-flow/candidates/x/decision", json={})
    assert response.status_code == 422
    assert response.json()["ok"] is False and any("status" in i for i in response.json()["issues"])


def test_settings_never_show_the_database_url() -> None:
    secret = Settings(db_url="postgresql://user:SuperSecret123@host:5432/db", schema="pz")
    assert "SuperSecret123" not in repr(secret) and "SuperSecret123" not in str(secret)
