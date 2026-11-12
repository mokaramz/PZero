"""Legacy import planning on a synthetic data folder shaped like the real one (dict- and list-keyed collections)."""

from __future__ import annotations

import hashlib
import itertools
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from projectzero.network.identity import canonical_openalex, canonical_orcid, classify_profile_url
from projectzero.ops.legacy.apply import apply_plan, fingerprint
from projectzero.ops.legacy.companies import CompanyBook
from projectzero.ops.legacy.plan import ImportPlan, build_plan
from projectzero.ops.legacy.source import LegacySnapshot, LegacySourceError

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def cand(cid: str, name: str, decision: str = "new", **extra: Any) -> dict[str, Any]:
    return {
        "id": cid, "name": name, "decision": decision, "source": "NIH", "source_id": "us-nih",
        "source_url": f"https://reporter.example.gov/{cid}", "first_seen": "2026-10-01 09:00:00",
        "last_observed": "2026-10-05 10:00:00", "country": "USA", "geo": ["US"], "description": f"{name} project",
        "why": ["fits robotics"], "sectors": ["robotics"], "location": "USA", "date": "2026-10-01",
    } | extra  # fmt: skip


def write(root: Path, rel: str, value: Any, *, raw: bytes | None = None) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw if raw is not None else json.dumps(value, ensure_ascii=False).encode("utf-8"))


@pytest.fixture
def legacy(tmp_path: Path) -> Path:
    root = tmp_path / "project-zero-data"
    write(root, "sources.json", {"sources": [{"id": "us-nih", "name": "NIH", "kind": "api", "enabled": True}]})
    write(root, "real_data.json", {"signals": [
        {"company": "EVASIVE Robotics", "website": "https://evasive-robotics.example.com", "status": "new",
         "verified": False, "scores": {"total": 7}, "country": "DE"},
    ]})  # fmt: skip
    write(root, "inbox.json", {"candidates": [
        cand("aaaaaaaaaaa1", "Duplex Bio LLC", entity_ids={"duns": "111"}, first_seen="2026-10-02 09:00:00"),
        cand("aaaaaaaaaaa2", "Duplex Bio, LLC", "research", entity_ids={"duns": "111"}),  # same DUNS, more advanced
        cand("aaaaaaaaaaa3", "Duplex Bio", "rejected", entity_ids={"duns": "111"}),  # closed: kept apart
        cand("aaaaaaaaaaa4", "UNKNOWN"),
        cand("aaaaaaaaaaa5", "Kontext", also_seen=[{"source": "Feed", "source_id": "legacy-gone",
                                                     "url": "https://feed.example.com/k", "first_seen": "2026-10-03 08:00:00"}]),
        cand("aaaaaaaaaaa6", "Nulla Labs", entity_ids={"duns": "None"}),
        cand("aaaaaaaaaaa7", "Vacua Labs", entity_ids={"duns": None}),
    ]})  # fmt: skip
    write(root, "scout_intake.json", {
        "cycles": {"008": {"cycle_id": "008", "imported": "2026-11-09 08:00:00", "reported_counts": {"items": 2}}},
        "items": {
            "si-008-kontext": {"id": "si-008-kontext", "cycle_id": "008", "entity_name": "Kontext", "status": "MONITOR",
                               "website": "UNKNOWN", "key_fact": "Founded in Berlin 2026", "imported": "2026-11-09 08:00:00",
                               "evidence_urls": ["https://news.example.com/kontext"], "linked": {}},
            "si-002-evasive": {"id": "si-002-evasive", "cycle_id": "008", "entity_name": "EVASIVE Robotics",
                               "status": "APPROVED — CREATE", "website": "UNKNOWN", "key_fact": "Drone defence startup",
                               "imported": "2026-10-28 14:00:00", "evidence_urls": [],
                               "linked": {"created": [{"kind": "company", "id": "evasive-robotics"}]}},
        },
        "events": {},
    })  # fmt: skip
    write(root, "native_scout.json", {"signals": [
        {"id": "sig-theme", "key": "digital twin", "name": "digital twin", "status": "MONITORING", "candidate_ids": ["aaaaaaaaaaa1"]},
        {"id": "sig-lead", "key": "planner:mimic", "name": "mimic robotics AG", "status": "INVESTIGATE", "origin": "planner",
         "first_seen": "2026-11-01T10:00:00", "evidence": [{"source": "ethz", "url": "https://ethz.example.ch/mimic"}]},
    ], "hunts": []})  # fmt: skip
    write(root, "triage_proposals.json", {"proposals": {
        "aaaaaaaaaaa1": {"candidate_id": "aaaaaaaaaaa1", "proposal": "RESEARCH", "model": "m", "usd": 0.001,
                         "proposed_at": "2026-10-02 10:00:00"},
        "aaaaaaaaaaa2": {"candidate_id": "aaaaaaaaaaa2", "proposal": "KEEP", "model": "m", "usd": 0.001},
    }, "runs": []})  # fmt: skip
    write(root, "queue_routing.json", {"routes": {
        "aaaaaaaaaaa1": {"state": "MACHINE_WATCH", "priority": 3}, "aaaaaaaaaaa2": {"state": "NEEDS_MOHAMED", "priority": 1},
    }, "runs": []})  # fmt: skip
    write(root, "committee.json", {"chair": {}, "outside": {}, "second_pass": {}})
    write(root, "people.json", {"people": [
        {"id": "p-a", "name": "Ada", "orcid": "0000-1", "profile_urls": ["https://ada.example.com"]},
        {"id": "p-b", "name": "Bea", "orcid": "0000-1"},  # duplicate strong identifier
    ]})  # fmt: skip
    write(root, "events.json", {"events": [{"id": "ev-x", "name": "Demo day", "start": "2027-08-31"}], "leads": [1]})
    ledger = b'{"ts": "2026-10-08T10:00:00", "purpose": "shadow_triage", "usd": 0.01}\r\n{"ts": "2026-10-08T11:00:00", "purpose": "x"}\r\n'
    write(root, "inference_ledger.jsonl", None, raw=ledger)
    write(root, "schedule/jobs.json", {"watch_checks": {"state": "ok", "started": "2026-11-10T08:00:00"}})
    write(root, "schedule/runs.jsonl", None, raw=b'{"at": "2026-11-10T08:00:01", "job": "watch_checks", "ok": true}\n')
    write(
        root,
        "bridge_jobs.json",
        {"jobs": {"j1": {"job_id": "j1", "job_type": "COMPANY_RESEARCH", "status": "needs_operator"}}},
    )
    write(root, "config.json", {"home_base": "Munich", "scout_bridge": {"transport": "xai"}})
    write(root, "radar_metrics.json", {"week": 45})
    write(root, "inference_cache/ab.json", {"v": 1})
    write(root, "shadow_triage/holdout_set.xlsx", None, raw=b"PK\x03\x04\x00binary\xff")
    return root


def plan_for(root: Path) -> ImportPlan:
    return build_plan(LegacySnapshot.capture(root), now=NOW)


def rows(plan: ImportPlan, table: str, **match: Any) -> list[dict[str, Any]]:
    return [r for r in plan.tables[table] if all(r.get(k) == v for k, v in match.items())]


def resolve(plan: ImportPlan, namespace: str, alias: str) -> str:
    (row,) = rows(plan, "candidate_aliases", namespace=namespace, alias_id=alias)
    return str(row["candidate_id"])


# ── identity and merging ────────────────────────────────────────────────────────────────────────────────────────


def test_open_candidates_with_the_same_registry_id_merge_into_the_most_advanced(legacy: Path) -> None:
    plan = plan_for(legacy)
    assert resolve(plan, "candidate", "aaaaaaaaaaa1") == "aaaaaaaaaaa2"  # 'research' outranks 'new'
    assert resolve(plan, "candidate", "aaaaaaaaaaa2") == "aaaaaaaaaaa2"
    assert not rows(plan, "candidates", id="aaaaaaaaaaa1")
    (survivor,) = rows(plan, "candidates", id="aaaaaaaaaaa2")
    assert survivor["status"] == "reviewing" and survivor["legacy_status"] == "research"
    assert rows(plan, "candidate_events", candidate_id="aaaaaaaaaaa2", action="merge")
    assert any(o["payload"].get("merged_record", {}).get("id") == "aaaaaaaaaaa1" for o in rows(plan, "observations"))


def test_closed_record_of_the_same_company_stays_its_own_candidate(legacy: Path) -> None:
    plan = plan_for(legacy)
    (closed,) = rows(plan, "candidates", id="aaaaaaaaaaa3")
    (survivor,) = rows(plan, "candidates", id="aaaaaaaaaaa2")
    assert closed["status"] == "rejected" and closed["company_id"] == survivor["company_id"]


def test_proposals_and_routing_follow_the_merge(legacy: Path) -> None:
    plan = plan_for(legacy)
    proposals = rows(plan, "triage_proposals", candidate_id="aaaaaaaaaaa2")
    assert sorted((p["proposal"], p["is_current"]) for p in proposals) == [("KEEP", True), ("RESEARCH", False)]
    assert len(rows(plan, "candidate_routing", candidate_id="aaaaaaaaaaa2")) == 1


def test_placeholder_name_and_placeholder_registry_ids_create_no_shared_identity(legacy: Path) -> None:
    plan = plan_for(legacy)
    (unknown,) = rows(plan, "candidates", id="aaaaaaaaaaa4")
    assert unknown["company_id"] is None and unknown["attrs"]["identity"] == "unresolved_name"
    nulla, vacua = rows(plan, "candidates", id="aaaaaaaaaaa6")[0], rows(plan, "candidates", id="aaaaaaaaaaa7")[0]
    assert nulla["company_id"] and vacua["company_id"] and nulla["company_id"] != vacua["company_id"]
    assert not [i for i in plan.tables["company_identifiers"] if i["kind"] == "registry" and i["value"] in {"None", ""}]


# ── decision 0001: same name from two different origins merges; everything else stays a suggestion ─────────────


def test_same_name_from_two_origins_merges_into_one_candidate(legacy: Path) -> None:
    plan = plan_for(legacy)
    inbox_kontext = resolve(plan, "candidate", "aaaaaaaaaaa5")
    intake_kontext = resolve(plan, "scout_intake", "si-008-kontext")
    assert inbox_kontext == intake_kontext  # both old links open the same candidate
    (survivor,) = rows(plan, "candidates", id=intake_kontext)
    assert survivor["status"] == "watch"  # Scout Intake MONITOR outranks Deal Flow 'new'
    assert survivor["origins"] == ["legacy_dealflow", "legacy_scout00"]
    (merge,) = rows(plan, "candidate_events", candidate_id=intake_kontext, action="merge")
    assert merge["detail"]["basis"] == "same_name_cross_origin"
    assert merge["detail"]["absorbed"]["legacy_id"] == "aaaaaaaaaaa5"
    merges = plan.report["identity"]["cross_origin_name_merges"]
    assert [m["normalized_name"] for m in merges] == ["kontext"]
    assert not rows(plan, "candidate_events", candidate_id=intake_kontext, action="merge_suggested")


def test_same_name_within_one_origin_stays_a_suggestion(legacy: Path) -> None:
    inbox = json.loads((legacy / "inbox.json").read_text(encoding="utf-8"))
    inbox["candidates"] += [cand("ccccccccccc1", "Twin Labs"), cand("ccccccccccc2", "Twin Labs GmbH")]
    write(legacy, "inbox.json", inbox)
    plan = plan_for(legacy)
    a, b = resolve(plan, "candidate", "ccccccccccc1"), resolve(plan, "candidate", "ccccccccccc2")
    assert a != b
    assert rows(plan, "candidate_events", candidate_id=a, action="merge_suggested")
    assert "twin labs" not in [m["normalized_name"] for m in plan.report["identity"]["cross_origin_name_merges"]]


def test_same_name_but_different_domains_stays_a_suggestion(legacy: Path) -> None:
    write(legacy, "real_data.json", {"signals": [
        {"company": "Kontext", "website": "https://kontext-ai.example.com", "status": "new"},
    ]})  # fmt: skip
    data = json.loads((legacy / "scout_intake.json").read_text(encoding="utf-8"))
    data["items"]["si-008-kontext"]["website"] = "https://kontext-legal.example.org"
    write(legacy, "scout_intake.json", data)
    plan = plan_for(legacy)
    intake = resolve(plan, "scout_intake", "si-008-kontext")
    (row,) = rows(plan, "candidates", id=intake)
    (entry,) = plan.tables["conviction_entries"]
    assert row["company_id"] != entry["company_id"]  # two different domains = two companies sharing a name
    assert rows(plan, "candidate_events", candidate_id=intake, action="merge_suggested")


def test_ambiguous_name_is_never_auto_merged(legacy: Path) -> None:
    inbox = json.loads((legacy / "inbox.json").read_text(encoding="utf-8"))
    inbox["candidates"] = [c for c in inbox["candidates"] if c["id"] != "aaaaaaaaaaa5"]
    inbox["candidates"] += [cand("ddddddddddd1", "Kontext"), cand("ddddddddddd2", "Kontext")]
    write(legacy, "inbox.json", inbox)
    plan = plan_for(legacy)
    intake = resolve(plan, "scout_intake", "si-008-kontext")
    assert intake not in {resolve(plan, "candidate", "ddddddddddd1"), resolve(plan, "candidate", "ddddddddddd2")}
    assert rows(plan, "candidate_events", candidate_id=intake, action="merge_suggested")
    assert plan.report["identity"]["cross_origin_name_merges"] == []


def test_a_conviction_company_absorbs_a_same_name_lead_from_another_origin(legacy: Path) -> None:
    write(legacy, "real_data.json", {"signals": [
        {"company": "EVASIVE Robotics", "website": "https://evasive-robotics.example.com", "status": "new"},
        {"company": "Nulla Labs", "status": "contacted"},
    ]})  # fmt: skip
    plan = plan_for(legacy)
    nulla = next(e for e in plan.tables["conviction_entries"] if e["slug"] == "nulla-labs")
    (lead,) = rows(plan, "candidates", id="aaaaaaaaaaa6")
    assert lead["company_id"] == nulla["company_id"]


def test_intake_item_linked_to_a_conviction_company_shares_its_identity(legacy: Path) -> None:
    plan = plan_for(legacy)
    (entry,) = plan.tables["conviction_entries"]
    evasive = resolve(plan, "scout_intake", "si-002-evasive")
    (candidate,) = rows(plan, "candidates", id=evasive)
    assert candidate["company_id"] == entry["company_id"] and candidate["status"] == "kept"
    assert entry["candidate_id"] == evasive


def test_native_theme_is_not_a_candidate_but_the_planner_lead_is(legacy: Path) -> None:
    plan = plan_for(legacy)
    lead = resolve(plan, "native_scout", "sig-lead")
    assert rows(plan, "candidates", id=lead)[0]["status"] == "reviewing"
    assert not rows(plan, "candidate_aliases", namespace="native_scout", alias_id="sig-theme")
    (rest,) = rows(plan, "documents", key="native_scout.json#rest")
    assert [s["id"] for s in rest["body"]["signals"]] == ["sig-theme"]


def test_unknown_source_ids_get_a_disabled_stub(legacy: Path) -> None:
    plan = plan_for(legacy)
    (stub,) = rows(plan, "sources", id="legacy-gone")
    assert stub["enabled"] is False and stub["kind"] == "legacy_stub"


def test_duplicate_person_identifier_is_reported_not_stored(legacy: Path) -> None:
    plan = plan_for(legacy)
    assert len(rows(plan, "person_identifiers", kind="orcid")) == 1
    assert plan.report["reconciliation"]["people.json"]["duplicate_identifiers_not_stored"]


# ── completeness, determinism, safety ───────────────────────────────────────────────────────────────────────────


def test_every_legacy_record_is_accounted_for(legacy: Path) -> None:
    plan = plan_for(legacy)
    legacy_ids = {"candidate": {f"aaaaaaaaaaa{i}" for i in range(1, 8)},
                  "scout_intake": {"si-008-kontext", "si-002-evasive"}, "native_scout": {"sig-lead"}}  # fmt: skip
    for namespace, ids in legacy_ids.items():
        assert {a["alias_id"] for a in rows(plan, "candidate_aliases", namespace=namespace)} >= ids
    candidate_ids = {c["id"] for c in plan.tables["candidates"]}
    assert all(a["candidate_id"] in candidate_ids for a in plan.tables["candidate_aliases"])
    assert len(plan.tables["model_ledger"]) == 2 and len(plan.tables["job_runs"]) == 1


def test_archive_holds_every_file_byte_for_byte(legacy: Path) -> None:
    plan = plan_for(legacy)
    on_disk = {p.relative_to(legacy).as_posix(): p.read_bytes() for p in legacy.rglob("*") if p.is_file()}
    assert {f.path: f.raw for f in plan.archive} == on_disk
    ledger = next(f for f in plan.archive if f.path == "inference_ledger.jsonl")
    assert b"\r\n" in ledger.raw and isinstance(ledger.parsed, list) and len(ledger.parsed) == 2
    binary = next(f for f in plan.archive if f.path.endswith(".xlsx"))
    assert binary.parsed is None


def test_caches_are_archived_but_not_documents(legacy: Path) -> None:
    plan = plan_for(legacy)
    keys = {d["key"] for d in plan.tables["documents"]}
    assert "radar_metrics.json" in keys and "config.json" in keys
    assert not any(k.startswith("inference_cache/") for k in keys)
    assert any(f.path == "inference_cache/ab.json" for f in plan.archive)


def test_planning_never_writes_to_the_legacy_folder(legacy: Path) -> None:
    def snapshot() -> dict[str, tuple[str, int]]:
        return {
            p.as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "dir", p.stat().st_mtime_ns)
            for p in legacy.rglob("*")
        }

    before = snapshot()
    plan_for(legacy)
    assert snapshot() == before


def test_plans_are_deterministic(legacy: Path) -> None:
    a, b = plan_for(legacy), plan_for(legacy)
    assert a.tables == b.tables and fingerprint(a) == fingerprint(b)


def test_naive_legacy_times_are_read_as_berlin(legacy: Path) -> None:
    plan = plan_for(legacy)
    (survivor,) = rows(plan, "candidates", id="aaaaaaaaaaa2")
    assert survivor["first_seen_at"].isoformat() == "2026-10-01T09:00:00+02:00"  # CEST


def test_secret_looking_values_block_apply_before_any_connection(legacy: Path) -> None:
    write(legacy, "config.json", {"home_base": "Munich", "anthropic_api_key": "sk-live-123"})
    plan = plan_for(legacy)
    assert plan.secrets_found
    (config,) = rows(plan, "documents", key="config.json")
    assert config["body"]["anthropic_api_key"] == "[redacted]"
    result = apply_plan(plan, schema="pz", conn=None)  # refuses before connecting: no database needed
    assert result["applied"] is False and any("secret" in b for b in result["blockers"])


# ── review 003 #2: one captured snapshot; changes during capture are detected ───────────────────────────────────


def test_a_save_during_capture_is_detected_and_capture_retries(legacy: Path) -> None:
    def save_once(attempt: int) -> None:
        if attempt == 1:  # the old app saves between the two passes of the first attempt
            write(legacy, "inbox.json", {"candidates": [cand("aaaaaaaaaaa9", "Late Co", "watch")]})

    snapshot = LegacySnapshot.capture(legacy, between_passes=save_once)
    assert snapshot.attempts == 2
    plan = build_plan(snapshot, now=NOW)
    assert [c["id"] for c in plan.tables["candidates"] if c["origins"] == ["legacy_dealflow"]] == ["aaaaaaaaaaa9"]


def test_a_folder_that_keeps_changing_is_refused(legacy: Path) -> None:
    def save_every_time(attempt: int) -> None:
        write(legacy, "inbox.json", {"candidates": [cand(f"aaaaaaaaaa{attempt:02d}", "Busy Co")]})

    with pytest.raises(LegacySourceError, match="kept changing"):
        LegacySnapshot.capture(legacy, attempts=3, between_passes=save_every_time)


def test_rows_and_archive_come_from_the_same_bytes_even_if_the_file_changes_later(legacy: Path) -> None:
    snapshot = LegacySnapshot.capture(legacy)
    write(legacy, "inbox.json", {"candidates": [cand("aaaaaaaaaaa1", "Changed", "rejected")]})  # after capture
    plan = build_plan(snapshot, now=NOW)
    archived = json.loads(next(f for f in plan.archive if f.path == "inbox.json").raw)
    archived_status = {c["id"]: c["decision"] for c in archived["candidates"]}
    (survivor,) = rows(plan, "candidates", id="aaaaaaaaaaa2")
    assert archived_status["aaaaaaaaaaa2"] == survivor["legacy_status"] == "research"
    assert all(c["name"] != "Changed" for c in plan.tables["candidates"])


# ── review 003 #3: conflicting strong identities resolve to no company and change no owner ──────────────────────


BRIDGE_RECORDS = {
    "inbox:a": ("Alpha", [("domain", "", "alpha.com")]),
    "inbox:b": ("Beta", [("registry", "duns", "1")]),
    "inbox:c": ("Gamma", [("domain", "", "alpha.com"), ("registry", "duns", "1"), ("registry", "duns", "3")]),
}


@pytest.mark.parametrize("order", list(itertools.permutations(BRIDGE_RECORDS)))
def test_a_bridging_record_never_joins_two_owners_in_any_order(order: tuple[str, ...]) -> None:
    """Codex rev 4: A owns a domain, B a DUNS, C carries both (+ an unclaimed DUNS). Every order gives the same."""
    book = CompanyBook()
    for seed in order:
        name, keys = BRIDGE_RECORDS[seed]
        book.resolve(seed=seed, name=name, strong_keys=keys, source="t", description=f"{name} details")
    book.finalize()

    a, b, c = book.company_of("inbox:a"), book.company_of("inbox:b"), book.company_of("inbox:c")
    assert a and b and a != b and c is None
    assert book.companies[a].keys == {("domain", "", "alpha.com")}
    assert book.companies[b].keys == {("registry", "duns", "1")}
    assert all(i["value"] != "3" for i in book.identifiers)  # the bridge's own key is claimed by nobody
    assert book.companies[a].description == "Alpha details" and book.companies[b].description == "Beta details"
    (conflict,) = book.conflicts
    assert conflict["seed"] == "inbox:c" and conflict["groups"] == [["inbox:a"], ["inbox:b"]]


@pytest.mark.parametrize("order", list(itertools.permutations(["inbox:x", "inbox:y", "inbox:z"])))
def test_records_sharing_one_key_are_one_company_in_any_order(order: tuple[str, ...]) -> None:
    keys = {
        "inbox:x": [("registry", "duns", "7")],
        "inbox:y": [("registry", "duns", "7")],
        "inbox:z": [("registry", "duns", "7")],
    }
    book = CompanyBook()
    for seed in order:
        book.resolve(seed=seed, name="Seven Labs", strong_keys=keys[seed], source="t")
    book.finalize()
    assert len({book.company_of(s) for s in keys}) == 1 and not book.conflicts


def test_placeholder_named_records_join_a_named_record_with_the_same_key() -> None:
    book = CompanyBook()
    book.resolve(seed="inbox:p", name="UNKNOWN", strong_keys=[("registry", "duns", "8")], source="t")
    book.resolve(seed="inbox:q", name="Octo GmbH", strong_keys=[("registry", "duns", "8")], source="t")
    book.resolve(seed="inbox:r", name="UNKNOWN", strong_keys=[("registry", "duns", "9")], source="t")
    book.finalize()
    assert book.company_of("inbox:p") == book.company_of("inbox:q") and book.company_of("inbox:r") is None
    assert book.companies[book.company_of("inbox:q")].name == "Octo GmbH"


def test_conflicting_candidate_is_imported_unresolved_and_not_merged(legacy: Path) -> None:
    write(legacy, "real_data.json", {"signals": [
        {"company": "Beta Robotics", "website": "https://beta-robotics.example.com", "status": "new"},
    ]})  # fmt: skip
    inbox = json.loads((legacy / "inbox.json").read_text(encoding="utf-8"))
    inbox["candidates"].append(cand("bbbbbbbbbbb1", "Beta Robotics", website="x", entity_ids={"duns": "111"}))
    write(legacy, "inbox.json", inbox)
    # give the conflicting record a strong key owned by Conviction's company, too: domain via a scout intake item
    data = json.loads((legacy / "scout_intake.json").read_text(encoding="utf-8"))
    data["items"]["si-x"] = {"id": "si-x", "cycle_id": "008", "entity_name": "Beta X", "status": "NEW INTAKE",
                             "website": "https://beta-robotics.example.com",
                             "linked": {"created": [{"kind": "company", "id": "duplex-bio-llc"}]}}  # fmt: skip
    write(legacy, "scout_intake.json", data)
    write(legacy, "real_data.json", {"signals": [
        {"company": "Beta Robotics", "website": "https://beta-robotics.example.com", "status": "new"},
        {"company": "Duplex Bio LLC", "status": "new"},
    ]})  # fmt: skip
    plan = plan_for(legacy)
    conflicted = resolve(plan, "scout_intake", "si-x")
    (row,) = rows(plan, "candidates", id=conflicted)
    assert row["company_id"] is None and row["attrs"]["identity"] == "identity_conflict"
    assert rows(plan, "candidate_events", candidate_id=conflicted, action="identity_conflict")
    assert plan.report["identity"]["strong_key_conflicts"]
    assert not plan.blockers  # a conflicting candidate is reviewable; it does not block the import


# ── review 003 #4: required inventory ───────────────────────────────────────────────────────────────────────────


def test_empty_folder_is_blocked_and_never_marked_imported(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    plan = plan_for(empty)
    assert len(plan.inventory_errors) == 14 and all(e.endswith("missing") for e in plan.inventory_errors)
    result = apply_plan(plan, schema="pz", conn=None)  # refused before any connection: no marker can be written
    assert result["applied"] is False and result["blockers"]


def test_incomplete_folder_is_blocked(legacy: Path) -> None:
    (legacy / "inbox.json").unlink()
    plan = plan_for(legacy)
    assert plan.inventory_errors == ["inbox.json: missing"]
    assert any("inbox.json" in b for b in plan.blockers)


def test_malformed_required_collection_is_blocked(legacy: Path) -> None:
    write(legacy, "people.json", {"persons": []})
    plan = plan_for(legacy)
    assert any(e.startswith("people.json: expected collection 'people'") for e in plan.inventory_errors)


def test_present_but_empty_collection_is_allowed(legacy: Path) -> None:
    write(legacy, "committee.json", {"chair": {}, "outside": {}, "second_pass": {}})
    write(legacy, "bridge_jobs.json", {"jobs": {}})
    plan = plan_for(legacy)
    assert plan.inventory_errors == [] and plan.blockers == []
    assert plan.report["inventory"]["bridge_jobs.json"]["records"] == 0


def test_conviction_entry_without_a_company_blocks(legacy: Path) -> None:
    write(legacy, "real_data.json", {"signals": [{"company": "UNKNOWN", "status": "new"}]})
    plan = plan_for(legacy)
    assert any("conviction entry 'UNKNOWN' cannot be imported: no usable name" in b for b in plan.blockers)


# ── review 003 rev 3: order-independent name resolution and per-merge evidence ──────────────────────────────────


def twin_labs(legacy: Path, *, reverse: bool) -> ImportPlan:
    inbox = json.loads((legacy / "inbox.json").read_text(encoding="utf-8"))
    inbox["candidates"].append(cand("eeeeeeeeeee1", "Twin Labs"))
    write(legacy, "inbox.json", inbox)
    data = json.loads((legacy / "scout_intake.json").read_text(encoding="utf-8"))
    items = [
        {
            "id": "si-twin-a",
            "cycle_id": "008",
            "entity_name": "Twin Labs",
            "status": "NEW INTAKE",
            "website": "https://twin-a-labs.com",
        },
        {
            "id": "si-twin-b",
            "cycle_id": "008",
            "entity_name": "Twin Labs",
            "status": "NEW INTAKE",
            "website": "https://twinlabs-b.org",
        },
    ]
    for item in reversed(items) if reverse else items:
        data["items"][item["id"]] = item
    write(legacy, "scout_intake.json", data)
    return plan_for(legacy)


@pytest.mark.parametrize("reverse", [False, True])
def test_ambiguous_name_across_origins_never_merges_in_either_order(legacy: Path, reverse: bool) -> None:
    plan = twin_labs(legacy, reverse=reverse)
    deal_flow = resolve(plan, "candidate", "eeeeeeeeeee1")
    a, b = resolve(plan, "scout_intake", "si-twin-a"), resolve(plan, "scout_intake", "si-twin-b")
    companies = {rows(plan, "candidates", id=c)[0]["company_id"] for c in (deal_flow, a, b)}
    assert len({deal_flow, a, b}) == 3 and len(companies) == 3  # nobody absorbed anybody
    twin = [s for s in plan.report["identity"]["merge_suggestion_detail"] if s["normalized_name"] == "twin labs"]
    assert len(twin) == 3 and all("ambiguous" in s["reason"] for s in twin)  # every pair left for review
    assert "twin labs" not in [m["normalized_name"] for m in plan.report["identity"]["cross_origin_name_merges"]]


def test_twin_labs_result_is_identical_in_both_orders(tmp_path: Path, legacy: Path) -> None:
    import shutil

    other = tmp_path / "copy"
    shutil.copytree(legacy, other)
    forward, backward = twin_labs(legacy, reverse=False), twin_labs(other, reverse=True)
    key = lambda r: json.dumps(r, sort_keys=True, default=str)  # noqa: E731
    for table in ("candidates", "companies", "company_identifiers", "candidate_aliases"):
        assert sorted(map(key, forward.tables[table])) == sorted(map(key, backward.tables[table])), table


def test_mixed_group_records_the_evidence_of_each_absorption(legacy: Path) -> None:
    inbox = json.loads((legacy / "inbox.json").read_text(encoding="utf-8"))
    inbox["candidates"] += [
        cand("fffffffffff1", "Mixa Labs", entity_ids={"duns": "999"}, first_seen="2026-09-01 09:00:00"),
        cand("fffffffffff2", "Mixa Labs Ltd", "research", entity_ids={"duns": "999"}, first_seen="2026-10-20 09:00:00"),
    ]
    write(legacy, "inbox.json", inbox)
    data = json.loads((legacy / "scout_intake.json").read_text(encoding="utf-8"))
    data["items"]["si-mixa"] = {"id": "si-mixa", "cycle_id": "008", "entity_name": "Mixa Labs", "status": "MONITOR",
                                "website": "UNKNOWN", "imported": "2026-11-09 08:00:00"}  # fmt: skip
    write(legacy, "scout_intake.json", data)
    plan = plan_for(legacy)

    survivor = resolve(plan, "candidate", "fffffffffff2")  # later record, chosen by the status rule
    assert survivor == "fffffffffff2"
    assert resolve(plan, "candidate", "fffffffffff1") == survivor == resolve(plan, "scout_intake", "si-mixa")
    events = {
        e["detail"]["absorbed"]["legacy_id"]: e["detail"]
        for e in rows(plan, "candidate_events", candidate_id=survivor, action="merge")
    }
    assert events["fffffffffff1"]["basis"] == "strong_identifier"
    evidence = [events["fffffffffff1"]["absorbed_evidence"], events["fffffffffff1"]["survivor_evidence"]]
    assert [e["basis"] for e in evidence] == ["strong_identifier", "strong_identifier"]  # both matched on DUNS
    assert all(e["matched"] == [["registry", "duns", "999"]] for e in evidence)
    assert events["si-mixa"]["basis"] == "same_name_cross_origin"
    assert events["si-mixa"]["absorbed_evidence"]["then"] == "same_name_cross_origin"


def test_company_ids_do_not_depend_on_reading_order(tmp_path: Path, legacy: Path) -> None:
    import shutil

    other = tmp_path / "shuffled"
    shutil.copytree(legacy, other)
    inbox = json.loads((other / "inbox.json").read_text(encoding="utf-8"))
    inbox["candidates"].reverse()
    write(other, "inbox.json", inbox)
    a, b = plan_for(legacy), plan_for(other)
    key = lambda r: json.dumps(r, sort_keys=True, default=str)  # noqa: E731
    for table in ("candidates", "companies", "company_identifiers", "candidate_aliases", "conviction_entries"):
        assert sorted(map(key, a.tables[table])) == sorted(map(key, b.tables[table])), table


# ── review 010: Conviction entries as the old app keyed them ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("company", "slug"),
    [
        ("a68 GmbH", "a68"),
        ("Drawcall UG", "drawcall"),
        ("RegCheck (Softreg GmbH)", "regcheck-softreg"),
        ("Müller Größe AG", "mueller-groesse"),
        ("X" * 50, "x" * 40),
    ],
)
def test_conviction_slug_is_the_old_radar_slug(legacy: Path, company: str, slug: str) -> None:
    write(legacy, "real_data.json", {"signals": [{"company": company, "status": "new"}]})
    (entry,) = plan_for(legacy).tables["conviction_entries"]
    assert entry["slug"] == slug


def test_two_entries_with_one_old_slug_block_the_import(legacy: Path) -> None:
    write(legacy, "real_data.json", {"signals": [{"company": "Acme GmbH", "status": "new"},
                                                 {"company": "Acme AG", "status": "new"}]})  # fmt: skip
    plan = plan_for(legacy)
    assert any("share the slug 'acme'" in b for b in plan.blockers)


@pytest.mark.parametrize(
    ("verified", "flags"),
    [
        (
            {"founders": True, "traction": False, "funding": False},
            {"founders": True, "traction": False, "funding": False},
        ),
        (
            {"founders": False, "traction": False, "funding": False},
            {"founders": False, "traction": False, "funding": False},
        ),
        (False, {}),
        (None, {}),
        ({"founders": "yes"}, {}),
    ],
)
def test_conviction_verified_keeps_the_per_claim_record(legacy: Path, verified: Any, flags: dict[str, bool]) -> None:
    write(legacy, "real_data.json", {"signals": [{"company": "Flagged Co", "status": "new", "verified": verified}]})
    (entry,) = plan_for(legacy).tables["conviction_entries"]
    assert entry["verified"] == flags  # never collapsed to one boolean, never "all verified" from a non-empty record


def test_a_kept_entry_links_to_the_lead_it_came_from_through_merges(legacy: Path) -> None:
    # aaaaaaaaaaa1 is merged into aaaaaaaaaaa2 by the shared DUNS: the entry must point at the survivor
    write(
        legacy, "real_data.json", {"signals": [{"company": "Duplex Bio", "status": "new", "inbox_id": "aaaaaaaaaaa1"}]}
    )
    plan = plan_for(legacy)
    (entry,) = plan.tables["conviction_entries"]
    assert entry["candidate_id"] == resolve(plan, "candidate", "aaaaaaaaaaa1") == "aaaaaaaaaaa2"


# ── review 012: people as the old app keyed them ────────────────────────────────────────────────────────────────


def people_plan(legacy: Path, *people: Any) -> ImportPlan:
    write(legacy, "people.json", {"people": list(people)})
    return plan_for(legacy)


def identifiers(plan: ImportPlan, person_id: str) -> list[tuple[str, str]]:
    return [(i["kind"], i["value"]) for i in rows(plan, "person_identifiers", person_id=person_id)]


def test_a_person_without_an_id_is_skipped_and_reported(legacy: Path) -> None:
    plan = people_plan(legacy, {"name": "No Id"}, {"id": "", "name": "Empty Id"}, "not a record",
                       {"id": "p-a", "name": "Ada"})  # fmt: skip
    assert [p["id"] for p in plan.tables["people"]] == ["p-a"]
    report = plan.report["reconciliation"]["people.json"]
    assert report["in"] == 4 and report["rows"] == 1
    assert report["skipped_without_id"] == [
        {"position": 0, "name": "No Id", "why": "no id"},
        {"position": 1, "name": "Empty Id", "why": "no id"},
        {"position": 2, "name": None, "why": "not a record"},
    ]
    assert not plan.blockers  # the old app skipped them too


def test_two_people_with_one_id_block_the_import(legacy: Path) -> None:
    plan = people_plan(legacy, {"id": "p-a", "name": "Ada Lovelace"}, {"id": "p-a", "name": "Ada King"})
    assert any("'Ada Lovelace' and 'Ada King' share the id 'p-a'" in b for b in plan.blockers)
    assert len(rows(plan, "people", id="p-a")) == 1  # never two rows for one primary key
    result = apply_plan(plan, schema="pz", conn=None)  # refused before any connection
    assert result["applied"] is False and any("share the id" in b for b in result["blockers"])


def test_created_at_is_the_old_created_day_else_the_import_time(legacy: Path) -> None:
    plan = people_plan(legacy, {"id": "p-a", "name": "A", "created": "2026-09-12"}, {"id": "p-b", "name": "B"},
                       {"id": "p-c", "name": "C", "created": "last week"}, {"id": "p-d", "name": "D", "created": 7})  # fmt: skip
    by_id = {p["id"]: p["created_at"] for p in plan.tables["people"]}
    assert by_id["p-a"].isoformat() == "2026-09-12T00:00:00+02:00"  # midnight Europe/Berlin, like other legacy days
    assert by_id["p-b"] == by_id["p-c"] == by_id["p-d"] == NOW
    assert plan.report["reconciliation"]["people.json"]["created_at_from_import_time"] == 3


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("Prof. Dr. Jürgen Groß", "jurgen gross"),
        ("Dr.-Ing. Anna Weiß", "anna weiss"),
        ("Dipl.-Ing. Lena Müller-Lüdenscheidt", "lena muller ludenscheidt"),
        ("JÜRGEN GROẞ", "jurgen gross"),
        ("Zoë O'Brien", "zoe o brien"),
        ("李小龙", None),  # no ASCII letters: no key rather than an empty one
    ],
)
def test_normalized_name_is_the_old_person_key(legacy: Path, name: str, key: str | None) -> None:
    (person,) = people_plan(legacy, {"id": "p-x", "name": name}).tables["people"]
    assert person["name"] == name and person["normalized_name"] == key


def test_a_profile_is_strong_and_any_other_link_is_weak(legacy: Path) -> None:
    plan = people_plan(legacy, {"id": "p-a", "name": "Ada", "github_id": "1", "aliases": ["AdaL"],
                                "profile_urls": ["https://github.com/AdaL", "https://acme-robotics.example.com/"]},
                       {"id": "p-b", "name": "Bea", "github_id": "2",
                        "profile_urls": ["https://github.com/bea", "http://www.Acme-Robotics.example.com"]})  # fmt: skip
    assert identifiers(plan, "p-a") == [("github", "1"), ("profile_url", "https://github.com/adal"),
                                        ("url", "https://acme-robotics.example.com"), ("alias", "AdaL")]  # fmt: skip
    assert identifiers(plan, "p-b")[-1] == ("url", "https://acme-robotics.example.com")  # a shared company site
    assert plan.report["reconciliation"]["people.json"]["duplicate_identifiers_not_stored"] == []


def test_profile_variants_are_one_identifier_across_people(legacy: Path) -> None:
    plan = people_plan(legacy, {"id": "p-a", "name": "Ada", "orcid": "0000-0002-1825-0097",
                                "profile_urls": ["https://www.linkedin.com/in/Ada-L/"]},
                       {"id": "p-b", "name": "Bea", "orcid": "https://orcid.org/0000-0002-1825-0097",
                        "profile_urls": ["de.linkedin.com/in/ada-l?trk=x"]})  # fmt: skip
    assert identifiers(plan, "p-a") == [("orcid", "https://orcid.org/0000-0002-1825-0097"),
                                        ("profile_url", "https://www.linkedin.com/in/ada-l")]  # fmt: skip
    assert identifiers(plan, "p-b") == []
    dups = plan.report["reconciliation"]["people.json"]["duplicate_identifiers_not_stored"]
    assert [(d["kind"], d["people"]) for d in dups] == [("orcid", ["p-a", "p-b"]), ("profile_url", ["p-a", "p-b"])]


def test_a_repeat_within_one_person_is_one_row_and_not_a_duplicate(legacy: Path) -> None:
    plan = people_plan(legacy, {"id": "p-a", "name": "Ada", "openalex_id": "https://openalex.org/A123",
                                "profile_urls": ["https://openalex.org/A123", "https://openalex.org/a123/",
                                                 "https://ada.example.com", "https://ada.example.com/"]})  # fmt: skip
    assert identifiers(plan, "p-a") == [("openalex", "https://openalex.org/A123"),
                                        ("profile_url", "https://openalex.org/A123"),
                                        ("url", "https://ada.example.com")]  # fmt: skip
    report = plan.report["reconciliation"]["people.json"]
    assert report["duplicate_identifiers_not_stored"] == [] and report["repeated_within_one_person"] == 2


def test_aliases_are_weak_identifiers_deduplicated_per_person(legacy: Path) -> None:
    plan = people_plan(legacy, {"id": "p-a", "name": "Ada", "aliases": ["adal", "AdaL", " adal ", "", "unknown"]},
                       {"id": "p-b", "name": "Bea", "aliases": ["adal"]})  # fmt: skip
    assert identifiers(plan, "p-a") == [("alias", "adal")]
    assert identifiers(plan, "p-b") == [("alias", "adal")]  # weak: two people may share an alias
    assert plan.report["reconciliation"]["people.json"]["duplicate_identifiers_not_stored"] == []


def test_a_non_text_promoted_field_is_kept_in_attrs(legacy: Path) -> None:
    plan = people_plan(legacy, {"id": "p-a", "name": "Ada", "country": {"code": "DE"}, "identity_status": ["x"]},
                       {"id": "p-b", "name": "Bea", "country": "DE", "region": "BY"})  # fmt: skip
    a, b = rows(plan, "people", id="p-a")[0], rows(plan, "people", id="p-b")[0]
    assert a["country"] is None and a["attrs"]["country"] == {"code": "DE"}
    assert a["identity_status"] is None and a["attrs"]["identity_status"] == ["x"]
    assert b["country"] == "DE" and b["attrs"] == {"region": "BY"}  # a text value lives in its column only
    assert a["legacy"]["country"] == {"code": "DE"}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.linkedin.com/in/Jane-Roe-123/", ("profile_url", "https://www.linkedin.com/in/jane-roe-123")),
        ("linkedin.com/in/jane-roe-123?trk=public", ("profile_url", "https://www.linkedin.com/in/jane-roe-123")),
        ("https://www.linkedin.com/company/acme", ("url", "https://linkedin.com/company/acme")),
        ("https://GitHub.com/JaneRoe", ("url", "https://github.com/JaneRoe")),  # not established as this person's
        ("https://github.com/janeroe/robot-arm", ("url", "https://github.com/janeroe/robot-arm")),
        ("https://github.com/orgs", ("url", "https://github.com/orgs")),
        ("https://orcid.org/0000-0002-1825-009x", ("profile_url", "https://orcid.org/0000-0002-1825-009X")),
        ("0000-0002-1825-0097", ("profile_url", "https://orcid.org/0000-0002-1825-0097")),
        ("https://openalex.org/A5023888391", ("profile_url", "https://openalex.org/A5023888391")),
        ("https://api.openalex.org/authors/a5023888391", ("profile_url", "https://openalex.org/A5023888391")),
        ("https://openalex.org/W2741809807", ("url", "https://openalex.org/W2741809807")),  # a work, not a person
        ("https://scholar.google.de/citations?user=AbC123&hl=de",
         ("profile_url", "https://scholar.google.com/citations?user=AbC123")),
        ("https://twitter.com/JaneRoe", ("url", "https://twitter.com/JaneRoe")),
        ("https://scholar.google.example/citations?user=AbC123",
         ("url", "https://scholar.google.example/citations?user=AbC123")),  # unknown Scholar host
        ("https://x.com/home", ("url", "https://x.com/home")),
        ("https://x.com/janeroe/status/1", ("url", "https://x.com/janeroe/status/1")),
        ("http://www.Acme-Robotics.example.com/", ("url", "https://acme-robotics.example.com")),
        ("https://www.youtube.com/@JaneRoe", ("url", "https://youtube.com/@JaneRoe")),
        ("acme.example.com/About#team", ("url", "https://acme.example.com/About")),
        ("not a url", ("url", "not a url")),
        ("   ", None),
    ],
)  # fmt: skip
def test_profile_url_rules(url: str, expected: tuple[str, str] | None) -> None:
    assert classify_profile_url(url) == expected


@pytest.mark.parametrize(
    ("value", "orcid", "openalex"),
    [
        ("0000-0002-1825-009x", "https://orcid.org/0000-0002-1825-009X", "0000-0002-1825-009x"),
        ("http://www.ORCID.org/0000-0002-1825-009X/", "https://orcid.org/0000-0002-1825-009X",
         "http://www.ORCID.org/0000-0002-1825-009X/"),
        ("a5023888391", "a5023888391", "https://openalex.org/A5023888391"),
        ("https://api.openalex.org/authors/A5023888391/", "https://api.openalex.org/authors/A5023888391/",
         "https://openalex.org/A5023888391"),
        (" 0000-1 ", "0000-1", "0000-1"),  # not an iD: kept as written (stripped)
    ],
)  # fmt: skip
def test_orcid_and_openalex_ids_have_one_spelling(value: str, orcid: str, openalex: str) -> None:
    assert (canonical_orcid(value), canonical_openalex(value)) == (orcid, openalex)


# ── review 012, Codex H-078 ─────────────────────────────────────────────────────────────────────────────────────
def test_an_account_is_strong_only_when_the_record_establishes_it(legacy: Path) -> None:
    from projectzero.network.identity import classify_profile_url, own_accounts

    mine = own_accounts({"github_id": "42", "aliases": ["JaneRoe"], "x": "@jroe"})
    assert classify_profile_url("https://github.com/janeroe", mine) == ("profile_url", "https://github.com/janeroe")
    assert classify_profile_url("https://x.com/JRoe", mine) == ("profile_url", "https://x.com/jroe")
    assert own_accounts({"aliases": ["JaneRoe"]}) == frozenset()  # an alias without the collector's account id


def test_two_people_listing_one_organisation_stay_weak_and_never_collide(legacy: Path) -> None:
    plan = people_plan(legacy, {"id": "p-a", "name": "Ada", "profile_urls": ["https://github.com/acme-robotics"]},
                       {"id": "p-b", "name": "Bea", "profile_urls": ["https://github.com/Acme-Robotics/"]},
                       {"id": "p-c", "name": "Cy", "github_id": "7", "aliases": ["cy-dev"],
                        "profile_urls": ["https://github.com/cy-dev"]})  # fmt: skip
    assert identifiers(plan, "p-a") == [("url", "https://github.com/acme-robotics")]
    assert identifiers(plan, "p-b") == [("url", "https://github.com/Acme-Robotics")]
    assert identifiers(plan, "p-c") == [
        ("github", "7"),
        ("profile_url", "https://github.com/cy-dev"),
        ("alias", "cy-dev"),
    ]  # confirmed as this person's own account
    assert plan.report["reconciliation"]["people.json"]["duplicate_identifiers_not_stored"] == []


def test_record_is_reserved_for_application_writes(legacy: Path) -> None:
    from projectzero.network.people import record_of

    plan = people_plan(legacy, {"id": "p-n", "name": "Nested", "record": {"name": "not the person", "x": 1}})
    (row,) = [r for r in plan.tables["people"] if r["id"] == "p-n"]
    assert "record" not in row["attrs"] and row["legacy"]["record"] == {"name": "not the person", "x": 1}
    imported = record_of(row)
    assert imported["id"] == "p-n" and imported["name"] == "Nested"  # the imported person, not the nested field
    written = {**row, "attrs": {**row["attrs"], "record": {"id": "p-n", "name": "Nested (edited)"}}}
    assert record_of(written)["name"] == "Nested (edited)"  # a later application write takes precedence


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (
            {"github_id": "42", "aliases": [1, None, {"a": 1}, "JaneRoe"]},
            {("github", "janeroe")},
        ),  # non-strings skipped
        ({"github_id": "42", "aliases": "Alice"}, {("github", "alice")}),  # one string is ONE alias, not 5 letters
        ({"github_id": "unknown", "aliases": ["JaneRoe"]}, set()),  # the source id must be numeric
        ({"github_id": "", "aliases": ["JaneRoe"]}, set()),
        ({"github_id": 42, "aliases": ["JaneRoe"]}, {("github", "janeroe")}),
        ({"github_id": True, "aliases": ["JaneRoe"]}, set()),
        ({"github_id": "42", "aliases": 7}, set()),
        ({"x": "https://example.org/team/acme"}, set()),  # an unrelated URL authorises nothing
        ({"x": "https://x.com/acme/status/1"}, set()),
        ({"x": "https://x.com/home"}, set()),
        ({"x": "https://twitter.com/JRoe"}, {("x", "jroe")}),
        ({"x": "x.com/JRoe"}, {("x", "jroe")}),
        ({"x": "@JRoe"}, {("x", "jroe")}),  # valid bare handles keep working
        ({"x": "JRoe"}, {("x", "jroe")}),
        ({"x": 123}, set()),
    ],
)
def test_ownership_evidence_is_validated(record: dict[str, Any], expected: set[tuple[str, str]]) -> None:
    from projectzero.network.identity import own_accounts

    assert own_accounts(record) == frozenset(expected)


def test_malformed_ownership_inputs_never_stop_the_plan(legacy: Path) -> None:
    plan = people_plan(legacy, {"id": "p-a", "name": "Ada", "github_id": "42", "aliases": [1, "AdaL"],
                                "x": "https://example.org/team/acme",
                                "profile_urls": ["https://github.com/AdaL", "https://x.com/acme"]},
                       {"id": "p-b", "name": "Bea", "github_id": "unknown", "aliases": "Bea",
                        "profile_urls": ["https://github.com/bea"]})  # fmt: skip
    a = identifiers(plan, "p-a")
    assert ("profile_url", "https://github.com/adal") in a  # numeric id + whole-string alias: established
    assert ("url", "https://x.com/acme") in a and ("profile_url", "https://x.com/acme") not in a
    assert ("url", "https://github.com/bea") in identifiers(plan, "p-b")  # "unknown" id establishes nothing
    assert plan.blockers == []


@pytest.mark.parametrize(
    ("github_id", "stored"),
    [(42, "42"), ("42", "42"), (" 042 ", "42"), ("not-a-number", None), ("", None), (0, None), (True, None),
     ("４２", None), (None, None)],
)  # fmt: skip
def test_the_stored_github_id_uses_the_ownership_validator(legacy: Path, github_id: Any, stored: str | None) -> None:
    plan = people_plan(legacy, {"id": "p-g", "name": "Gil", "github_id": github_id, "aliases": ["gil-dev"],
                                "profile_urls": ["https://github.com/gil-dev"]})  # fmt: skip
    rows = identifiers(plan, "p-g")
    assert [v for k, v in rows if k == "github"] == ([stored] if stored else [])
    # the account URL is strong exactly when the same id is valid
    assert (("profile_url", "https://github.com/gil-dev") in rows) is (stored is not None)


# ── review 014: events and leads as the old app read them ───────────────────────────────────────────────────────


def events_plan(legacy: Path, events: Any, leads: Any = ()) -> ImportPlan:
    write(legacy, "events.json", {"events": events, "leads": list(leads)})
    return plan_for(legacy)


def event(plan: ImportPlan, eid: str) -> dict[str, Any]:
    (row,) = rows(plan, "events", id=eid)
    return row


def test_an_event_or_lead_without_an_id_is_skipped_and_reported(legacy: Path) -> None:
    plan = events_plan(legacy, [{"name": "No Id"}, {"id": "", "name": "Empty Id"}, "not a record",
                                {"id": "ev-a", "name": "Demo day"}],
                       [{"title": "Lead without id"}, 7, {"id": "evlead-1", "title": "Robotics meetup", "decision": "new"}])  # fmt: skip
    assert [e["id"] for e in plan.tables["events"]] == ["ev-a"]
    assert [lead["id"] for lead in plan.tables["event_leads"]] == ["evlead-1"]
    report = plan.report["reconciliation"]
    assert report["events.json"]["skipped_without_id"] == [
        {"position": 0, "name": "No Id", "why": "no id"},
        {"position": 1, "name": "Empty Id", "why": "no id"},
        {"position": 2, "name": None, "why": "not a record"},
    ]
    assert report["events.json leads"]["skipped_without_id"] == [
        {"position": 0, "title": "Lead without id", "why": "no id"},
        {"position": 1, "title": None, "why": "not a record"},
    ]
    assert report["events.json"]["in"] == 4 and report["events.json leads"]["in"] == 3
    assert not plan.blockers


def test_a_repeated_event_or_lead_id_blocks_the_import(legacy: Path) -> None:
    plan = events_plan(legacy, [{"id": "ev-a", "name": "Demo day"}, {"id": "ev-a", "name": "Demo night"}],
                       [{"id": "evlead-1", "title": "Meetup", "decision": "new"},
                        {"id": "evlead-1", "title": "Hackathon", "decision": "new"}])  # fmt: skip
    assert any("'Demo day' and 'Demo night' share the id 'ev-a'" in b for b in plan.blockers)
    assert any("'Meetup' and 'Hackathon' share the id 'evlead-1'" in b for b in plan.blockers)
    assert len(rows(plan, "events", id="ev-a")) == 1 and len(rows(plan, "event_leads", id="evlead-1")) == 1
    result = apply_plan(plan, schema="pz", conn=None)  # refused before any connection
    assert result["applied"] is False and any("share the id 'ev-a'" in b for b in result["blockers"])


@pytest.mark.parametrize(
    ("start", "end", "columns", "span"),
    [
        ("2026-09-20", None, ("2026-09-20", None, None, None), ("2026-09-20T00:00:00+02:00", "2026-09-21T00:00:00+02:00")),
        ("2026-09-20", "2026-09-22", ("2026-09-20", None, "2026-09-22", None), ("2026-09-20T00:00:00+02:00", "2026-09-23T00:00:00+02:00")),
        ("2026-09-20T18:30:45", "2026-09-20T21:00", ("2026-09-20", "18:30", "2026-09-20", "21:00"), ("2026-09-20T18:30:00+02:00", "2026-09-20T21:00:00+02:00")),
        ("2026-09-20T18:30", "", ("2026-09-20", "18:30", None, None), ("2026-09-20T18:30:00+02:00", "2026-09-21T00:00:00+02:00")),
        ("2026-09-19T23:30Z", None, ("2026-09-20", "01:30", None, None), ("2026-09-20T01:30:00+02:00", "2026-09-21T00:00:00+02:00")),
        ("20.09.2026 18:30", "21.09.2026", ("2026-09-20", "18:30", "2026-09-21", None), ("2026-09-20T18:30:00+02:00", "2026-09-22T00:00:00+02:00")),
        ("2026-09-20", "2026-09-18", ("2026-09-20", None, "2026-09-18", None), ("2026-09-20T00:00:00+02:00", "2026-09-21T00:00:00+02:00")),
        ("TBA", "2026-09-22", (None, None, "2026-09-22", None), (None, None)),
        ("2026-09-20", "2026-09-20T24:00", ("2026-09-20", None, None, None), ("2026-09-20T00:00:00+02:00", "2026-09-21T00:00:00+02:00")),
    ],
)  # fmt: skip
def test_event_dates_are_the_old_parse_when_and_event_span(
    legacy: Path, start: Any, end: Any, columns: tuple[Any, ...], span: tuple[str | None, str | None]
) -> None:
    e = {"id": "ev-a", "name": "Demo day", "start": start} | ({} if end is None else {"end": end})
    row = event(events_plan(legacy, [e]), "ev-a")
    stated = (row["start_date"], row["start_time"], row["end_date"], row["end_time"])
    assert tuple(v.isoformat() if hasattr(v, "isoformat") else v for v in stated) == columns
    assert (row["starts_at"] and row["starts_at"].isoformat(), row["ends_at"] and row["ends_at"].isoformat()) == span


def test_event_dates_are_counted_and_an_unparseable_value_stays_in_attrs(legacy: Path) -> None:
    plan = events_plan(legacy, [
        {"id": "ev-a", "name": "A", "start": "2026-09-20", "end": "2026-09-21"},
        {"id": "ev-b", "name": "B", "start": "2026-09-20T18:00", "end": "2026-09-20T22:00"},
        {"id": "ev-c", "name": "C", "start": "TBA", "end": ""},
        {"id": "ev-d", "name": "D", "start": 20260920},
        {"id": "ev-e", "name": "E", "start": "2026-09-20T25:00", "end": "2026-09-19"},
        {"id": "ev-f", "name": "F", "start": "Sept 20"},
    ])  # fmt: skip
    report = plan.report["reconciliation"]["events.json"]
    assert report["dates"] == {
        "start": {"date_only": 2, "timed": 1, "unparseable": 3, "absent": 0, "free_text": 1},
        "end": {"date_only": 2, "timed": 1, "unparseable": 0, "absent": 3, "free_text": 0},
    }
    assert report["unparseable"] == {"start: invalid time": 1, "start: no date": 1, "start: not text": 1}
    assert report["dates_clock"] == "2026-11-10"
    assert event(plan, "ev-c")["attrs"]["start"] == "TBA" and event(plan, "ev-d")["attrs"]["start"] == 20260920
    assert "start" not in event(plan, "ev-a")["attrs"] and "end" not in event(plan, "ev-c")["attrs"]  # blank: nothing
    # a month without a year is dated by the import clock (Berlin 2026-11-10): September has passed -> 2027
    assert event(plan, "ev-f")["start_date"].isoformat() == "2027-09-20"
    assert event(plan, "ev-e")["start_date"] is None and event(plan, "ev-e")["starts_at"] is None
    assert event(plan, "ev-e")["end_date"].isoformat() == "2026-09-19"  # the end as stated, even with no start


def test_24_00_is_unparseable_and_its_raw_value_stays_in_attrs(legacy: Path) -> None:
    plan = events_plan(legacy, [{"id": "ev-a", "name": "A", "start": "2026-09-20T24:00", "end": "2026-09-20T24:00"}])
    row, report = event(plan, "ev-a"), plan.report["reconciliation"]["events.json"]
    assert (row["start_date"], row["starts_at"], row["end_date"]) == (None, None, None)
    assert row["attrs"]["start"] == row["attrs"]["end"] == "2026-09-20T24:00"
    assert report["unparseable"] == {"end: invalid time": 1, "start: invalid time": 1} and not plan.blockers


def test_an_end_before_the_start_is_kept_as_stated_and_counted(legacy: Path) -> None:
    plan = events_plan(legacy, [{"id": "ev-a", "name": "A", "start": "2026-09-20", "end": "2026-09-18"}])
    assert plan.report["reconciliation"]["events.json"]["end_before_start"] == 1
    assert event(plan, "ev-a")["ends_at"].isoformat() == "2026-09-21T00:00:00+02:00"  # old event_when: end = start


def test_event_created_at_is_created_then_retrieved_at_then_the_import_time(legacy: Path) -> None:
    plan = events_plan(legacy, [
        {"id": "ev-a", "name": "A", "created": "2026-09-12", "retrieved_at": "2026-09-01T10:00:00"},
        {"id": "ev-b", "name": "B"},
        {"id": "ev-c", "name": "C", "created": "soon"},
        {"id": "ev-d", "name": "D", "retrieved_at": "2026-09-01T10:00:00"},
        {"id": "ev-e", "name": "E", "created": "", "retrieved_at": "2026-09-01 10:00:00Z"},
        {"id": "ev-f", "name": "F", "retrieved_at": "yesterday"},
    ])  # fmt: skip
    assert event(plan, "ev-a")["created_at"].isoformat() == "2026-09-12T00:00:00+02:00"
    assert event(plan, "ev-d")["created_at"].isoformat() == "2026-09-01T10:00:00+02:00"  # naive: Berlin
    assert event(plan, "ev-e")["created_at"].isoformat() == "2026-09-01T10:00:00+00:00"
    assert (
        event(plan, "ev-b")["created_at"]
        == event(plan, "ev-c")["created_at"]
        == event(plan, "ev-f")["created_at"]
        == NOW
    )
    assert plan.report["reconciliation"]["events.json"]["created_at_from"] == {
        "created": 1, "retrieved_at": 2, "import_time": 3}  # fmt: skip


@pytest.mark.parametrize(
    ("start", "end", "why"),
    [
        ("2026-03-29T02:45", "2026-03-29T03:15", "does not run forward in UTC"),  # 01:45 UTC -> 01:15 UTC
        ("9999-12-31", None, "falls after 9999-12-31"),
        ("9999-12-31T10:00", "", "falls after 9999-12-31"),
    ],
)
def test_a_span_that_overflows_or_runs_backwards_in_utc_blocks_the_import(
    legacy: Path, start: str, end: str | None, why: str
) -> None:
    bad = {"id": "ev-bad", "name": "Night run", "start": start} | ({} if end is None else {"end": end})
    plan = events_plan(legacy, [bad, {"id": "ev-ok", "name": "OK", "start": "2026-09-20"}])  # the planner finishes
    (blocker,) = [b for b in plan.blockers if "'ev-bad'" in b]
    assert "'Night run'" in blocker and repr(start) in blocker and repr(end) in blocker and why in blocker
    assert rows(plan, "events", id="ev-bad") == [] and len(rows(plan, "events", id="ev-ok")) == 1
    report = plan.report["reconciliation"]["events.json"]
    assert report["span_blocked"] == ["ev-bad"] and report["duplicate_ids_blocked"] == 0
    result = apply_plan(plan, schema="pz", conn=None)  # refused before any connection
    assert result["applied"] is False and any("'ev-bad'" in b for b in result["blockers"])


def test_the_autumn_repeated_hour_and_an_ordinary_span_are_not_blocked(legacy: Path) -> None:
    plan = events_plan(legacy, [
        {"id": "ev-a", "name": "A", "start": "2026-10-25T02:30", "end": "2026-10-25T02:45"},
        {"id": "ev-b", "name": "B", "start": "2026-03-29T01:30", "end": "2026-03-29T03:30"},
    ])  # fmt: skip
    assert not plan.blockers
    b = event(plan, "ev-b")
    assert (b["starts_at"].isoformat(), b["ends_at"].isoformat()) == (
        "2026-03-29T01:30:00+01:00",
        "2026-03-29T03:30:00+02:00",
    )


def test_blank_text_is_null_and_unknown_statuses_are_kept(legacy: Path) -> None:
    plan = events_plan(legacy, [
        {"id": "ev-a", "name": "A", "city": "", "country": " ", "url": "", "status": ""},
        {"id": "ev-b", "name": "B", "city": "UNKNOWN", "country": "DE", "url": " https://b.example.com ", "status": "skipped"},
        {"id": "ev-c", "name": "", "city": 7, "status": "MAYBE"},
        {"id": "ev-d", "name": "D", "status": "new"},
    ])  # fmt: skip
    a, b, c = event(plan, "ev-a"), event(plan, "ev-b"), event(plan, "ev-c")
    assert (a["city"], a["country"], a["url"], a["status"]) == (None, None, None, None)
    assert (b["city"], b["country"], b["url"], b["status"]) == (None, "DE", "https://b.example.com", "skipped")
    assert c["name"] == "ev-c" and c["city"] is None and c["attrs"]["city"] == 7  # not text: kept in attrs
    assert c["status"] == "MAYBE"  # no CHECK: an unknown status is kept
    report = plan.report["reconciliation"]["events.json"]
    assert report["status"] == {"(none)": 1, "MAYBE": 1, "new": 1, "skipped": 1}
    assert report["name_from_id"] == 1


@pytest.mark.parametrize(
    ("lat", "lng", "kept", "note"),
    [
        (49.0069, 8.4037, (49.0069, 8.4037), "kept"),
        (49, -180, (49.0, -180.0), "kept"),
        ("49.5", " 8.25 ", (49.5, 8.25), "kept_from_text"),
        (True, False, (None, None), "dropped"),
        (90.5, 181, (None, None), "dropped"),
        ("NaN", "1e400", (None, None), "dropped"),
        ("49,5", "8_4", (None, None), "dropped"),
        ([49], {"v": 8}, (None, None), "dropped"),
        (None, "", (None, None), "absent"),
    ],
)  # fmt: skip
def test_coordinates_are_finite_numbers_in_range(
    legacy: Path, lat: Any, lng: Any, kept: tuple[float | None, float | None], note: str
) -> None:
    plan = events_plan(legacy, [{"id": "ev-a", "name": "A", "lat": lat, "lng": lng}])
    row = event(plan, "ev-a")
    assert (row["lat"], row["lng"]) == kept
    assert all(not isinstance(v, bool) for v in (row["lat"], row["lng"]))
    coords = plan.report["reconciliation"]["events.json"]["coordinates"]
    assert coords["lat"][note] == 1 and coords["lng"][note] == 1
    if note == "dropped":
        assert row["attrs"]["lat"] == lat and row["attrs"]["lng"] == lng  # kept in attrs (and legacy)
    else:
        assert "lat" not in row["attrs"] and "lng" not in row["attrs"]


def test_an_imported_record_field_never_becomes_the_application_record(legacy: Path) -> None:
    plan = events_plan(legacy, [{"id": "ev-a", "name": "A", "record": {"id": "ev-x", "name": "X"}, "venue": "Hall"}],
                       [{"id": "evlead-1", "title": "T", "decision": "new", "record": {"title": "X"}}])  # fmt: skip
    row, (lead,) = event(plan, "ev-a"), plan.tables["event_leads"]
    assert "record" not in row["attrs"] and row["attrs"]["venue"] == "Hall"
    assert row["legacy"]["record"] == {"id": "ev-x", "name": "X"}  # still in legacy
    assert "record" not in lead["attrs"] and lead["legacy"]["record"] == {"title": "X"}


def test_leads_become_rows_with_their_parsed_date(legacy: Path) -> None:
    plan = events_plan(legacy, [], [
        {"id": "evlead-1", "title": "Robotics meetup", "source": "Luma", "url": "https://luma.example.com/r",
         "city": "Munich", "type": "founder_meetup", "date": "2026-12-03", "confidence": "low",
         "detected_on": "2026-11-01", "decision": "new", "note": "", "source_id": "luma-muc", "provenance": "ics"},
        {"id": "evlead-2", "title": "Demo night", "date": "", "detected_on": "", "decision": "dismissed"},
        {"id": "evlead-3", "title": "Hack weekend", "date": "Sept 20", "detected_on": "2026-02-30", "decision": "converted"},
    ])  # fmt: skip
    one, two, three = (rows(plan, "event_leads", id=f"evlead-{i}")[0] for i in (1, 2, 3))
    assert one["lead_date"].isoformat() == "2026-12-03" and one["date_raw"] == "2026-12-03"
    assert (one["title"], one["source"], one["city"], one["type"], one["confidence"]) == (
        "Robotics meetup", "Luma", "Munich", "founder_meetup", "low")  # fmt: skip
    assert one["note"] is None and one["attrs"] == {"source_id": "luma-muc", "provenance": "ics"}
    assert one["detected_on"].isoformat() == "2026-11-01"
    assert one["created_at"].isoformat() == "2026-11-01T00:00:00+01:00"
    assert two["lead_date"] is None and two["date_raw"] is None and two["created_at"] == NOW
    assert three["lead_date"].isoformat() == "2027-09-20" and three["date_raw"] == "Sept 20"
    assert three["detected_on"] is None and three["attrs"]["detected_on"] == "2026-02-30"  # invalid day: attrs
    report = plan.report["reconciliation"]["events.json leads"]
    assert (report["in"], report["rows"], report["open"]) == (3, 3, 1)
    assert report["decisions"] == {"converted": 1, "dismissed": 1, "new": 1}
    assert report["dates"] == {"date_only": 2, "timed": 0, "unparseable": 0, "absent": 1, "free_text": 1}
    assert report["created_at_from_import_time"] == 2
    assert not any(d["key"] == "events.json#rest" for d in plan.tables["documents"])  # nothing left un-modelled


@pytest.mark.parametrize("decision", ["maybe", None, ""])
def test_a_lead_with_an_unknown_decision_blocks_the_import(legacy: Path, decision: Any) -> None:
    lead = {"id": "evlead-1", "title": "T"} | ({} if decision is None else {"decision": decision})
    plan = events_plan(legacy, [], [lead])
    assert any("lead 'evlead-1' has the decision" in b for b in plan.blockers)
    assert plan.tables["event_leads"] == []


def test_scout_event_reports_drop_the_merge_suffix_in_documents_only(legacy: Path) -> None:
    intake = json.loads((legacy / "scout_intake.json").read_text(encoding="utf-8"))
    intake["events"] = {
        "se-1": {"id": "se-1", "event_name": "Demo day", "event_id": "ev-demo-day-2026-09-20|merged:Demo Day 2026"},
        "se-2": {"id": "se-2", "event_name": "Meetup", "event_id": "ev-meetup-2026-10-01"},
        "se-3": {"id": "se-3", "event_name": "Hack", "event_id": ""},
    }
    write(legacy, "scout_intake.json", intake)
    plan = plan_for(legacy)
    (rest,) = [d["body"] for d in plan.tables["documents"] if d["key"] == "scout_intake.json#rest"]
    assert {k: v["event_id"] for k, v in rest["events"].items()} == {
        "se-1": "ev-demo-day-2026-09-20", "se-2": "ev-meetup-2026-10-01", "se-3": ""}  # fmt: skip
    assert plan.report["reconciliation"]["scout_intake.json"]["event_id_merge_suffixes_stripped"] == 1
    (archived,) = [f for f in plan.archive if f.path == "scout_intake.json"]
    assert archived.parsed["events"]["se-1"]["event_id"].endswith("|merged:Demo Day 2026")  # the archive is untouched


@pytest.mark.parametrize(
    ("raw", "kind", "why"),
    [
        (None, "absent", None), ("  ", "absent", None), ("2026-09-20", "date_only", None),
        ("2026-09-20T18:30", "timed", None), ("2026-09-20T18:30+99:00", "unparseable", "the old parse_when raised"),
        ("0001-01-01T00:30+01:00", "unparseable", "the old parse_when raised"), ("2026-09-20T23:60", "unparseable", "invalid time"),
        ("next week", "unparseable", "no date"), (0, "unparseable", "not text"), (False, "unparseable", "not text"),
    ],
)  # fmt: skip
def test_stated_never_raises(raw: Any, kind: str, why: str | None) -> None:
    from datetime import date

    from projectzero.events.when import stated

    s = stated(raw, today=date(2026, 11, 10))
    assert (s.kind, s.why) == (kind, why)
    assert (s.date is None) is (kind in ("absent", "unparseable"))


# ── reviews 023 / 024: the id-keyed archives are checked by the backfill's own rules (Codex H-188) ──────────────
KEYED = {"evaluations.json": "sessions", "founder_calls.json": "calls"}


@pytest.mark.parametrize("path", sorted(KEYED))
@pytest.mark.parametrize("text", ["{}", '{"version": 1}', '{"COLL": {}}'])
def test_an_absent_or_empty_keyed_collection_imports(legacy: Path, path: str, text: str) -> None:
    write(legacy, path, None, raw=text.replace("COLL", KEYED[path]).encode("utf-8"))
    plan = plan_for(legacy)
    assert not [b for b in plan.blockers if path in b]


@pytest.mark.parametrize("path", sorted(KEYED))
@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ('{"COLL": null}', "must be an object keyed by id (it is null)"),  # explicit null is not absent
        ('{"COLL": []}', "must be an object keyed by id (it is an array)"),
        ('{"COLL": {"r-1": {"id": "r-1"}, "r-1": {"id": "r-1"}}}', "'r-1' is repeated"),  # json.loads would hide it
        ('{"COLL": {"r-1": {"id": 1}}}', "not a record keyed by its own id"),
        ('{"COLL": {"r-1": {"id": null}}}', "not a record keyed by its own id"),
        ('{"COLL": {"": {}}}', "not a record keyed by its own id"),
        ('{"COLL": {"r-1": 5}}', "not a record keyed by its own id"),
        ("[1]", "the top level must be an object"),
    ],
)
def test_a_malformed_keyed_archive_blocks_the_plan(legacy: Path, path: str, text: str, problem: str) -> None:
    write(legacy, path, None, raw=text.replace("COLL", KEYED[path]).encode("utf-8"))
    plan = plan_for(legacy)
    assert any(path in b and problem in b for b in plan.blockers), plan.blockers


@pytest.mark.parametrize("path", sorted(KEYED))
def test_a_bom_prefixed_keyed_archive_plans_like_one_without(legacy: Path, path: str) -> None:
    """Codex H-192: the importer reads ``utf-8-sig``; the preview, the backfills and the readers all skip the BOM."""
    coll = KEYED[path]
    text = json.dumps({"version": 1, coll: {"r-long-zzzz": {"id": "r-long-zzzz"}, "r-1": {"id": "r-1"}}})
    write(legacy, path, None, raw=b"\xef\xbb\xbf" + text.encode("utf-8"))
    plan = plan_for(legacy)
    assert not [b for b in plan.blockers if path in b]
    assert plan.report["reconciliation"][path][coll] == 2


# ── review 025 (decision f): a source-network candidate the Map's city detail would break on blocks the import ─────
def _net(**cands: Any) -> dict[str, Any]:
    return {"candidates": cands}


GOOD_NET = {"id": "net-ok", "name": "Invented Lab Feed", "state": "DISCOVERED", "url": "https://feed.invented.example/x",
            "family": "university_lab"}  # fmt: skip


@pytest.mark.parametrize(
    ("doc", "problem"),
    [
        (_net(a=dict(GOOD_NET, url="example.org")), "the url is not a text with a host"),
        (_net(a={k: v for k, v in GOOD_NET.items() if k != "name"}), "no name"),
        (_net(a=dict(GOOD_NET, family=["grant"])), "the family is list, not a text"),
        (_net(a={k: v for k, v in GOOD_NET.items() if k != "state"}), "not an object with a state"),
        ({"candidates": None}, "candidates are null, not an object"),
        (["x"], "archive is list, not an object"),
    ],
)
def test_a_source_network_candidate_the_map_cannot_read_blocks_the_plan(legacy: Path, doc: Any, problem: str) -> None:
    write(legacy, "sources/network.json", doc)
    plan = plan_for(legacy)
    assert any("sources/network.json" in b and problem in b for b in plan.blockers), plan.blockers


def test_a_rejected_candidate_with_a_bad_url_and_an_empty_archive_do_not_block(legacy: Path) -> None:
    write(legacy, "sources/network.json", _net(a=GOOD_NET, b=dict(GOOD_NET, state="REJECTED", url="example.org")))
    plan = plan_for(legacy)
    assert not [b for b in plan.blockers if "sources/network.json" in b]
    assert plan.report["reconciliation"]["sources/network.json"] == {"candidates_usable": 2}
    write(legacy, "sources/network.json", {})
    assert not [b for b in plan_for(legacy).blockers if "sources/network.json" in b]
