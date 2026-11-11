"""Deal Flow read model and decisions against the hosted project, in a throw-away scratch schema."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.candidates import DealFlowStore, DecisionError, ListQuery
from projectzero.dealflow.intake.postgres import PostgresIntake
from projectzero.dealflow.intake.service import IntakeService
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


def company(name: str, **extra: Any) -> dict[str, Any]:
    return {"kind": "company", "name": name, "key_fact": f"{name} raised a pre-seed round",
            "evidence": [{"url": f"https://news.example.com/{name.lower().replace(' ', '-')}"}]} | extra  # fmt: skip


def deliver(settings: Settings, schema: str, *entities: dict[str, Any], origin: str = "grok") -> list[dict[str, Any]]:
    payload = {"contract_version": "1.0", "origin": origin, "external_ref": secrets.token_hex(3),
               "submitted_at": "2026-11-11T09:00:00+01:00", "entities": list(entities)}  # fmt: skip
    with transaction(settings.db_url) as conn:
        store = PostgresIntake(conn, schema)
        result = IntakeService(store, resolver=store).submit_external(payload, submitted_by=origin)
    return list(result.resolution)


def store_call(settings: Settings, schema: str, fn: Any) -> Any:
    with transaction(settings.db_url) as conn:
        return fn(DealFlowStore(conn, schema))


@pytest.fixture
def seeded(settings: Settings, schema: str) -> dict[str, str]:
    ids = {}
    for name in ("Alpha Robotics", "Beta Quantum", "Gamma Bio", "Delta Space", "Epsilon Grid"):
        ids[name] = deliver(settings, schema, company(name))[0]["candidate_id"]
    ids["Zeta Manual"] = deliver(settings, schema, company("Zeta Manual"), origin="manual")[0]["candidate_id"]
    # a legacy Scout Intake id pointing at Alpha (as the import writes it)
    with connect(settings.db_url, autocommit=True) as conn:
        conn.execute(
            f"insert into {schema}.candidate_aliases (namespace, alias_id, candidate_id, reason) "
            "values ('scout_intake', 'si-002-alpha', %s, 'merge')".encode(),
            (ids["Alpha Robotics"],),
        )
    return ids


def test_list_filters_counts_and_paging(settings: Settings, schema: str, seeded: dict[str, str]) -> None:
    everything = store_call(settings, schema, lambda s: s.list_candidates(ListQuery(limit=200)))
    assert len(everything["items"]) == 6 and everything["next_cursor"] is None
    assert everything["counts"]["status"] == {"new": 6}
    assert everything["counts"]["origin"] == {"grok": 5, "manual": 1}

    manual = store_call(settings, schema, lambda s: s.list_candidates(ListQuery(origin=("manual",))))
    assert [i["name"] for i in manual["items"]] == ["Zeta Manual"] and manual["counts"]["origin"] == {"manual": 1}

    found = store_call(settings, schema, lambda s: s.list_candidates(ListQuery(text="quant")))
    assert [i["name"] for i in found["items"]] == ["Beta Quantum"]
    assert store_call(settings, schema, lambda s: s.list_candidates(ListQuery(text="100%_")))["items"] == []

    seen: list[str] = []
    cursor = None
    while True:
        page = store_call(settings, schema, lambda s, c=cursor: s.list_candidates(ListQuery(limit=2, cursor=c)))
        seen += [i["id"] for i in page["items"]]
        if not (cursor := page["next_cursor"]):
            break
    assert sorted(seen) == sorted(seeded.values()) and len(seen) == len(set(seen))  # complete, no duplicates

    item = everything["items"][0]
    assert item["company"]["name"] and item["observations"] == 1 and item["merge_suggested"] is False


def test_detail_and_old_id_resolution(settings: Settings, schema: str, seeded: dict[str, str]) -> None:
    alpha = seeded["Alpha Robotics"]
    detail = store_call(settings, schema, lambda s: s.get_candidate(alpha))
    assert detail["candidate"]["name"] == "Alpha Robotics" and detail["company"]["name"] == "Alpha Robotics"
    assert len(detail["observations"]) == 1 and detail["observations"][0]["evidence"]
    assert [e["action"] for e in detail["events"]] == ["intake"]
    assert {(k["namespace"], k["alias_id"]) for k in detail["known_ids"]} == {
        ("candidate", alpha),
        ("scout_intake", "si-002-alpha"),
    }
    assert any(i["kind"] == "normalized_name" for i in detail["identifiers"])

    assert store_call(settings, schema, lambda s: s.resolve_id("scout_intake", "si-002-alpha")) == alpha
    assert store_call(settings, schema, lambda s: s.resolve_id("candidate", "nope")) is None
    with pytest.raises(DecisionError):
        store_call(settings, schema, lambda s: s.resolve_id("inbox", alpha))


def test_decisions_audit_noop_and_guards(settings: Settings, schema: str, seeded: dict[str, str]) -> None:
    beta = seeded["Beta Quantum"]
    first = store_call(settings, schema, lambda s: s.decide(beta, "reviewing", reason="strong founders"))
    assert first == {"id": beta, "status": "reviewing", "previous_status": "new", "changed": True}
    again = store_call(settings, schema, lambda s: s.decide(beta, "reviewing"))
    assert again["changed"] is False  # never reports a change that did not happen

    with pytest.raises(DecisionError) as stale:
        store_call(settings, schema, lambda s: s.decide(beta, "watch", expected_status="new"))
    assert stale.value.status == 409 and stale.value.extra["current"] == "reviewing"
    with pytest.raises(DecisionError) as keep:
        store_call(settings, schema, lambda s: s.decide(beta, "kept"))
    assert keep.value.status == 409
    with pytest.raises(DecisionError) as missing:
        store_call(settings, schema, lambda s: s.decide("doesnotexist", "watch"))
    assert missing.value.status == 404

    store_call(settings, schema, lambda s: s.decide(beta, "reviewing", notes="call after demo day"))
    detail = store_call(settings, schema, lambda s: s.get_candidate(beta))
    assert detail["candidate"]["status"] == "reviewing" and detail["candidate"]["decided_at"] is not None
    assert detail["candidate"]["attrs"]["notes"] == "call after demo day"
    operator = [
        (e["action"], e["from_status"], e["to_status"], e["reason"])
        for e in detail["events"]
        if e["actor"] == "operator"
    ]
    assert operator == [("note", "reviewing", None, None), ("status", "new", "reviewing", "strong founders")]


def test_intake_re_report_never_overrides_an_operator_decision(
    settings: Settings, schema: str, seeded: dict[str, str]
) -> None:
    gamma = seeded["Gamma Bio"]
    store_call(settings, schema, lambda s: s.decide(gamma, "watch"))
    deliver(settings, schema, company("Gamma Bio", key_unknown="Who is the CTO?"), origin="manual")
    detail = store_call(settings, schema, lambda s: s.get_candidate(gamma))
    assert detail["candidate"]["status"] == "watch" and detail["candidate"]["origins"] == ["grok", "manual"]


def test_http_endpoints_end_to_end(settings: Settings, schema: str, seeded: dict[str, str]) -> None:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    with TestClient(app, base_url="http://127.0.0.1:8177") as client:
        listing = client.get("/api/deal-flow/candidates", params=[("origin", "grok"), ("limit", "3")]).json()
        assert listing["ok"] and len(listing["items"]) == 3 and listing["next_cursor"]
        old = client.get("/api/deal-flow/candidates/si-002-alpha", params={"ns": "scout_intake"}).json()
        assert old["ok"] and old["candidate"]["id"] == seeded["Alpha Robotics"]
        assert client.get("/api/deal-flow/candidates/nope").status_code == 404
        decided = client.post(
            f"/api/deal-flow/candidates/{seeded['Delta Space']}/decision", json={"status": "rejected"}
        ).json()
        assert decided == {
            "ok": True,
            "id": seeded["Delta Space"],
            "status": "rejected",
            "previous_status": "new",
            "changed": True,
        }
        stale = client.post(f"/api/deal-flow/candidates/{seeded['Delta Space']}/decision",
                            json={"status": "watch", "expected_status": "new"})  # fmt: skip
        assert stale.status_code == 409 and stale.json()["current"] == "rejected"
