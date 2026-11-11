"""Ingest tagging (review 007): the port against goldens written by the OLD code, the decision 0002 mapping asserted
by hand, the stored-tags adapter, and the interstitial refusal at the intake contract."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from tests.dealflow.test_intake_contract import MemoryStore, company, submission

from projectzero.dealflow.intake.contract import Origin, validate_external
from projectzero.dealflow.intake.service import IntakeService, TrustedBatch
from projectzero.dealflow.ranking import attention, tagging
from projectzero.dealflow.ranking.service import ranking_input
from projectzero.ops import parity_tagging

GOLDEN = json.loads(parity_tagging.GOLDEN.read_text(encoding="utf-8"))


# ── parity with the old code (goldens written by scripts/oracle/tagging_oracle.py) ───────────────────────────────


def test_goldens_come_from_the_clean_old_revision() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert GOLDEN["cases"] == parity_tagging.synthetic_cases() + parity_tagging.live_cases()  # corpus not drifted
    assert GOLDEN["not_ported"] == sorted(parity_tagging.NOT_PORTED)


def test_tables_are_verbatim() -> None:
    assert parity_tagging.diff(GOLDEN["tables"], json.loads(json.dumps(parity_tagging.new_tables()))) == []


@pytest.mark.parametrize("case", GOLDEN["cases"], ids=lambda c: c["key"])
def test_each_case_matches_the_old_scan(case: dict[str, Any]) -> None:
    assert parity_tagging.compare_case(GOLDEN["expected"][case["key"]], parity_tagging.new_case(case)) == []


def test_the_corpus_reaches_the_sensitive_cases() -> None:
    kept = {r["name"]: r for r in GOLDEN["expected"]["synthetic-hi"]["kept"]}
    assert "Cookie Wall" not in kept and "Late Cookie" in kept  # dropped vs match after character 400
    assert kept["Beyond600"]["archetype_hits"] == [3] and "stablecoin" not in kept["Beyond600"]["description"]
    assert kept["N" * 120]["twins"] == ["Nexcade"]  # the twin keyword sits beyond the stored 120-char name
    assert kept["Quirk Zero"]["priority"] == 7  # computed 0 -> "or 5" -> + high bonus 2
    assert kept["Chem One"]["archetype_hits"] == [] and kept["Chem Two"]["archetype_hits"] == [2]
    assert kept["Handel Shop"]["noise"] is True and kept["Bio Spinout"]["opportunistic"] is True
    assert all(r["probation_source"] for r in kept.values())
    assert {r["src_quality"] for r in GOLDEN["expected"]["synthetic-none"]["kept"]} == {0}  # missing reliability
    absorbed = GOLDEN["expected"]["absorb-grok-manual"]["kept"][0]
    assert absorbed["why"][-1] == "Cross-source signal: also seen on Manual"


# ── decision 0002, asserted by hand (independent of the mapping the oracle was fed) ──────────────────────────────


def test_cycle_008_mapped_inputs() -> None:
    entities = parity_tagging.sample_entities()
    assert [e["kind"] for e in entities] == ["company"] * 6 + ["opportunity"]
    expected_tiers = ["manual"] * 6 + ["pre_company"]  # only the opportunity says pre_company (stage and flag)
    for entity, tier in zip(entities, expected_tiers, strict=True):
        inputs = tagging.live_inputs("grok", entity["name"], entity.get("key_fact"), entity.get("stage"),
                                     entity.get("flags"))  # fmt: skip
        assert inputs["description"] == (entity.get("key_fact") or "")  # 0002 #1, full length
        assert inputs["name"] == entity["name"].strip()
        assert inputs["tier"] == tier  # 0002 #2
        assert (inputs["source"], inputs["source_id"], inputs["reliability"]) == ("Grok scout", "live-grok", "medium")
        assert inputs["probation"] is False  # 0002 #6


@pytest.mark.parametrize(
    ("stage", "flags", "tier"),
    [
        ("pre_company", None, "pre_company"),
        ("seed", ["stealth"], "pre_company"),
        (None, ["pre_company"], "pre_company"),
        ("pre_seed", ["spinout"], "manual"),
        (None, None, "manual"),
    ],
)
def test_tier_from_stage_or_flags(stage: Any, flags: Any, tier: str) -> None:
    assert tagging.live_tier(stage, flags) == tier


def test_manual_origin_is_a_manual_source() -> None:
    inputs = tagging.live_inputs("manual", "X", "y", None, None)
    assert (inputs["source"], inputs["source_id"], inputs["reliability"]) == ("Manual", "live-manual", "medium")


def test_a_noisy_live_lead_stays_new_with_no_generated_note() -> None:
    tags = tagging.tag(tagging.live_inputs("grok", "Alpha Holding GmbH", "a holding company", None, None))
    record = tags["record"]
    assert record["noise"] is True and record["decision"] == "new" and record["notes"] == ""  # 0002 #7
    assert "⚠ Looks like holding/consulting/services — likely noise" in record["why"]
    c, inputs = ranking_input({"status": "new", "attrs": {"tagging": tags}})
    assert inputs == "full"
    gated = attention.annotate_v31(c, None)["gated"]
    assert gated and "noise" in gated  # hidden from the Attention Queue by the protected gate


def test_tags_are_deterministic_and_survive_json() -> None:
    inputs = tagging.live_inputs("grok", "Phrase Co", "a counter-drone sensor fusion stack", "pre_company", None)
    tags = tagging.tag(inputs)
    assert tagging.tag(copy.deepcopy(inputs)) == tags
    stored = json.loads(json.dumps(tags))  # what jsonb gives back
    assert stored == tags
    assert stored["record"]["archetype_hits"] == [6, 5]  # ordered list[int], as the old producer emitted
    assert all(type(h) is int for h in stored["record"]["archetype_hits"])
    assert tagging.tag(stored["inputs"], stored["sightings"]) == stored


def test_a_sighting_is_added_once_and_never_by_the_first_origin() -> None:
    inputs = tagging.live_inputs("grok", "Acme", "freight forwarding agents", None, None)
    sighting = tagging.sighting_for("manual", None, None, "sub-1")
    once = tagging.tag(inputs, [sighting])["record"]
    assert once["priority"] == tagging.tag(inputs)["record"]["priority"] + 2
    assert once["all_source_ids"] == ["live-grok", "live-manual"]
    twice = tagging.tag(inputs, [sighting, tagging.sighting_for("manual", None, None, "sub-2")])["record"]
    assert twice == once
    same = tagging.tag(inputs, [tagging.sighting_for("grok", None, None, "sub-3")])["record"]
    assert same == tagging.tag(inputs)["record"] | {"also_seen": []}  # old absorb: setdefault only, nothing scored


# ── the ranking adapter ─────────────────────────────────────────────────────────────────────────────────────────


def test_adapter_reads_stored_tags_with_operator_status_and_notes() -> None:
    tags = tagging.tag(tagging.live_inputs("grok", "Twin Seeker", "accounting ledger bookkeeping", None, None))
    row = {"status": "watch", "attrs": {"tagging": tags, "notes": "met them at a fair"}, "name": "ignored"}
    c, inputs = ranking_input(row)
    assert inputs == "full"
    assert c == {**tags["record"], "decision": "watch", "notes": "met them at a fair"}


def test_untagged_and_unknown_version_rows_stay_partial() -> None:
    row = {"status": "new", "name": "Pre 007", "key_fact": "x", "attrs": {}, "origins": ["grok"]}
    assert ranking_input(row)[1] == "partial"
    tags = tagging.tag(tagging.live_inputs("grok", "A", "b", None, None)) | {"version": 999}
    assert ranking_input({**row, "attrs": {"tagging": tags}})[1] == "partial"


def test_an_imported_record_wins_over_tags() -> None:
    legacy = {"decision": "new", "discovery_tier": "registry", "source_id": "old-src", "name": "Old", "notes": "n"}
    tags = tagging.tag(tagging.live_inputs("grok", "A", "b", None, None))
    c, inputs = ranking_input({"status": "new", "legacy": legacy, "attrs": {"tagging": tags}})
    assert inputs == "full" and c["source_id"] == "old-src" and c["notes"] == "n"


# ── interstitial refusal, before identity grouping ──────────────────────────────────────────────────────────────


def test_an_interstitial_entity_refuses_an_external_delivery() -> None:
    wall = company(name="Cookie settings", key_fact="We use cookies", website="https://wall.example.com")
    payload = submission(company(), wall)
    issues = validate_external(payload)
    assert [i.path for i in issues] == ["$/entities/1"]
    assert "cookie banner" in issues[0].message
    store = MemoryStore()
    assert IntakeService(store).submit_external(payload, submitted_by="grok").outcome == "rejected"
    assert IntakeService(store).submit_external(copy.deepcopy(payload), submitted_by="grok").outcome == "rejected"
    assert store.rows == []  # nothing written, on the first try or the replay


def test_interstitial_text_after_character_400_is_not_refused() -> None:
    fact = "x" * 400 + " we use cookies"
    assert validate_external(submission(company(key_fact=fact))) == []


def test_people_and_events_are_not_checked() -> None:
    person = {"kind": "person", "name": "Captcha Researcher", "external_id": "p-1"}
    assert [i for i in validate_external(submission(company(), person)) if "cookie" in i.message] == []


class RecordingResolver:
    def __init__(self) -> None:
        self.seen: list[list[int]] = []

    def resolve_submission(self, submission: Any, entities: Any) -> list[dict[str, Any]]:
        self.seen.append([index for index, _ in entities])
        return [{"index": index} for index, _ in entities]


def test_a_mixed_trusted_batch_refuses_the_wall_and_its_dependants_before_resolution() -> None:
    wall = company(name="Access denied", key_fact="error 403", website="https://shared.example.com",
                   external_id="wall")  # fmt: skip
    linked = company(name="Linked Co", website="https://linked.example.com", related_external_ids=["wall"])
    good = company()
    batch = TrustedBatch(Origin.REGISTRY_SCAN, "registry-scanner", [good, wall, linked])
    store, resolver = MemoryStore(), RecordingResolver()
    result = IntakeService(store, resolver).submit_trusted(batch)
    assert result.outcome == "partial"
    assert [index for index, _ in result.refused] == [1, 2]
    assert resolver.seen == [[0]]  # the refused wall never supplies its domain / id to grouping
    replay = IntakeService(store, resolver).submit_trusted(batch)
    assert replay.outcome == "duplicate" and resolver.seen == [[0]]


@pytest.mark.parametrize("bad_kind", [["company"], {"kind": "company"}, 7, None])
def test_a_malformed_kind_is_refused_by_index_and_its_sibling_still_resolves(bad_kind: Any) -> None:
    malformed = company(name="Broken Kind", website="https://broken.example.org") | {"kind": bad_kind}
    good = company()
    batch = TrustedBatch(Origin.REGISTRY_SCAN, "registry-scanner", [malformed, good])
    store, resolver = MemoryStore(), RecordingResolver()
    result = IntakeService(store, resolver).submit_trusted(batch)  # must not raise
    assert result.outcome == "partial" and result.accepted == 1
    assert [index for index, _ in result.refused] == [0]
    assert all(issue.path.startswith("$/entities/0") for issue in result.refused[0][1])
    assert resolver.seen == [[1]]
    assert len(store.rows) == 1 and store.rows[0].outcome_detail["refused"][0]["index"] == 0
