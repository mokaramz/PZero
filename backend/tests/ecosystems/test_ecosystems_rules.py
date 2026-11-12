"""Review 022, offline: the adopt order (plan revision 3), the merge of the imported documents with the adoption rows
(plan revision 2), the legacy id mapping and the kept quirks, on small invented inputs."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from projectzero.ecosystems import adopt, catalog, cities, coverage
from projectzero.ecosystems.inputs import CoverageInputs, merged_adoptions, merged_overrides

NOW = datetime(2026, 11, 11, 11, 0, tzinfo=UTC)  # 12:00 in Berlin


def cand(name: str, **kw: Any) -> dict[str, Any]:
    return {"source_name": name, "url": "https://x.example.org", "country": "Austria", "city": "Quellbrunn",
            "signal_family": "grants", "access_mode": "html", "access_limitations": ""} | kw  # fmt: skip


def base(**kw: Any) -> CoverageInputs:
    docs = {"registry_id": "INV", "version": "1", "sources": [
        cand("Invented Historic", url="", access_limitations="login wall now"),  # archived, now unusable
        cand("Invented Fresh"),
        cand("Invented Locked", access_limitations="CAPTCHA on every page"),
        cand("Invented Locked Api", access_limitations="needs a login", access_mode="structured"),
        cand("Invented Offline", url="ftp://x.example.org"),
        cand("Invented Present"),
    ]}  # fmt: skip
    adopted = {"adopted": {"cand-invented-historic": {"source_id": "cov-archived-other", "on": "2026-10-01 09:30",
                                                      "by": "operator"}}}  # fmt: skip
    fields: dict[str, Any] = {
        "coverage_candidates": docs,
        "coverage_adopted": adopted,
        "candidate_files": (),
        "audit_files": (),
        "sources": [{"id": "cov-invented-present", "name": "Invented Present"}],
    }
    return CoverageInputs(**(fields | kw))  # fmt: skip


def row(cid: str, sid: str, **kw: Any) -> dict[str, Any]:
    return {"candidate_id": cid, "source_id": sid, "families": ["grants"], "countries": ["AT"], "cities": [],
            "note": "adopted from coverage audit", "by": "operator", "adopted_at": NOW} | kw  # fmt: skip


def test_the_old_order_confirmation_first_then_the_catalog_then_a_recorded_adoption() -> None:
    i = base()
    assert adopt.adopt_plan(i, "cand-nope", False).response == {"ok": False, "error": "explicit confirmation required"}
    assert adopt.adopt_plan(i, "cand-nope", True).response == {"ok": False, "error": "unknown candidate"}
    # the historical retry: answered with the ARCHIVED id before the (now failing) limitation and URL checks
    retry = adopt.adopt_plan(i, "cand-invented-historic", True)
    assert retry.response == {"ok": True, "already": True, "source_id": "cov-archived-other"} and not retry.writes
    assert adopt.adopt_plan(i, "cand-invented-historic", False).response["error"] == "explicit confirmation required"


def test_the_refusals_and_an_existing_source() -> None:
    i = base()
    locked = adopt.adopt_plan(i, "cand-invented-locked", True)
    assert (
        locked.response["ok"] is False
        and "access limitation recorded by the audit (CAPTCHA" in locked.response["error"]
    )
    assert adopt.adopt_plan(i, "cand-invented-locked-api", True).writes  # structured access is allowed
    assert adopt.adopt_plan(i, "cand-invented-offline", True).response == {"ok": False, "error": "candidate has no URL"}
    present = adopt.adopt_plan(i, "cand-invented-present", True)  # no archived adoption, but the cov- source exists
    assert present.response == {"ok": True, "already": True, "source_id": "cov-invented-present"}
    assert not present.writes and present.declaration is None


def test_the_legacy_id_mapping_and_the_new_records() -> None:
    d = adopt.adopt_plan(base(), "cand-invented-fresh", True)
    assert d.source_id == "cov-" + "cand-invented-fresh"[5:] == "cov-invented-fresh"
    assert d.response["source_id"] == "cov-invented-fresh" and d.by == "operator"
    assert d.declaration == {"families": ["grants"], "countries": ["AT"], "cities": ["Quellbrunn"],
                             "note": "adopted from coverage audit"}  # fmt: skip
    assert d.source is not None
    assert d.source["kind"] == "watcher" and d.source["stage"] == "grant" and d.source["geo"] == ["AT"]
    assert d.source["enabled"] is True and d.source["audit_origin"]["file"] == "coverage_candidates.json"


def test_an_adoption_row_answers_already_with_its_recorded_id() -> None:
    i = base(adoptions=[row("cand-invented-fresh", "cov-invented-fresh")])
    again = adopt.adopt_plan(i, "cand-invented-fresh", True)
    assert again.response == {"ok": True, "already": True, "source_id": "cov-invented-fresh"} and not again.writes


def test_the_merge_rules() -> None:
    imported = {"sources": {"x-other": {"families": ["events"], "countries": ["FR"]},
                            "cov-y": {"families": ["general"], "countries": ["DE"]}}}  # fmt: skip
    i = base(coverage_sources=imported, adoptions=[row("cand-y", "cov-y"), row("cand-invented-historic", "cov-z")])
    over = merged_overrides(i)
    assert over["x-other"] == imported["sources"]["x-other"]  # another source's override is untouched
    assert over["cov-y"] == {
        "families": ["grants"],
        "countries": ["AT"],
        "cities": [],
        "note": "adopted from coverage audit",
    }
    ad = merged_adoptions(i)
    assert ad["cand-invented-historic"]["source_id"] == "cov-archived-other"  # a row never replaces an import
    assert ad["cand-y"] == {"source_id": "cov-y", "on": "2026-11-11 12:00", "by": "operator"}  # Berlin wall time
    empty = base(coverage_adopted={"adopted": {"cand-y": {}}}, adoptions=[row("cand-y", "cov-y")])
    assert merged_adoptions(empty)["cand-y"]["source_id"] == "cov-y"  # an empty record was never an adoption
    assert merged_overrides(CoverageInputs()) == {} and merged_adoptions(CoverageInputs()) == {}


def test_imported_state_survives_a_new_adoption() -> None:
    """Codex H-165: a standalone override, an archived adoption and a custom ecosystem, then a retry and a new one."""
    i = base(
        coverage_sources={"sources": {"x-standalone": {"families": ["events"], "countries": [], "cities": ["Quellbrunn"]}}},
        coverage_registry={"ecosystems": [{"city": "Quellbrunn", "country": "AT", "region": "Invented Alps"}]},
        sources=[{"id": "x-standalone", "name": "Invented Standalone", "enabled": True}],
    )  # fmt: skip
    retry = adopt.adopt_plan(i, "cand-invented-historic", True)
    assert not retry.writes and adopt.with_adoption(i, retry, NOW) is i  # zero rows of any kind
    fresh = adopt.adopt_plan(i, "cand-invented-fresh", True)
    after = adopt.with_adoption(i, fresh, NOW)
    assert len(after.adoptions) == 1 and after.sources[0]["id"] == "x-standalone"
    assert "cov-invented-fresh" in {s["id"] for s in after.sources}
    view = coverage.coverage_view(after, NOW)
    rows = {c["id"]: c for c in view["candidates"]["rows"]}
    assert rows["cand-invented-historic"]["adopted"] == {"source_id": "cov-archived-other", "on": "2026-10-01 09:30",
                                                         "by": "operator"}  # fmt: skip
    assert rows["cand-invented-fresh"]["status"] == "ADOPTED — configured as watcher (2026-11-11 12:00)"
    quell = next(e for e in view["ecosystems"] if e["city"] == "Quellbrunn")
    assert quell["region"] == "Invented Alps"
    declared = {s["id"]: s["declared_by"] for f in quell["families"].values() for s in f["sources"]}
    assert (
        declared["x-standalone"] == "coverage_sources.json"
        and declared["cov-invented-fresh"] == "coverage_sources.json"
    )


def test_an_event_source_is_never_productive() -> None:
    """Decision b: the event_health rows carry no count, so a fresh retrieval alone is not productive."""
    health = {"sources": [{"id": "ev-cyberforum", "status": "ok", "last_ok": "2026-11-10 06:00", "raw": 9}]}
    i = CoverageInputs(event_health=health, candidate_files=(), audit_files=())
    reg = coverage.ecosystems(i)
    s = next(x for x in coverage.declared_sources(i, reg, date(2026, 11, 11)) if x["id"] == "ev-cyberforum")
    assert s["retrieved"] is True and s["productive"] is False and s["families"] == ["events"]


def test_missing_bootstrap_documents_read_as_the_old_defaults() -> None:
    """Decision a: nothing is written; a missing document is the default in memory."""
    assert coverage.load_regions(None) == catalog.DEFAULT_REGIONS
    assert coverage.load_sources(None) == catalog.RADAR_DEFAULT_SOURCES
    v1 = {"sources": [{"id": "gh-x", "kind": "github_users"}, {"id": "oa-x", "kind": "openalex_works"}]}
    assert coverage.load_sources(v1) == [{"id": "oa-x", "kind": "openalex_works"}] and "schema" not in v1
    assert coverage.event_health(None)["sources"] == [] and coverage.radar_health([])["sources"] == []


def test_the_city_view_keeps_the_unknown_earliness_raise_and_the_orgs_merge() -> None:
    sig = [{"company": "Invented Odd", "location": "Karlsruhe", "earliness": "weird"}]
    with pytest.raises(TypeError):
        cities.eco_view("Karlsruhe", sig, [], [], None, date(2026, 11, 11))
    doc = {"institutions": [{"name": "Invented Hub", "kind": "hub", "city": "Karlsruhe"}, {"name": "No kind"}]}
    view = cities.eco_view("Karlsruhe", [], [], [], doc, date(2026, 11, 11))
    assert [o["name"] for o in view["orgs"]][-1] == "Invented Hub" and view["note"].startswith("Home base.")
