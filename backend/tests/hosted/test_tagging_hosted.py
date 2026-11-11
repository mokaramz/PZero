"""Review 007 through the PRODUCTION path: live delivery -> intake tags -> stored attrs -> adapter -> HTTP. The
Cycle 008 ranking must equal the OLD per-source output ranked by the old ``annotate_v31`` (oracle goldens).
Scratch schemas only (``scripts/db.ps1 itest``)."""

from __future__ import annotations

import copy
import json
import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from projectzero.api.app import create_app
from projectzero.core.config import Settings
from projectzero.core.db import connect, transaction
from projectzero.dealflow.intake.postgres import PostgresIntake
from projectzero.dealflow.intake.service import IntakeResult, IntakeService
from projectzero.ops import parity_tagging
from projectzero.ops.db_check import _scratch_sql
from projectzero.ops.parity_ranking import diff

pytestmark = pytest.mark.hosted
GOLDEN = json.loads(parity_tagging.GOLDEN.read_text(encoding="utf-8"))


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
        admin.execute(
            f"insert into {name}.documents (key, body) values ('inbox.json#rest', %s)".encode(),
            (Jsonb({"last_run": GOLDEN["last_run"]}),),
        )
        yield name
    finally:
        admin.execute(f"drop schema if exists {name} cascade".encode())
        admin.close()


def submit(settings: Settings, schema: str, payload: dict[str, Any]) -> IntakeResult:
    with transaction(settings.db_url) as conn:
        store = PostgresIntake(conn, schema)
        return IntakeService(store, resolver=store).submit_external(payload, submitted_by=payload["origin"])


def query(settings: Settings, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    with connect(settings.db_url, autocommit=True) as conn:
        return conn.execute(sql.encode(), params or None).fetchall()


def delivery(*entities: dict[str, Any], origin: str = "grok") -> dict[str, Any]:
    return {"contract_version": "1.0", "origin": origin, "external_ref": secrets.token_hex(3),
            "submitted_at": "2026-11-11T09:00:00+01:00", "entities": list(entities)}  # fmt: skip


def company(name: str, website: str, key_fact: str, **extra: Any) -> dict[str, Any]:
    return {"kind": "company", "name": name, "website": website, "key_fact": key_fact,
            "evidence": [{"url": f"{website}/news"}]} | extra  # fmt: skip


def ranking(settings: Settings, schema: str, candidate_id: str) -> dict[str, Any]:
    app = create_app(Settings(db_url=settings.db_url, schema=schema))
    with TestClient(app, base_url="http://127.0.0.1:8177") as client:
        detail = client.get(f"/api/deal-flow/candidates/{candidate_id}").json()
        listed = {i["id"]: i for i in client.get("/api/deal-flow/candidates", params={"limit": 200}).json()["items"]}
    assert listed[candidate_id]["ranking"] == detail["ranking"]  # list and detail read the same tags
    result: dict[str, Any] = detail["ranking"]
    return result


def attrs_of(settings: Settings, schema: str, candidate_id: str) -> dict[str, Any]:
    row = query(settings, f"select attrs from {schema}.candidates where id = %s", candidate_id)
    value: dict[str, Any] = row[0][0]
    return value


def test_cycle_008_through_intake_and_api_matches_the_old_scan(settings: Settings, schema: str) -> None:
    sample = json.loads(parity_tagging.SAMPLE.read_text(encoding="utf-8"))
    result = submit(settings, schema, sample)
    assert result.outcome == "accepted"
    tagged = [r for r in result.resolution if r["kind"] in ("company", "opportunity")]
    assert len(tagged) == 7
    mismatches = []
    for index, res in enumerate(tagged):
        got = ranking(settings, schema, res["candidate_id"])
        assert got["inputs"] == "full"
        want = GOLDEN["expected"][f"cycle008-{index}"]["attention"][0]
        mismatches += [f"cycle008-{index}{d}" for d in diff(want, got["attention_v2"])]
        stored = attrs_of(settings, schema, res["candidate_id"])["tagging"]["record"]
        old = GOLDEN["expected"][f"cycle008-{index}"]["kept"][0]
        assert stored["archetype_hits"] == old["archetype_hits"]  # ordered ints through jsonb
        assert stored["why"] == old["why"] and stored["priority"] == old["priority"]
    assert mismatches == []
    for res in result.resolution:  # people / events are not tagged
        if res["kind"] not in ("company", "opportunity"):
            assert "tagging" not in attrs_of(settings, schema, res["candidate_id"])


def test_replay_keeps_tags_a_second_origin_is_one_sighting(settings: Settings, schema: str) -> None:
    # The contract caps key_fact at 600 characters (so the 600 cut is a no-op live; the offline corpus covers it),
    # but a name may be 200: a keyword past the stored 120-character name must still tag, from the full name.
    name = "Ledger Rail " + "Operations " * 10 + "Stablecoin Payments"
    assert name.lower().index("stablecoin") > 120
    lead = company(name, "https://ledger-rail.de", "Industrial tools for operators across Europe.")
    first = submit(settings, schema, delivery(lead)).resolution[0]
    cid = first["candidate_id"]
    tags = attrs_of(settings, schema, cid)["tagging"]
    assert tags["record"]["archetype_hits"] == [3]  # found on the full name
    assert tags["record"]["name"] == name[:120] and "Stablecoin" not in tags["record"]["name"]

    again = submit(settings, schema, delivery(copy.deepcopy(lead))).resolution[0]  # same entity, new delivery
    assert again["candidate_id"] == cid and again["result"] == "re_reported"
    assert attrs_of(settings, schema, cid)["tagging"] == tags  # unchanged inputs -> identical tags
    before = ranking(settings, schema, cid)

    manual = company(name, "https://ledger-rail.de", "pasted by the operator")
    assert submit(settings, schema, delivery(manual, origin="manual")).resolution[0]["candidate_id"] == cid
    seen = attrs_of(settings, schema, cid)["tagging"]
    assert [s["source"] for s in seen["sightings"]] == ["Manual"]
    assert seen["record"]["priority"] == tags["record"]["priority"] + 2
    assert seen["record"]["why"][-1] == "Cross-source signal: also seen on Manual"
    assert seen["inputs"] == tags["inputs"]  # the first delivery's key fact stays the description
    assert ranking(settings, schema, cid)["inputs"] == "full" and before["inputs"] == "full"

    submit(settings, schema, delivery(copy.deepcopy(manual), origin="manual"))
    assert attrs_of(settings, schema, cid)["tagging"] == seen  # a sighting is added once


def seed_existing(settings: Settings, schema: str, domain: str, legacy: Any, attrs: dict[str, Any]) -> str:
    with connect(settings.db_url, autocommit=True) as conn:
        company_id = conn.execute(
            f"insert into {schema}.companies (name, normalized_name) values ('Seeded Co', 'seeded co') returning id".encode()
        ).fetchone()[0]  # type: ignore[index]
        conn.execute(
            f"insert into {schema}.company_identifiers (company_id, kind, value, source) values (%s, 'domain', %s, 'legacy_dealflow')".encode(),
            (company_id, domain),
        )
        cid = conn.execute(
            f"insert into {schema}.candidates (company_id, name, status, origins, key_fact, legacy, attrs) "
            "values (%s, 'Seeded Co', 'watch', %s, 'old fact', %s, %s) returning id".encode(),
            (company_id, ["legacy_dealflow"] if legacy else ["grok"], Jsonb(legacy) if legacy else None, Jsonb(attrs)),
        ).fetchone()[0]  # type: ignore[index]
        conn.execute(
            f"insert into {schema}.candidate_aliases (namespace, alias_id, candidate_id) values ('candidate', %s, %s)".encode(),
            (str(cid), cid),
        )
    return str(cid)


def test_an_imported_candidate_keeps_its_record_ranking_and_notes(settings: Settings, schema: str) -> None:
    legacy = {"id": "old-1", "name": "Seeded Co", "decision": "watch", "discovery_tier": "registry",
              "source_id": "de-hrb", "source": "Handelsregister", "description": "Industrial AI for shop floors",
              "archetype_hits": [7], "why": ["Archetype keyword match: #7 x"], "notes": "old note"}  # fmt: skip
    cid = seed_existing(settings, schema, "seeded-co.de", legacy, {"notes": "operator note"})
    before = ranking(settings, schema, cid)
    lead = company("Seeded Co", "https://seeded-co.de", "a holding company")  # noisy, would retag if wrong
    assert submit(settings, schema, delivery(lead)).resolution[0]["candidate_id"] == cid
    after_attrs = attrs_of(settings, schema, cid)
    assert "tagging" not in after_attrs and after_attrs["notes"] == "operator note"
    assert query(settings, f"select legacy from {schema}.candidates where id = %s", cid)[0][0] == legacy
    assert ranking(settings, schema, cid) == before and before["inputs"] == "full"


def test_a_pre_007_untagged_lead_is_not_retagged(settings: Settings, schema: str) -> None:
    cid = seed_existing(settings, schema, "untagged-co.de", None, {"notes": ""})
    assert ranking(settings, schema, cid)["inputs"] == "partial"
    submit(settings, schema, delivery(company("Seeded Co", "https://untagged-co.de", "freight agents")))
    assert "tagging" not in attrs_of(settings, schema, cid)
    assert ranking(settings, schema, cid)["inputs"] == "partial"


def test_a_noisy_live_lead_is_new_hidden_and_has_no_generated_note(settings: Settings, schema: str) -> None:
    res = submit(settings, schema, delivery(company("Alpha Holding GmbH", "https://alpha.example.com",
                                                    "a holding and consulting company"))).resolution[0]  # fmt: skip
    status = query(settings, f"select status from {schema}.candidates where id = %s", res["candidate_id"])[0][0]
    assert status == "new"
    attrs = attrs_of(settings, schema, res["candidate_id"])
    assert "notes" not in attrs and attrs["tagging"]["record"]["notes"] == ""
    got = ranking(settings, schema, res["candidate_id"])
    assert got["inputs"] == "full" and got["attention_v2"]["gated"] and "noise" in got["attention_v2"]["gated"]


def test_a_mixed_delivery_with_an_interstitial_writes_nothing_even_on_replay(settings: Settings, schema: str) -> None:
    payload = delivery(company("Real Co", "https://real.example.com", "freight agents"),
                       company("Please enable JavaScript", "https://real.example.com", "javascript is required"))  # fmt: skip
    for attempt in (payload, copy.deepcopy(payload)):
        result = submit(settings, schema, attempt)
        assert result.outcome == "rejected" and [i.path for i in result.issues] == ["$/entities/1"]
    assert query(settings, f"select count(*) from {schema}.intake_submissions")[0][0] == 0
    assert query(settings, f"select count(*) from {schema}.candidates")[0][0] == 0
