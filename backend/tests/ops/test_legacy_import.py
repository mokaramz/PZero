"""Legacy import planning on a synthetic data folder shaped like the real one (dict- and list-keyed collections)."""

from __future__ import annotations

import hashlib
import itertools
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

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
