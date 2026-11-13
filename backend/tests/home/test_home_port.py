"""Review 031a, offline: the pure Investment Desk matches the OLD code's goldens (``oracle_home.json``, ``python -m
projectzero.ops.parity_home goldens``), key order included, with no declared difference. Also: the port carries only
the old literals, the reused helpers are the old ones, reads never write and never mutate their inputs, the payload
key order, the best opportunity's ranking and exclusions, the weekend-first event, the inbox order of the new
signals, the Omar sort, the 7-day boundary under one clock, and the adapter's old loader semantics."""

from __future__ import annotations

import ast
import copy
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from projectzero.conviction import records as conviction_records
from projectzero.conviction.records import safe_score
from projectzero.dealflow.ranking import names
from projectzero.home import UNREADABLE, HomeInputs, core, inputs_from_docs, view
from projectzero.ops.parity_home import CLOCK, WORLDS, compare_goldens, main_docs, read_golden
from projectzero.ops.parity_ranking import OLD_REPO

GOLDEN: dict[str, Any] = read_golden()
OLD = OLD_REPO / "backend" / "src" / "projectzero"
ECOSYS_PY = OLD / "domain" / "ecosys.py"
NOW = datetime.fromisoformat(CLOCK)
PAYLOAD_KEYS = ["priority", "best_event", "due", "new_signals", "latest_signals", "omar", "progress", "watch",
                "weekday", "date"]  # fmt: skip
PRIORITY_KEYS = ["slug", "company", "score", "verified", "verdict", "op", "next", "timing"]
PROGRESS_KEYS = ["found", "contacted", "sent_omar", "people_added", "events_planned", "verified"]


def _served(name: str) -> dict[str, Any]:
    body: dict[str, Any] = GOLDEN["worlds"][name]["expected"]["ok"]
    return body


def _new(docs: dict[str, Any], now: datetime = NOW) -> dict[str, Any]:
    return view(inputs_from_docs(docs, now.date(), now), now.date(), now)


def _with_signals(*companies: str, order: list[str] | None = None) -> dict[str, Any]:
    docs = main_docs()
    by = {e["company"]: e for e in docs["real_data.json"]["signals"]}
    docs["real_data.json"]["signals"] = [by[c] for c in (order or list(companies))]
    return docs


# ------------------------------------------------------------------ the goldens
def test_provenance_and_inputs_are_current() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    frozen = set(GOLDEN["provenance"]["frozen"])
    for module in ("domain.ecosys.date", "domain.people.date", "domain.events.date", "domain.events.datetime",
                   "services.case_prep.date", "services.case_prep.datetime"):  # fmt: skip
        assert f"projectzero.{module}" in frozen, module  # the old desk read the frozen clock
    assert set(GOLDEN["worlds"]) == set(WORLDS)
    for name, (fn, clock) in WORLDS.items():
        w = GOLDEN["worlds"][name]
        assert w["clock"] == clock
        assert w["expected"]["blocked"] == [] and w["expected"]["changed"] == []  # the old desk wrote nothing
        # serialized without sort_keys: the documents' insertion order is part of the input
        assert json.dumps(w["docs"]) == json.dumps(json.loads(json.dumps(fn()))), name


def test_the_pure_view_matches_the_old_code_including_key_order() -> None:
    assert compare_goldens(GOLDEN) == []


def test_the_goldens_cover_the_planned_cases() -> None:
    main, fallback = _served("main"), _served("fallback")
    # the best opportunity: provisional ranking, the prepared case's action (not the stored ``next_action``)
    assert main["priority"]["company"] == "Invented Juniper Grid" and main["priority"]["score"] == 79
    assert main["priority"]["verified"] is False and main["priority"]["op"]["source"] == "prepared case"
    assert main["priority"]["next"] == "Verify the founders' prior exit"
    # verified ranking, the score band: ``next`` is the stored ``next_action``
    assert fallback["priority"]["company"] == "Invented Arclight Systems" and fallback["priority"]["verified"] is True
    assert fallback["priority"]["op"]["source"] == "score band"
    assert fallback["priority"]["next"] == "Invented: book the intro call"
    assert _served("gated")["priority"] is None and _served("empty")["priority"] is None
    assert _served("legacy")["priority"]["company"] == "Invented Umber Fields"
    # the events: weekend first, the fallback, none
    assert main["best_event"]["weekend"] is True and main["best_event"]["id"] == "ev-2"
    assert fallback["best_event"]["weekend"] is False and fallback["best_event"]["id"] == "ev-2"
    assert _served("gated")["best_event"] is None
    # the cuts
    assert len(main["due"]) == len(main["watch"]) == 6
    assert main["new_signals"] == 4 and [s["name"] for s in main["latest_signals"]] == [
        "Invented Rookwood", "Invented Quillon", "Invented Tamworth Optics"]  # fmt: skip
    assert [o["sent"] for o in main["omar"]] == ["2026-11-12", "2026-11-12", "2026-11-07", "2026-11-06", "2026-11-05"]
    assert [o["company"] for o in main["omar"][:2]] == ["Invented Ovenden Works", "Invented Wexcombe"]  # stable tie
    assert main["progress"] == {"found": 3, "contacted": 3, "sent_omar": 4, "people_added": 3, "events_planned": 2,
                                "verified": 2}  # fmt: skip
    assert "p-omar-hedeya" in [p["id"] for p in main["watch"]]  # listed, but never counted as added
    assert _served("empty") == {**_served("empty"), "due": [], "omar": [], "watch": [], "new_signals": 0}


# ------------------------------------------------------------------ the port
def _literals(tree: ast.AST, skip_docstrings: bool) -> set[str]:
    docs = set()
    if skip_docstrings:
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr)}  # fmt: skip
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs}  # fmt: skip


def _old_function(path: Path, name: str) -> ast.FunctionDef:
    return next(n for n in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(n, ast.FunctionDef) and n.name == name)  # fmt: skip


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_port_carries_the_old_literals_unchanged() -> None:
    old = _literals(_old_function(ECOSYS_PY, "home"), skip_docstrings=False)
    ours = _literals(ast.parse(Path(core.__file__ or "").read_text(encoding="utf-8")), skip_docstrings=True)
    assert sorted(ours - old) == []  # every key, status, text and the ``p-omar-hedeya`` constant are the old ones


def _body(fn: ast.FunctionDef) -> str:
    body = fn.body[1:] if fn.body and isinstance(fn.body[0], ast.Expr) else fn.body  # the docstring aside
    return ast.dump(ast.Module(body=body, type_ignores=[]))


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_reused_helpers_are_the_old_ones() -> None:
    new_records = ast.parse(Path(conviction_records.__file__ or "").read_text(encoding="utf-8"))
    new_readable = next(n for n in new_records.body if isinstance(n, ast.FunctionDef) and n.name == "readable")
    assert _body(new_readable) == _body(_old_function(OLD / "services" / "pipeline.py", "_readable"))
    new_names = ast.parse(Path(names.__file__ or "").read_text(encoding="utf-8"))
    new_slug = next(n for n in new_names.body if isinstance(n, ast.FunctionDef) and n.name == "slug")
    assert _body(new_slug) == _body(_old_function(OLD / "domain" / "radar.py", "slug"))


def test_the_payload_key_order() -> None:
    body = _new(main_docs())
    assert list(body) == PAYLOAD_KEYS
    assert list(body["priority"]) == PRIORITY_KEYS and list(body["progress"]) == PROGRESS_KEYS
    assert all(list(d) == ["id", "name", "action", "date"] for d in body["due"])
    assert all(list(w) == ["id", "name", "last"] for w in body["watch"])
    assert body["weekday"] == "Friday" and body["date"] == "2026-11-13"


def test_reads_never_mutate_their_inputs_or_documents() -> None:
    for name, (fn, _clock) in WORLDS.items():
        docs = fn()
        before = copy.deepcopy(docs)
        inputs = inputs_from_docs(docs, NOW.date(), NOW)
        snapshot = copy.deepcopy(inputs)
        body = view(inputs, NOW.date(), NOW)
        assert docs == before and inputs == snapshot, name
        if body["best_event"]:  # the answer shares nothing with the inputs: mutating it changes no input
            body["best_event"]["when"]["start_date"] = "mutated"
        for e in body["due"] + body["watch"]:
            e["name"] = "mutated"
        assert inputs == snapshot, name
    legacy = inputs_from_docs(WORLDS["legacy"][0](), NOW.date(), NOW)
    view(legacy, NOW.date(), NOW)
    assert all("data_warning" not in e or e["company"] == "Invented Tarn Robotics" for e in legacy.signals)


# ------------------------------------------------------------------ focused cases
def test_each_exclusion_alone_leaves_no_best_opportunity() -> None:
    for company in ("Invented Dunmore Analytics", "Invented Eskerfield", "Invented Kestrel Defence",
                    "Invented Selby Optics", "Invented Pellow Farms", "Invented Larch Dynamics"):  # fmt: skip
        e = next(x for x in main_docs()["real_data.json"]["signals"] if x["company"] == company)
        sc = safe_score(copy.deepcopy(e))
        assert (sc["verified"] if sc["fully_verified"] else sc["provisional"]) > 79, company  # it would have won
        assert _new(_with_signals(company))["priority"] is None, company
    statuses = {c: _new(_with_signals(c))["priority"] for c in ("Invented Corvid Labs", "Invented Arclight Systems")}
    assert statuses["Invented Corvid Labs"]["op"]["status"] == "AWAITING FOUNDER RESPONSE"  # not an exclusion
    assert statuses["Invented Arclight Systems"]["next"] == "Invented: send the intro note"


def test_max_keeps_the_first_of_equal_scores() -> None:
    a, b = "Invented Juniper Grid", "Invented Quarry Point"
    assert _new(_with_signals(a, b))["priority"]["company"] == a
    assert _new(_with_signals(a, b, order=[b, a]))["priority"]["company"] == b
    assert _new(_with_signals(b, order=[b]))["priority"]["next"] == ""  # the score band without a stored next_action


def test_the_weekend_event_comes_first_else_the_best_upcoming() -> None:
    docs = main_docs()
    weekday = [e for e in docs["events.json"]["events"] if e["id"] not in ("ev-2", "ev-3")]
    best = _new({**docs, "events.json": {"events": weekday}})["best_event"]
    assert best["id"] == "ev-1" and best["weekend"] is False and best["rank"] > _served("main")["best_event"]["rank"]


def test_the_new_signals_follow_the_inbox_order() -> None:
    docs = main_docs()
    by_id = sorted(docs["inbox.json"]["candidates"], key=lambda c: str(c.get("id")))
    latest = _new({**docs, "inbox.json": {"candidates": by_id}})["latest_signals"]
    assert [s["name"] for s in latest] == ["Invented Quillon", "Invented Tamworth Optics", "Invented Ashby Motion"]
    assert latest[0] == {"name": "Invented Quillon", "source": "invented-feed-a"}


def test_one_clock_decides_the_week_boundary() -> None:
    later = NOW + timedelta(days=1)  # week_ago moves from 2026-11-06 to 11-07
    body = _new(main_docs(), later)
    assert body["progress"]["found"] == 2  # Ovenden (11-06) drops out
    assert body["progress"]["sent_omar"] == 3  # Vellacott (11-06) drops out
    assert body["progress"]["people_added"] == 2  # p-1 (11-06) drops out
    assert body["weekday"] == "Saturday" and body["date"] == "2026-11-14"
    # the operator status uses ``now``: a prepared case 14 days old turns STALE (refreshing), still the prepared case
    stale = datetime(2026, 11, 24, 10, 0, 1)
    juniper = _with_signals("Invented Juniper Grid")
    prio = view(inputs_from_docs(juniper, stale.date(), stale), stale.date(), stale)["priority"]
    assert prio["op"]["status"] == "REFRESHING CASE" and prio["op"]["source"] == "prepared case"
    fresh = view(inputs_from_docs(juniper, NOW.date(), NOW), NOW.date(), NOW)["priority"]
    assert fresh["op"]["status"] == "READY FOR MOHAMED"


def test_the_adapter_reads_like_the_old_loaders() -> None:
    empty = inputs_from_docs({}, NOW.date(), NOW)
    assert empty == HomeInputs()
    assert inputs_from_docs({"real_data.json": UNREADABLE}, NOW.date(), NOW).signals == []  # no startups
    assert inputs_from_docs({"real_data.json": {"week": ""}}, NOW.date(), NOW).signals == []
    assert inputs_from_docs({"real_data.json": {"signals": {"a": {"company": "X"}}}}, NOW.date(), NOW).signals == [
        {"company": "X"}]  # fmt: skip
    for doc in ("people.json", "events.json", "inbox.json"):  # not tolerant: the old route answered 500
        with pytest.raises(ValueError):
            inputs_from_docs({doc: UNREADABLE}, NOW.date(), NOW)
    with pytest.raises(KeyError):
        inputs_from_docs({"events.json": {"leads": []}}, NOW.date(), NOW)
    tolerant = inputs_from_docs({"case_prep/cases.json": UNREADABLE, "event_sources.json": UNREADABLE}, NOW.date(), NOW)
    assert tolerant.operator.cases == {} and tolerant.events.documents == {}
    assert view(empty, date(2026, 11, 15), NOW)["weekday"] == "Sunday"  # ``today`` is the request date argument
