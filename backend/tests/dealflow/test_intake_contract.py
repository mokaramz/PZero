"""Intake contract and service: review 001 findings #3 (origin boundary, registry path) and #5 (evidence/text)."""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from typing import Any

import pytest

from projectzero.dealflow.intake.contract import Origin, canonical_sha256, validate_entity, validate_external
from projectzero.dealflow.intake.service import IntakeService, SubmissionRecord, TrustedBatch
from projectzero.dealflow.sources.registry import entity_from_registry_record


class MemoryStore:
    """In-memory stand-in with the same contract as pz.record_submission: atomic insert-if-absent on sha256."""

    def __init__(self) -> None:
        self.rows: list[SubmissionRecord] = []
        self._lock = threading.Lock()

    def insert_if_absent(self, submission: SubmissionRecord) -> bool:
        with self._lock:
            if any(r.sha256 == submission.sha256 for r in self.rows):
                return False
            self.rows.append(submission)
            return True


def company(**overrides: Any) -> dict[str, Any]:
    entity: dict[str, Any] = {
        "kind": "company",
        "name": "Acme Robotics GmbH",
        "website": "https://acme-robotics.example.com",
        "location": {"city": "München", "country": "DE"},
        "key_fact": "Spun out of TUM in October 2026",
        "evidence": [{"url": "https://www.tum.de/news/acme"}],
    }
    entity.update(overrides)
    return entity


def submission(*entities: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "contract_version": "1.0",
        "origin": "grok",
        "external_ref": "MW-2026-11-12",
        "submitted_at": "2026-11-12T08:00:00+01:00",
        "entities": list(entities) or [company()],
    }
    doc.update(overrides)
    return doc


# ── the happy path and Grok's real-world shapes ──────────────────────────────────────────────────────────────────


def test_valid_grok_submission_passes() -> None:
    assert validate_external(submission()) == []


def test_empty_delivery_is_a_valid_nothing_material_report() -> None:
    doc = submission()
    doc["entities"] = []
    assert validate_external(doc) == []


def test_scout_packet_fields_are_accepted() -> None:
    entity = company(
        external_id="scout:acme-robotics",
        source_scouts=["Lane 01", "Lane 04"],
        intent="create",
        flags=["spinout"],
        scout_assessment={"system_novelty": "CYCLE-NEW", "venture_exposure": "VE-0", "attention_state": "MONITOR"},
        claims=[
            {"text": "Incorporated as a GmbH in Munich", "label": "FACT", "evidence_urls": ["https://www.tum.de/x"]},
            {"text": "Likely raising a pre-seed round", "label": "INFERENCE"},
        ],
    )
    event = {
        "kind": "event",
        "name": "TUM Venture Lab demo day",
        "key_fact": "Twelve deep-tech teams pitch to investors",
        "evidence": [{"url": "https://www.tum-venture-labs.de/demo-day"}],
        "event": {"starts_on": "2026-12-03", "city": "Munich", "ax_class": "AX-1"},
    }
    assert validate_external(submission(entity, event)) == []


def test_fact_claim_without_evidence_is_refused() -> None:
    entity = company(claims=[{"text": "Raised two million from angels", "label": "FACT"}])
    assert validate_external(submission(entity))


def test_event_needs_a_date_but_never_an_invented_time() -> None:
    event = {
        "kind": "event",
        "name": "Demo day",
        "key_fact": "Twelve teams pitch to investors",
        "evidence": [{"url": "https://example.org/demo"}],
        "event": {"city": "Munich"},
    }
    assert validate_external(submission(event))
    event["event"]["starts_on"] = "2026-12-03"
    assert validate_external(submission(event)) == []


# ── finding #5: evidence must be a web URL with a host; text must be meaningful ─────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "mailto:founder@acme.example.com",
        "file:///C:/secret.txt",
        "javascript:alert(1)",
        "https://localhost/x",
        "https:///no-host",
        "ftp://files.example.com/a",
        "https://exa mple.com/a",
        "www.example.com/no-scheme",
    ],
)
def test_non_web_evidence_urls_are_refused(url: str) -> None:
    issues = validate_external(submission(company(evidence=[{"url": url}])))
    assert any(i.path == "$/entities/0/evidence/0/url" for i in issues), issues


@pytest.mark.parametrize("key_fact", ["        ", "\t\n  \n", "..........", "a b c d e f", "x"])
def test_blank_or_meaningless_key_fact_is_refused(key_fact: str) -> None:
    issues = validate_external(submission(company(key_fact=key_fact)))
    assert any(i.path == "$/entities/0/key_fact" for i in issues), issues


@pytest.mark.parametrize("name", ["   ", "---", ""])
def test_blank_name_is_refused(name: str) -> None:
    assert any(i.path == "$/entities/0/name" for i in validate_external(submission(company(name=name))))


def test_accented_names_and_facts_pass() -> None:
    assert validate_external(submission(company(name="Ölwerk Süd", key_fact="Gegründet in Zürich, Oktober 2026"))) == []


def test_formats_are_enforced() -> None:
    issues = validate_external(submission(submitted_at="yesterday"))
    assert any(i.path == "$/submitted_at" for i in issues), issues


# ── finding #3: the external origin boundary and the trusted registry path ─────────────────────────────────────


@pytest.mark.parametrize("origin", ["registry_scan", "research", "legacy_scout00", "legacy_native", "legacy_dealflow"])
def test_external_caller_cannot_assert_a_server_side_origin(origin: str) -> None:
    issues = validate_external(submission(origin=origin))
    assert [i.path for i in issues] == ["$/origin"]
    assert "server-side only" in issues[0].message


def test_external_rejection_writes_nothing() -> None:
    store = MemoryStore()
    result = IntakeService(store).submit_external(submission(origin="registry_scan"), submitted_by="grok")
    assert result.outcome == "rejected"
    assert store.rows == []


def test_trusted_batch_refuses_external_origins() -> None:
    with pytest.raises(ValueError, match="external envelope"):
        TrustedBatch(origin=Origin.GROK, submitted_by="scheduler", entities=[])


NIH_RECORD = {
    "name": "Via Therapeutics, Llc",
    "source": "NIH RePORTER (SBIR R43/R44)",
    "source_url": "https://api.reporter.nih.gov/v2/projects/search",
    "date": "2026-10-05",
    "date_kind": "detected",
    "country": "USA",
    "geo": ["US"],
    "description": "NIH SBIR: Development of a shelf-stable universal mucosal HA-vaccine for influenza",
    "sectors": ["bio"],
    "entity_ids": {"duns": "079642993"},
}


def test_registry_record_maps_to_a_valid_entity_without_inventing_fields() -> None:
    entity = entity_from_registry_record(NIH_RECORD)
    assert validate_entity(entity) == []
    assert entity["location"] == {"country": "US"}
    assert entity["registry_ids"] == {"duns": "079642993"}
    assert "signal_date" not in entity  # a detection date is not a signal date
    assert "website" not in entity


def test_registry_delivery_through_the_trusted_path() -> None:
    store = MemoryStore()
    service = IntakeService(store)
    broken = {**NIH_RECORD, "name": "", "source_url": None}
    batch = TrustedBatch(
        origin=Origin.REGISTRY_SCAN,
        submitted_by="scheduler:deal_flow_scan",
        external_ref="scan-2026-11-10",
        entities=[entity_from_registry_record(NIH_RECORD), entity_from_registry_record(broken)],
    )

    result = service.submit_trusted(batch)

    assert result.outcome == "partial"
    assert result.accepted == 1
    assert [index for index, _ in result.refused] == [1]
    assert len(store.rows) == 1 and store.rows[0].origin is Origin.REGISTRY_SCAN
    assert store.rows[0].outcome_detail["refused"][0]["index"] == 1
    # replaying the same scan changes nothing
    assert service.submit_trusted(batch).outcome == "duplicate"
    assert len(store.rows) == 1


def test_same_external_delivery_twice_is_a_no_op_even_reordered() -> None:
    store = MemoryStore()
    service = IntakeService(store)
    doc = submission()
    reordered = dict(reversed(list(copy.deepcopy(doc).items())))
    assert canonical_sha256(doc) == canonical_sha256(reordered)
    assert service.submit_external(doc, submitted_by="grok").outcome == "accepted"
    assert service.submit_external(reordered, submitted_by="grok").outcome == "duplicate"
    assert len(store.rows) == 1


# ── rev 2 #1: a missing registry id must never become a strong identifier ───────────────────────────────────────


@pytest.mark.parametrize("missing", [None, "None", "null", " ", "", "N/A", "unknown", 0, "0", "-", True, 1.5, [], {}])
def test_missing_or_placeholder_registry_ids_are_dropped(missing: Any) -> None:
    entity = entity_from_registry_record({**NIH_RECORD, "entity_ids": {"duns": missing}})
    assert "registry_ids" not in entity
    assert validate_entity(entity) == []


def test_two_records_without_duns_share_no_registry_identifier() -> None:
    a = entity_from_registry_record({**NIH_RECORD, "name": "Alpha Bio Inc", "entity_ids": {"duns": None}})
    b = entity_from_registry_record({**NIH_RECORD, "name": "Beta Labs LLC", "entity_ids": {"duns": None}})
    assert a.get("registry_ids") is None and b.get("registry_ids") is None


def test_integer_registry_id_is_kept_as_text() -> None:
    entity = entity_from_registry_record({**NIH_RECORD, "entity_ids": {"duns": 79642993}})
    assert entity["registry_ids"] == {"duns": "79642993"}


@pytest.mark.parametrize(
    "placeholder", ["None", "null", "NULL", "n/a", "NA", "Unknown", "TBD", "000", "--", "?", " none "]
)
def test_contract_refuses_placeholder_registry_ids_from_any_caller(placeholder: str) -> None:
    issues = validate_external(submission(company(registry_ids={"duns": placeholder})))
    assert any(i.path == "$/entities/0/registry_ids/duns" for i in issues), issues


# ── rev 2 #2: concurrent deliveries — exactly one accepted, one duplicate, one row ──────────────────────────────


def _race(store: MemoryStore, call: Callable[[], Any], runners: int = 2) -> list[str]:
    barrier = threading.Barrier(runners)
    outcomes: list[str] = []

    def run() -> None:
        barrier.wait()
        outcomes.append(call().outcome)

    threads = [threading.Thread(target=run) for _ in range(runners)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return sorted(outcomes)


@pytest.mark.parametrize("attempt", range(25))
def test_overlapping_external_replay(attempt: int) -> None:
    store = MemoryStore()
    service = IntakeService(store)
    doc = submission()
    assert _race(store, lambda: service.submit_external(copy.deepcopy(doc), submitted_by="grok")) == [
        "accepted",
        "duplicate",
    ]
    assert len(store.rows) == 1


@pytest.mark.parametrize("attempt", range(25))
def test_overlapping_trusted_replay(attempt: int) -> None:
    store = MemoryStore()
    service = IntakeService(store)
    batch = TrustedBatch(
        origin=Origin.REGISTRY_SCAN, submitted_by="scheduler", entities=[entity_from_registry_record(NIH_RECORD)]
    )
    assert _race(store, lambda: service.submit_trusted(batch), runners=3) == ["accepted", "duplicate", "duplicate"]
    assert len(store.rows) == 1


def test_service_never_looks_up_before_inserting() -> None:
    # A store with only the atomic method: any "find, then insert" code path would fail with AttributeError.
    class AtomicOnly:
        def __init__(self) -> None:
            self.calls = 0

        def insert_if_absent(self, submission: SubmissionRecord) -> bool:
            self.calls += 1
            return self.calls == 1

    store = AtomicOnly()
    service = IntakeService(store)
    assert service.submit_external(submission(), submitted_by="grok").outcome == "accepted"
    assert service.submit_external(submission(), submitted_by="grok").outcome == "duplicate"


# ── rev 2 #3: names and facts in any writing system ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "key_fact"),
    [
        ("王小明", "2026年10月在深圳成立了新公司"),
        ("株式会社テックラボ", "2026年10月に東京大学からスピンアウトした"),
        ("شركة النور للتقنية", "تأسست الشركة في دبي في أكتوبر 2026"),
        ("Ελληνική Ρομποτική", "Ιδρύθηκε στην Αθήνα τον Οκτώβριο"),
        ("한국로봇", "2026년 10월 서울에서 설립"),
        ("Ölwerk Süd", "Gegründet in Zürich, Oktober 2026"),
    ],
)
def test_non_latin_names_and_facts_pass(name: str, key_fact: str) -> None:
    assert validate_external(submission(company(name=name, key_fact=key_fact))) == []


@pytest.mark.parametrize(
    "blank",
    ["　" * 4, "。" * 5, "—" * 7, "、" * 4, "！？" * 2, " " * 4],
)
def test_blank_text_in_other_scripts_is_refused(blank: str) -> None:
    issues = validate_external(submission(company(name=blank, key_fact=blank)))
    paths = {i.path for i in issues}
    assert {"$/entities/0/name", "$/entities/0/key_fact"} <= paths, issues


# ── linked entities: repeated external ids and dangling references (Codex rev 2 note) ───────────────────────────


def founder_and_opportunity() -> list[dict[str, Any]]:
    person = {
        "kind": "person",
        "name": "Jana Novak",
        "external_id": "scout:jana-novak",
        "related_external_ids": ["scout:novak-opportunity"],
        "key_fact": "Left ETH robotics lab to start a company",
        "evidence": [{"url": "https://janasite.example.org/about"}],
    }
    opportunity = {
        "kind": "opportunity",
        "name": "Novak robotics opportunity",
        "external_id": "scout:novak-opportunity",
        "related_external_ids": ["scout:jana-novak"],
        "key_fact": "Pre-company project announced at ETH demo day",
        "evidence": [{"url": "https://ethz.ch/news/demo-day"}],
    }
    return [person, opportunity]


def test_linked_person_and_opportunity_pass() -> None:
    assert validate_external(submission(*founder_and_opportunity())) == []


def test_repeated_external_id_refuses_the_delivery() -> None:
    person, opportunity = founder_and_opportunity()
    opportunity["external_id"] = person["external_id"]
    opportunity["related_external_ids"] = []
    person["related_external_ids"] = []
    issues = validate_external(submission(person, opportunity))
    assert [i.path for i in issues] == ["$/entities/1/external_id"]
    assert "already used by entity 0" in issues[0].message


def test_reference_to_a_missing_entity_is_refused() -> None:
    person, _ = founder_and_opportunity()
    issues = validate_external(submission(person))
    assert [i.path for i in issues] == ["$/entities/0/related_external_ids/0"]
    assert "no entity in this delivery" in issues[0].message


def test_self_reference_is_refused() -> None:
    person, _ = founder_and_opportunity()
    person["related_external_ids"] = [person["external_id"]]
    assert [i.path for i in validate_external(submission(person))] == ["$/entities/0/related_external_ids/0"]


def test_trusted_path_refuses_only_the_repeated_entity() -> None:
    store = MemoryStore()
    a = entity_from_registry_record(NIH_RECORD) | {"external_id": "nih:1"}
    b = entity_from_registry_record({**NIH_RECORD, "name": "Other Co"}) | {"external_id": "nih:1"}
    result = IntakeService(store).submit_trusted(
        TrustedBatch(origin=Origin.REGISTRY_SCAN, submitted_by="scheduler", entities=[a, b])
    )
    assert result.outcome == "partial"
    assert [index for index, _ in result.refused] == [1]


# ── Grok's real Cycle 008 delivery (docs/team/samples) stays valid as the contract evolves ──────────────────────


def test_grok_cycle_008_sample_is_accepted_once() -> None:
    import json

    from projectzero.core.paths import REPO_ROOT

    doc = json.loads((REPO_ROOT / "docs/team/samples/grok_cycle_sample.json").read_text(encoding="utf-8"))
    assert validate_external(doc) == []
    store = MemoryStore()
    service = IntakeService(store)
    assert service.submit_external(doc, submitted_by="grok").outcome == "accepted"
    assert service.submit_external(doc, submitted_by="grok").outcome == "duplicate"
    assert len(store.rows) == 1


# ── rev 3: references inside partial trusted batches resolve only within the accepted set ─────────────────────


def linked(external_id: str, *refs: Any, evidence: bool = True, name: str | None = None) -> dict[str, Any]:
    entity = entity_from_registry_record({**NIH_RECORD, "name": name or f"Company {external_id}"})
    entity["external_id"] = external_id
    if refs:
        entity["related_external_ids"] = list(refs)
    if not evidence:
        entity["evidence"] = []
    return entity


def test_refusal_propagates_along_references_and_spares_the_rest() -> None:
    entities = [
        linked("a", "b"),  # 0: A -> B
        linked("b", "c"),  # 1: B -> C
        linked("c", evidence=False),  # 2: C invalid (empty evidence)
        linked("d"),  # 3: unrelated, valid
        linked("e", {"not": "a string"}),  # 4: malformed reference
        linked("f", "g"),  # 5: F <-> G, valid pair
        linked("g", "f"),  # 6
    ]
    store = MemoryStore()
    result = IntakeService(store).submit_trusted(
        TrustedBatch(origin=Origin.REGISTRY_SCAN, submitted_by="scheduler", entities=entities)
    )

    assert result.outcome == "partial"
    assert [index for index, _ in result.refused] == [0, 1, 2, 4]
    assert result.accepted == 3  # D, F, G
    reasons = {index: " ".join(i.message for i in issues) for index, issues in result.refused}
    assert "whose entity 2 was refused" in reasons[1]
    assert "whose entity 1 was refused" in reasons[0]
    assert store.rows[0].outcome_detail["accepted"] == 3


def test_every_accepted_link_resolves_within_the_accepted_set() -> None:
    entities = [
        linked("a", "b"),
        linked("b", "c"),
        linked("c", evidence=False),
        linked("d"),
        linked("f", "g"),
        linked("g", "f"),
    ]
    result = IntakeService(MemoryStore()).submit_trusted(
        TrustedBatch(origin=Origin.REGISTRY_SCAN, submitted_by="scheduler", entities=entities)
    )
    refused = {index for index, _ in result.refused}
    accepted_ids = {e["external_id"] for i, e in enumerate(entities) if i not in refused}
    for i, entity in enumerate(entities):
        if i not in refused:
            assert set(entity.get("related_external_ids", [])) <= accepted_ids


def test_reference_to_the_refused_repeat_holder_points_at_the_first_holder() -> None:
    entities = [linked("x"), linked("x", name="Second X"), linked("y", "x")]
    result = IntakeService(MemoryStore()).submit_trusted(
        TrustedBatch(origin=Origin.REGISTRY_SCAN, submitted_by="scheduler", entities=entities)
    )
    assert [index for index, _ in result.refused] == [1]  # y -> x resolves to entity 0, which is accepted


def test_malformed_values_never_raise() -> None:
    from projectzero.dealflow.intake.contract import cross_entity_issues

    junk: list[Any] = [
        "not an entity",
        None,
        {"external_id": 5},
        {"related_external_ids": "x"},
        {"related_external_ids": [None, 3, ["a"]]},
    ]
    assert cross_entity_issues(junk) == {}
    assert validate_external(submission(company(related_external_ids=[{"bad": 1}])))  # schema refuses, no TypeError


def test_cycle_of_three_with_one_invalid_member_refuses_the_whole_cycle() -> None:
    entities = [linked("p", "q"), linked("q", "r"), linked("r", "p", evidence=False), linked("s")]
    result = IntakeService(MemoryStore()).submit_trusted(
        TrustedBatch(origin=Origin.REGISTRY_SCAN, submitted_by="scheduler", entities=entities)
    )
    assert [index for index, _ in result.refused] == [0, 1, 2]
    assert result.accepted == 1
