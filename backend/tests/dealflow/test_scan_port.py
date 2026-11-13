"""Review 034a, offline: the scan's parsers are the old text cut by script, the pure phase 2 matches the OLD code's
goldens (``oracle_scan.json``), and the pure pieces of phase 3 (the entity mapping, the batch hosts, the record lines,
the run id, the creation hints, the readers' overlay, the counters) behave as declared."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from projectzero.dealflow.intake.contract import Origin, validate_entity
from projectzero.dealflow.intake.postgres import PostgresIntake
from projectzero.dealflow.intake.service import TrustedBatch
from projectzero.dealflow.ranking.service import ranking_input
from projectzero.dealflow.scan import history, ingest, parsers, records, run, seams, sources_v2, taste
from projectzero.dealflow.sources import counters
from projectzero.dealflow.sources.registry import registry_namespace
from projectzero.jobs.catalog import REAL
from projectzero.jobs.ported import PORTED
from projectzero.ops import parity_scan
from projectzero.ops.parity_ranking import OLD_REPO

ROOT = Path(__file__).resolve().parents[3]
OLD = OLD_REPO / "backend" / "src" / "projectzero" / "domain"
GOLDEN: dict[str, Any] = json.loads(parity_scan.GOLDEN.read_text(encoding="utf-8"))


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location("gen_scan_catalog", ROOT / "scripts" / "gen_scan_catalog.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_parsers_are_the_old_top_level_lines_cut_by_script() -> None:
    built = _generator().build()  # every cut checked node for node against the old module inside build()
    for name, mod in (("parsers.py", parsers), ("sources_v2.py", sources_v2), ("taste.py", taste)):
        assert built[name] == Path(mod.__file__ or "").read_text(encoding="utf-8"), name  # regenerating changes nothing


def test_the_cut_module_keeps_the_old_registry_of_parsers_and_budgets() -> None:
    assert sorted(parsers.PARSERS) == sorted(
        ["page_diff", "rss", "sbir", "nsf", "nih", "gtr", "cordis", "ckan", *sources_v2.PARSERS_V2]
    )
    assert parsers.PARSERS["page_diff"] is None and parsers.PARSERS["rss"] is None
    assert (run.MAX_WORKERS, run.TIME_BUDGET_S, run.SOURCE_BUDGET_S, parsers.TIMEOUT) == (6, 240, 90, 20)
    assert run.LOCK == "{schema}.dealflow.scan" and "pz." not in run.LOCK
    assert parsers.RUNTIME_KEYS == ("last_scan", "last_ok", "last_result_count", "failures_in_row", "total_results",
                                    "last_truncated", "hwm")  # fmt: skip
    tree = ast.parse(Path(parsers.__file__ or "").read_text(encoding="utf-8"))
    names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {"_get_raw", "_request_json", "_snap_path", "_load_snapshot", "_save_snapshot"} <= names
    assert "insecure_tls_fallback" not in Path(parsers.__file__ or "").read_text(encoding="utf-8")


def test_the_pure_scan_matches_the_old_goldens() -> None:
    assert GOLDEN["provenance"]["old_dirty"] is False and GOLDEN["expected"]["blocked"] == []
    assert parity_scan.compare_pure(GOLDEN) == []


def test_a_parser_outside_a_scan_source_has_no_network() -> None:
    with pytest.raises(RuntimeError, match="outside a scan source context"):
        parsers._get_raw("https://example.com/")


def test_every_fetch_goes_through_core_net_with_the_runs_transport() -> None:
    t = parity_scan.FixtureTransport({"https://a.invented.example/x": {"body": "hello"}})
    ctx = seams.SourceContext(today=date(2026, 11, 13), transport=t, resolver=parity_scan.fixture_resolver)
    with seams.source(ctx):
        assert parsers._get("https://a.invented.example/x") == "hello"
        with pytest.raises(Exception, match="HTTP Error 404"):
            parsers._get("https://a.invented.example/missing")
        with pytest.raises(Exception, match="non-public"):
            parsers._get("http://127.0.0.1/admin")  # decision e: core/net's SSRF guard
        assert parsers._fetch_stats()["attempts"] == 3 and parsers._fetch_stats()["ok"] == 1
    assert t.asked == ["https://a.invented.example/x", "https://a.invented.example/missing"]


# ------------------------------------------------------------------ phase 3, pure pieces
def record(**kw: Any) -> dict[str, Any]:
    base = {"id": "a1b2c3d4e5f6", "name": "Aurora Robotics", "source": "Invented Feed (feed)", "discovery_tier": "announcement",
            "source_url": "https://feed.invented.example/news/aurora", "description": "Aurora Robotics raises a seed round",
            "decision": "new", "source_id": "fx-feed", "geo": ["DACH"], "country": "Germany", "date_kind": "published",
            "source_date": "2026-10-19", "sectors": ["robotics"]}  # fmt: skip
    return {**base, **kw}


def test_the_entity_mapping_decision_a() -> None:
    e = ingest.entity_of(
        record(discovery_tier="pre_company", entity_ids={"uei": "UEI1", "duns": "0", "domain": "aurora.example.com"})
    )
    assert e == {"kind": "company", "name": "Aurora Robotics", "key_fact": "Aurora Robotics raises a seed round",
                 "evidence": [{"url": "https://feed.invented.example/news/aurora", "title": "Invented Feed (feed)"}],
                 "location": {"country": "DE"}, "sectors": ["robotics"], "signal_date": "2026-10-19",
                 "external_id": "fx-feed:a1b2c3d4e5f6", "flags": ["pre_company"], "registry_ids": {"uei": "UEI1"},
                 "website": "https://aurora.example.com"}  # fmt: skip
    assert validate_entity(e) == []
    grant = ingest.entity_of(record(discovery_tier="grant", source_id="uk-gtr", entity_ids={"org_id": "gtr-O-1"}))
    assert grant["kind"] == "opportunity" and grant["registry_ids"] == {"org_id": "gtr-O-1"}  # schema-valid (H-343)
    assert validate_entity(grant) == []


def test_the_scan_registry_ids_resolve_under_the_importers_namespaces() -> None:
    """H-343: the importer and the scan's identity resolution share ``registry_namespace``; the delivery keeps the
    schema-valid kinds and the hint's ``source_id`` qualifies them, for the registry scan only."""
    assert registry_namespace("uei", "fx-sbir") == "uei:fx-sbir"
    assert registry_namespace("duns", "fx-sbir") == "duns"
    assert registry_namespace("org_id", "uk-gtr") == "gtr_org"
    assert registry_namespace("org_id", "eu-cordis") == "org_id:eu-cordis"
    e = {"registry_ids": {"uei": "U1", "duns": "123456789", "handelsregister": "HRB 1"}}
    scan = Origin.REGISTRY_SCAN.value
    assert PostgresIntake._strong_keys(e, scan, {"source_id": "fx-sbir"}) == [
        ("registry", "duns", "123456789"), ("registry", "handelsregister", "HRB 1"), ("registry", "uei:fx-sbir", "U1")]  # fmt: skip
    assert PostgresIntake._strong_keys({"registry_ids": {"org_id": "gtr-O-1"}}, scan, {"source_id": "uk-gtr"}) == [
        ("registry", "gtr_org", "gtr-O-1")]  # fmt: skip
    other = next(o for o in Origin if o is not Origin.REGISTRY_SCAN and o.value != scan)
    assert PostgresIntake._strong_keys(e, other.value, {"source_id": "fx-sbir"})[-1] == ("registry", "uei", "U1")
    assert PostgresIntake._strong_keys(e, scan, None)[-1] == ("registry", "uei", "U1")  # no hint: verbatim
    assert ingest.external_id(record(source_id="eu_cordis horizon")) == "eu_cordis-horizon:a1b2c3d4e5f6"
    refused = ingest.entity_of(record(source_url=""))
    assert refused["evidence"] == [] and validate_entity(refused)  # no source URL: the contract refuses it


def test_the_creation_status_decision_c() -> None:
    assert [ingest.creation_status(record(decision=d)) for d in ("new", "baseline", "rejected", "kept")] == [
        "new", "baseline", "rejected", "new"]  # fmt: skip
    with pytest.raises(ValueError, match="registry scan only"):
        TrustedBatch(Origin.RESEARCH, "x", [{}], scan={0: {"status": "new"}})
    with pytest.raises(ValueError, match="invalid scan creation hint"):
        TrustedBatch(Origin.REGISTRY_SCAN, "x", [{}], scan={0: {"status": "kept"}})
    with pytest.raises(ValueError, match="invalid scan creation hint"):
        TrustedBatch(Origin.REGISTRY_SCAN, "x", [{}], scan={1: {"status": "new"}})


def test_batch_hosts_follow_the_cut_resolution() -> None:
    a = record()
    b = record(id="b" * 12, source="Invented Feed Two (feed)", source_id="fx-feed2")
    c = record(id="c" * 12, name="Echo Photonics", source_id="fx-feed2")
    cands = [b, a, c]
    hosts = ingest.batch_hosts(cands)
    merged = parsers._resolve_batch(cands, [])
    assert [x["id"] for x in merged] == [a["id"], c["id"]]
    assert hosts[id(b)] is a and hosts[id(a)] is a and hosts[id(c)] is c
    assert merged[0]["also_seen"][0]["source_id"] == "fx-feed2"


def test_a_watcher_record_maps_back_to_its_lines() -> None:
    fresh = [
        "Hotel Robotics GmbH – robotics spin-off founded 2026",
        "09.10.2026 15:09",
        "India Quantum opens Munich office",
    ]
    rec = {"name": "Hotel Robotics GmbH", "description": fresh[0]}
    assert ingest.record_lines(rec, fresh) == {fresh[0]}
    swapped = {"name": "India Quantum opens Munich office", "description": fresh[2]}
    assert ingest.record_lines(swapped, fresh) == {fresh[2]}


def test_the_run_id_is_unique_like_the_old_one() -> None:
    t = datetime(2026, 11, 13, 9, 0, 0)
    assert ingest.unique_run_id(t, set()) == "2026-11-13 09:00:00"
    assert ingest.unique_run_id(t, {"2026-11-13 09:00:00", "2026-11-13 09:00:00 #2"}) == "2026-11-13 09:00:00 #3"


def test_created_and_absorb_are_the_old_ones() -> None:
    rec = records.created(
        record(also_seen=[{"source": "Invented Feed Two (feed)", "source_id": "fx-feed2"}]), "R1", "2026-11-13"
    )
    assert (rec["run_id"], rec["first_seen_run"], rec["last_observed"], rec["seen_runs"]) == ("R1", "R1", "R1", 1)
    assert rec["also_seen"][0]["first_seen"] == "R1" and rec["q_found"] == ["fx-feed", "fx-feed2"]
    host = copy.deepcopy(rec)
    added = records.absorb(host, record(source="Invented Page", source_id="fx-page"), "R2")
    assert added == 1 and host["seen_runs"] == 2 and host["last_observed"] == "R2"
    assert host["all_source_ids"] == ["fx-feed", "fx-feed2", "fx-page"] and host["q_found"][-1] == "fx-page"
    assert records.absorb(host, record(source="Invented Page", source_id="fx-page"), "R3") == 0


def test_the_ranking_reads_a_scan_record_like_an_imported_one() -> None:
    rec = records.created(record(), "R1", "2026-11-13")
    row = {"id": "zz", "status": "rejected", "attrs": {"scan_record": rec, "notes": "operator note"}, "legacy": None}
    c, kind = ranking_input(row)
    assert kind == "full" and c["decision"] == "rejected" and c["notes"] == "operator note" and c["id"] == rec["id"]


def test_the_history_overlay_and_the_inbox_rest() -> None:
    imported = {"scans": [{"run_id": f"old-{i}"} for i in range(59)]}
    runs = [{"run_id": "R1", "summary": {"new": 1, "run_id": "R1"}, "report": [{"source": "x"}], "sources": [{"s": 1}]},
            {"run_id": "R2", "summary": {"new": 2, "run_id": "R2"}, "report": [], "sources": []}]  # fmt: skip
    out = history.overlay(imported, runs)
    assert len(out["scans"]) == 60 and out["scans"][0]["run_id"] == "old-1"  # the old [-60:]
    assert out["scans"][-1] == {"new": 2, "run_id": "R2", "sources": []}
    assert history.overlay(imported, []) is imported
    rest = {"last_run": "old", "report": ["old"], "last_summary": {"new": 0}, "reprocess_v": 3}
    assert history.overlay_rest(rest, None) == rest
    got = history.overlay_rest(rest, {"run_id": "R2", "report": [], "summary": {"new": 2}})
    assert got == {"last_run": "R2", "report": [], "last_summary": {"new": 2}, "reprocess_v": 3}


def test_candidates_found_is_derived_from_the_scan_records() -> None:
    out = counters.derive([], [], {}, {}, ["fx-feed", "fx-feed2", "fx-feed"])
    assert out == {"fx-feed": {"quality": {"candidates_found": 2}, "yield": {}},
                   "fx-feed2": {"quality": {"candidates_found": 1}, "yield": {}}}  # fmt: skip


def test_the_runner_runs_the_scan() -> None:
    assert "deal_flow_scan" in PORTED and REAL["deal_flow_scan"].interval_h == 168
    assert REAL["deal_flow_scan"].last == "_last_scan"


def test_the_clock_is_berlin_and_aware() -> None:
    clock = run._berlin_clock(lambda: datetime(2026, 11, 13, 8, 0, tzinfo=UTC))
    assert clock().isoformat() == "2026-11-13T09:00:00+01:00"
    naive = run._berlin_clock(lambda: datetime(2026, 11, 13, 9, 0))
    assert naive().isoformat() == "2026-11-13T09:00:00+01:00"
