"""Review 028a, offline: the catalog is the old text cut by script, the curated cases are the old resource byte for
byte, the port carries only the old literals, and the pure News read side matches the OLD code's goldens
(``oracle_news.json``, ``python -m projectzero.ops.parity_news goldens``), key order included, with the declared (e)
and (s) normalised. Also: reads never write (the curated cases are seeded in memory under the legacy guard), the
Validation entities are built once and shared, the archive key order decides the ties, and the idle refresh job."""

from __future__ import annotations

import ast
import copy
import dataclasses
import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from projectzero.news import (
    NewsInputs,
    base_from_docs,
    catalog,
    claims,
    core,
    inputs_from_docs,
    refresh_status,
    seed_cases,
    sources,
    sources_view,
    view,
    weekly_review,
)
from projectzero.news.inputs_model import CASES_KEY, SEED_CASES, packaged_cases
from projectzero.ops import parity_news
from projectzero.ops.parity_news import CLOCK, ROUTES, SETS, compare_goldens, main_docs
from projectzero.ops.parity_ranking import OLD_REPO
from projectzero.validation import core as validation_core
from projectzero.validation import inputs_from_docs as validation_inputs
from projectzero.validation import view as validation_view

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1" / "oracle_news.json").read_text(encoding="utf-8")
)
OLD = OLD_REPO / "backend" / "src" / "projectzero"
NEWS = OLD / "services" / "news.py"
NEWS_SOURCES = OLD / "services" / "news_sources.py"
CLAIMS = OLD / "services" / "claims.py"
TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 10, 0)
TOP = {
    NEWS: ["EVENTS", "ACTIONS", "RUNS", "RUN_STATE", "COOLDOWN", "WEEKLY", "EARLY_DAYS", "FEEDS", "EVENT_TYPES",
           "TYPE_LABEL", "_NOISE", "_DIGEST", "_ROUND", "_AMOUNT", "GEO_WORDS", "EUROPE", "GEO_LABEL", "THEME_WORDS",
           "PRIORITY_THEMES", "SENSOR_FOR", "CONCEPTS", "_EVENT_VERBS", "STATE_LABEL", "OUTCOME_KIND"],
    NEWS_SOURCES: ["SNAPSHOT", "STATE", "LOG", "DISAGREE", "HISTORY", "EXTRA_FEEDS", "WINDOWS", "DEFAULT_WINDOW",
                   "MIN_OVERLAP", "MIN_COVERED", "SCOPES", "_MUNICH", "_PR", "CANDIDATE_MIN_EVENTS",
                   "DATABASE_DOMAINS", "PUBLICATIONS", "_CITE", "HIGH_AUTHORITY_PRIOR", "HYPOTHESES", "BEST"],
    CLAIMS: ["REGISTRY_OFFICIAL", "REGISTRY_MIRROR", "PROGRAM", "GOVERNMENT", "MEDIA", "AGGREGATOR", "SOCIAL",
             "PRESS_WIRE"],
}  # fmt: skip
VIEW_KEYS = ["date", "pz_start", "today", "stories", "caught_early", "known_late", "misses", "historical",
             "my_companies", "themes", "counts", "metrics", "concept_of_the_day", "notice_earlier", "last_run",
             "state_labels", "signal_families", "note"]  # fmt: skip
ROW_KEYS = ["event_id", "company", "headline", "summary", "event_type", "round", "amount_m", "event_date", "geo",
            "themes", "materiality", "materiality_why", "card", "type_label", "sources", "independent_sources",
            "check", "state", "state_label", "backcast", "concepts", "my_company", "in_deal_flow", "outcome_proposal",
            "outcome_decision", "audit_id", "source_notes", "disagreements"]  # fmt: skip
SOURCES_KEYS = ["window", "start", "today", "benchmark_events", "bias", "best", "disagreements", "sources", "declining",
                "missing", "candidates", "windows", "scopes", "note", "evaluated_at"]  # fmt: skip
SOURCE_ROW_KEYS = ["name", "kind", "geo", "home_scope", "lifecycle", "domain", "articles", "recall", "speed",
                   "earliness", "originality", "unique", "authority", "technical", "independent", "hypothesis",
                   "sample", "roles", "best_use", "not_for", "limitations", "status", "status_reasons"]  # fmt: skip


def _hint_free(text: str) -> str:
    return re.sub(r"^(\w+): [^=\n]+ = ", r"\1 = ", text, flags=re.M)


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_catalog_is_the_old_lines_cut_by_script() -> None:
    ours = _hint_free(Path(catalog.__file__ or "").read_text(encoding="utf-8"))
    for path, names in TOP.items():
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines(keepends=True)
        nodes: dict[str, ast.stmt] = {}
        for n in ast.parse(src).body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                nodes[n.targets[0].id] = n
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                nodes[n.target.id] = n
        picked = [nodes[name] for name in names]
        for node in picked:
            assert _hint_free("".join(lines[node.lineno - 1 : node.end_lineno])) in ours  # the exact old lines
        ns: dict[str, Any] = {"re": re}
        if path == NEWS_SOURCES:
            ns["EARLY_DAYS"] = catalog.EARLY_DAYS
        exec(compile(ast.Module(body=list(picked), type_ignores=[]), str(path), "exec"), ns)  # the old values
        for name in names:
            assert getattr(catalog, name) == ns[name], name
    defined = []
    for n in ast.parse(Path(catalog.__file__ or "").read_text(encoding="utf-8")).body:
        target = n.target if isinstance(n, ast.AnnAssign) else n.targets[0] if isinstance(n, ast.Assign) else None
        if isinstance(target, ast.Name):
            defined.append(target.id)
    assert defined == [*TOP[NEWS], *TOP[NEWS_SOURCES], *TOP[CLAIMS]]
    # news_sources.EARLY_DAYS is News' threshold, cut once
    old_sources = {n.targets[0].id: n for n in ast.parse(NEWS_SOURCES.read_text(encoding="utf-8")).body
                   if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}  # fmt: skip
    assert ast.literal_eval(old_sources["EARLY_DAYS"].value) == catalog.EARLY_DAYS == 14
    assert [k for k, _lab, _rx in catalog.EVENT_TYPES][:5] == [
        "fund",
        "valuation",
        "acquisition",
        "shutdown",
        "funding",
    ]
    assert len(catalog.CONCEPTS) == 17


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_curated_cases_are_the_old_resource_byte_for_byte() -> None:
    old_cases = OLD / "resources" / "news_cases"
    names = sorted(p.name for p in old_cases.glob("*.json"))
    assert sorted(p.name for p in SEED_CASES.glob("*.json")) == names == ["robco.json"]
    for name in names:
        rel = (old_cases / name).relative_to(OLD_REPO).as_posix()
        blob = subprocess.run(["git", "-C", str(OLD_REPO), "show", f"HEAD:{rel}"], capture_output=True, check=True)
        assert (SEED_CASES / name).read_bytes() == blob.stdout
        assert json.loads((SEED_CASES / name).read_text(encoding="utf-8"))["curated"] is True  # observations skip it
    assert packaged_cases() == tuple((n, (SEED_CASES / n).read_text(encoding="utf-8")) for n in names)


def _literals(path: Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_port_carries_the_old_literals_unchanged() -> None:
    old = _literals(NEWS) | _literals(NEWS_SOURCES) | _literals(CLAIMS)
    allowed = {  # the visible reasons of what is deferred, and the new seams
        core: {"NewsInputs.entities: the request's Validation entities are required (inputs_from_docs)"},
        sources: {sources.HEALTH_REASON, "reason", "source alpha unavailable"},
        claims: set(),
    }
    for module, extra in allowed.items():
        tree = ast.parse(Path(module.__file__ or "").read_text(encoding="utf-8"))
        docs = {id(n.body[0].value) for n in ast.walk(tree)  # docstrings are commentary, not the old data
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr)}  # fmt: skip
        ours = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs}  # fmt: skip
        assert sorted(v for v in ours if v not in old and v not in extra) == [], module.__name__


def test_provenance_and_inputs_are_current() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert GOLDEN["clock"] == CLOCK
    assert set(GOLDEN["sets"]) == set(SETS)
    for name, fn in SETS.items():
        # serialized without sort_keys: the documents' insertion order is part of the input
        assert json.dumps(GOLDEN["sets"][name]["docs"]) == json.dumps(json.loads(json.dumps(fn()))), name


def test_the_pure_read_side_matches_the_old_code_including_key_order() -> None:
    assert compare_goldens(GOLDEN) == []


def test_the_goldens_cover_the_planned_cases() -> None:
    sets = {n: s["expected"] for n, s in GOLDEN["sets"].items()}
    assert all(e["changed"] == [] for e in sets.values())  # the old reads wrote nothing to the data folder
    assert all(list(e["routes"]) == ROUTES for e in sets.values())
    main = sets["main"]["routes"]
    v = main["view"]["body"]
    assert list(v) == VIEW_KEYS and list(v["stories"][0]) == ROW_KEYS
    states = {r["state"] for r in v["stories"]} | {r["state"] for r in v["misses"]}
    assert {"CAUGHT_EARLY", "KNOWN_LATE", "MISSED", "HISTORICAL", "UNKNOWN", "NOT_RELEVANT"} <= states
    assert len(v["stories"]) == 60 and v["counts"]["events"] == 94 and v["counts"]["noise_hidden"] == 1
    types = {e["event_type"] for e in GOLDEN["sets"]["main"]["docs"]["news/events.json"]["events"].values()}
    assert set(catalog.TYPE_LABEL) - {"grant"} <= types | {"grant"} and len(v["themes"]) == 2
    rows = {r["event_id"]: r for r in [*v["stories"], *v["misses"], *v["historical"]]}
    assert "nw-bad" not in rows and "nw-nokey" not in rows  # unreadable stories are skipped
    assert rows["nw-late"]["check"]["state"] == "KNOWN_LATE" and rows["nw-late2"]["check"]["lead_days"] == 7
    assert rows["nw-acq"]["outcome_decision"] == "confirm" and rows["nw-acq"]["outcome_proposal"] is None  # last wins
    assert rows["nw-miss"]["audit_id"] == "au-second" and rows["nw-early"]["outcome_proposal"]["kind"]
    assert rows["nw-case-a"]["state"] == "MISSED"  # the operator-added signal (kept by the update) is in PZ's window
    assert [r["event_id"] for r in v["stories"]].index("nw-tie-z") < [r["event_id"] for r in v["stories"]].index(
        "nw-tie-b"
    )
    assert {d["status"] for r in rows.values() for d in r["disagreements"]} == {"OPEN", "RESOLVED"}
    saved = main["view"]["saved"]
    assert saved["seeded"] == ["nw-case-a", "nw-case-b"] and main["weekly"]["saved"] == saved
    assert [s.get("added_by") for s in saved["events"]["nw-case-a"]["backcast"]] == [None, None, None, "mohamed"]
    assert all(main[r]["saved"] is None for r in ROUTES if r not in ("view", "weekly"))
    assert all(sets[n]["routes"]["view"]["saved"] is None for n in ("guard", "noop", "nocases", "empty"))
    assert "nw-case-b" not in {r["event_id"] for r in sets["guard"]["routes"]["view"]["body"]["stories"]}  # the guard
    assert sets["badcase"]["routes"]["view"] == {"raises": "JSONDecodeError", "saved": None}
    assert sets["torn"]["routes"]["refresh_status"]["raises"] == "AttributeError"
    assert all("raises" in sets["broken"]["routes"][f"sources:{w}"] for w in parity_news.WINDOWS)
    assert sets["broken"]["routes"]["view"]["body"]["stories"] == []  # a list as the metric cache: every story skipped
    s90 = main["sources:90"]["body"]
    assert list(s90) == SOURCES_KEYS and list(s90["sources"][0]) == SOURCE_ROW_KEYS
    assert main["sources:7"] == main["sources:90"]  # anything else is 90
    assert len({main[f"sources:{w}"]["body"]["benchmark_events"] for w in ("30", "90", "180")}) == 3
    tech = {r["name"]: r["technical"]["state"] for r in s90["sources"]}
    assert {tech["Tech.eu"], tech["Sifted"], tech["UKTN"], tech["startupticker.ch"]} == {
        "FAILING",
        "BLOCKED",
        "DEGRADED",
        "UNKNOWN",
    }
    assert {b["state"] for b in s90["best"]} == {"RANKED", "COLLECTING DATA"} and s90["missing"][0]["ready"] is True
    assert s90["declining"] and s90["candidates"] and s90["evaluated_at"] == "2026-11-11T16:05:00"
    status = main["refresh_status"]["body"]
    assert status["last"]["status"] == "failed" and status["last_ok"]["status"] == "partial"


def _main() -> NewsInputs:
    return inputs_from_docs(main_docs(), TODAY)


def test_reads_never_write_and_seed_in_memory_under_the_legacy_guard() -> None:
    docs = main_docs()
    before = copy.deepcopy(docs)
    inputs = inputs_from_docs(docs, TODAY)
    frozen = copy.deepcopy(inputs)
    v = view(inputs, TODAY, NOW)
    weekly_review(inputs, TODAY, NOW)
    for w in ("30", "90", "180", "all"):
        sources_view(inputs, w, TODAY)
    refresh_status(inputs)
    assert inputs == frozen and docs == before  # the stored document is never seeded
    assert inputs.events["seeded"] == ["nw-case-a"] and "nw-case-b" not in inputs.events["events"]
    assert "nw-case-b" in {r["event_id"] for r in v["historical"]}  # ... but the read shows the seeded case
    doc, added = seed_cases(inputs.events, inputs.cases, NOW)
    assert added == 2 and doc["events"]["nw-case-b"]["ingested_at"] == "2026-11-12T10:00:00"
    assert doc["events"]["nw-case-b"]["entity_key"] == "invented basin photonics"
    # a curated update keeps the operator's signals, appended after the file's
    file_a = json.loads(dict(inputs.cases or ())["case-a.json"])
    assert doc["events"]["nw-case-a"]["backcast"][: len(file_a["backcast"])] == file_a["backcast"]
    assert doc["events"]["nw-case-a"]["backcast"][-1]["added_by"] == "mohamed"
    assert doc["events"]["nw-case-a"]["precursor_sources"] == file_a["precursor_sources"]
    assert list(doc["events"])[-1] == "nw-case-b"  # a new case is appended to the archive order
    # the same inputs at the same clock: the same answer (the seeding is computed, never stored)
    assert view(inputs, TODAY, NOW) == v


def test_the_legacy_seed_count_guard_and_a_missing_case_file() -> None:
    guard = inputs_from_docs(SETS["guard"](), TODAY)
    assert len(guard.cases or ()) == len(guard.events["seeded"]) == 1  # 1 < 1 is false: nothing is seeded
    assert [r["event_id"] for r in view(guard, TODAY, NOW)["stories"]] == ["nw-g"]
    unseeded = dataclasses.replace(guard, events={**guard.events, "seeded": []})
    assert "nw-case-b" in {r["event_id"] for r in view(unseeded, TODAY, NOW)["historical"]}
    missing = inputs_from_docs(SETS["nocases"](), TODAY)
    assert missing.cases is None and view(missing, TODAY, NOW)["counts"]["events"] == 1
    noop = inputs_from_docs(SETS["noop"](), TODAY)
    doc, added = seed_cases(noop.events, noop.cases, NOW)
    assert added == 0 and doc is noop.events  # nothing changed: the old code saved nothing
    with pytest.raises(json.JSONDecodeError):
        view(inputs_from_docs(SETS["badcase"](), TODAY), TODAY, NOW)


def test_the_validation_entities_are_built_once_and_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    docs = main_docs()
    v_inputs = validation_inputs(docs, TODAY)
    ents = validation_core.entities(v_inputs, TODAY)

    def no_rebuild(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("News re-entered the Validation entity build")

    monkeypatch.setattr(validation_core, "entities", no_rebuild)
    shared = inputs_from_docs(docs, TODAY, entities=ents)
    assert shared.entities is ents and shared.source_alpha
    got = view(shared, TODAY, NOW)  # no second build
    sources_view(shared, "90", TODAY)
    monkeypatch.undo()
    assert got == view(_main(), TODAY, NOW)  # the same values as a fresh build
    with pytest.raises(ValueError, match="entities"):
        view(base_from_docs(docs), TODAY, NOW)  # News never builds them itself


def test_validation_reads_the_news_panel_over_its_own_entity_build(monkeypatch: pytest.MonkeyPatch) -> None:
    v_inputs = validation_inputs(main_docs(), TODAY)
    calls: list[int] = []
    real = validation_core.build

    def counting(*a: Any, **k: Any) -> Any:
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(validation_core, "build", counting)
    body = validation_view(v_inputs, TODAY, NOW)
    assert len(calls) == 1 and body["news"]["available"] is True
    news = view(inputs_from_docs(main_docs(), TODAY), TODAY, NOW)
    assert body["news"]["caught_early"] == news["counts"]["CAUGHT_EARLY"]
    assert body["news"]["median_lead_days"] == news["metrics"]["median_lead_days"]


def test_the_archive_key_order_decides_the_ties() -> None:
    inputs = _main()
    order = [r["event_id"] for r in view(inputs, TODAY, NOW)["stories"]]
    assert order.index("nw-tie-z") < order.index("nw-tie-b")
    events = dict(inputs.events["events"])
    z, b = events.pop("nw-tie-z"), events.pop("nw-tie-b")
    flipped = dataclasses.replace(inputs, events={**inputs.events, "events": {"nw-tie-b": b, "nw-tie-z": z, **events}})
    order = [r["event_id"] for r in view(flipped, TODAY, NOW)["stories"]]
    assert order.index("nw-tie-b") < order.index("nw-tie-z")


def test_the_refresh_job_is_idle_and_the_window_falls_back_to_90() -> None:
    inputs = _main()
    status = refresh_status(inputs)
    assert list(status) == ["job", "last", "last_ok", "events_total"]
    assert status["job"] == dict.fromkeys(core.JOB_KEYS) | {"running": False}
    assert status["events_total"] == len(inputs.events["events"])  # the stored archive: no seeding here
    assert sources.normal_window("365") == "90" and sources.normal_window("all") == "all"
    assert sources_view(inputs, None, TODAY)["window"] == "90"
    swiss = next(r for r in sources_view(inputs, "90", TODAY)["sources"] if r["kind"] == "deal_flow_reuse")
    assert swiss["technical"]["state"] == "UNKNOWN" and swiss["technical"]["reason"] == sources.HEALTH_REASON
    assert swiss["earliness"]["deal_flow"] is not None  # the source-alpha row of the shared entity build


def test_the_rules_classify_like_the_old_code() -> None:
    c = core.classify("Invented Kestrel Robotics raises €4M seed round in Munich", "A robotics startup.")
    assert c == {"event_type": "funding", "round": "seed", "amount_m": 4.0, "geo": ["DE"], "themes": ["robotics"],
                 "noise": False}  # fmt: skip
    assert core.classify("Invented Fund closes €80M Fund II")["event_type"] == "fund"  # first match wins
    assert core.amount_m("raised $1.2bn") == 1200.0 and core.amount_m("€500k") == 0.5
    assert core.is_noise("Top 10 startups to watch") and core.is_roundup("X raises $5M, Y acquires Z")
    assert core.materiality({"event_type": "funding", "amount_m": 25, "round": ""}) == ("HIGH", ["large round (25M)"])
    assert claims.classify("https://www.startupticker.ch/x")["publisher_class"] == "media"
    assert sources._prior("reuters.com", "external") == "HIGH-QUALITY INDEPENDENT MEDIA"
    assert base_from_docs({CASES_KEY: None}).cases is None and base_from_docs({CASES_KEY: {}}).cases == ()
