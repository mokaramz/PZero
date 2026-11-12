"""Review 025, offline: the catalog is the old text cut by script, the port carries only the old literals, and the pure
Map matches the OLD code's goldens (``oracle_map.json``, ``python -m projectzero.ops.parity_map goldens``), key order
included. Also: acceptance 32 (convergence), reads never write, and the order-sensitive points."""

from __future__ import annotations

import ast
import contextlib
import copy
import dataclasses
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from projectzero.ecosystems.catalog import ORGS
from projectzero.events import engine
from projectzero.map import catalog, intel, pins
from projectzero.map.inputs_model import MapInputs, inputs_from_docs
from projectzero.ops.parity_map import CLOCK, INJECT, SETS, compare_goldens, expand, inputs_of, munich_docs
from projectzero.ops.parity_ranking import OLD_REPO

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1" / "oracle_map.json").read_text(encoding="utf-8")
)
OLD = OLD_REPO / "backend" / "src" / "projectzero"
GEO = OLD / "services" / "geo_intel.py"
HOME = OLD / "api" / "routers" / "home.py"
TODAY = date(2026, 11, 12)
TOP = {GEO: ["ACTIVITY_DAYS", "MAX_PER_SOURCE", "EVENT_DAYS", "STATES", "FAMILY_LABEL", "COVERAGE_LABEL", "COV_WORD",
             "NOTE", "COORDS", "SUBLOCAL", "_UI_TEXT", "_ABROAD", "_SCOUT_FAMILY", "_SRC_FAMILY", "_NEWS_FAMILY",
             "HOME_DEFAULT"],
       HOME: ["DEFAULT_HOME_BASE", "OPERATOR_ID"]}  # fmt: skip
INNER = {"LEGEND": ("view", "legend", 0), "WHERE_TO_GO_EMPTY_NOTE": ("where_to_go", "note", 0),
         "WHERE_TO_GO_NOTE": ("where_to_go", "note", 1), "BRING_BACK": ("sourcing_day", "bring_back", 0),
         "PLAN_NOTE": ("sourcing_day", "note", 0)}  # fmt: skip


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
        exec(compile(ast.Module(body=list(picked), type_ignores=[]), str(path), "exec"), ns)  # the old values
        for name in names:
            assert getattr(catalog, name) == ns[name], name
    fns = {n.name: n for n in ast.parse(GEO.read_text(encoding="utf-8")).body if isinstance(n, ast.FunctionDef)}
    for name, (fn, key, i) in INNER.items():
        values = sorted((v for d in ast.walk(fns[fn]) if isinstance(d, ast.Dict)
                         for k, v in zip(d.keys, d.values, strict=True)
                         if isinstance(k, ast.Constant) and k.value == key),
                        key=lambda v: (v.lineno, v.col_offset))  # fmt: skip
        assert getattr(catalog, name) == ast.literal_eval(values[i]), name
    defined = []
    for n in ast.parse(Path(catalog.__file__ or "").read_text(encoding="utf-8")).body:
        target = n.target if isinstance(n, ast.AnnAssign) else n.targets[0] if isinstance(n, ast.Assign) else None
        if isinstance(target, ast.Name):
            defined.append(target.id)
    assert defined == [*TOP[GEO], *INNER, *TOP[HOME]]


def _literals(path: Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_port_carries_the_old_literals_unchanged() -> None:
    old = _literals(GEO) | _literals(HOME) | _literals(OLD / "domain" / "events.py")
    old |= _literals(OLD / "domain" / "scout_intake.py")  # ``scout_cycles``
    # the default ``built_at`` time and decision (d)'s Scout item link; decision (c)
    allowed = {intel: {"T00:00:00", "/scout-intake?", "item"}, pins: {"new_signals"}}
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
    for name, spec in SETS.items():
        # serialized without sort_keys: the documents' insertion order is part of the input
        assert json.dumps(GOLDEN["sets"][name]["docs"]) == json.dumps(json.loads(json.dumps(spec["docs"]()))), name


def test_the_pure_map_matches_the_old_code_including_key_order() -> None:
    assert compare_goldens(GOLDEN) == []


def test_the_goldens_cover_the_old_acceptance_cases() -> None:
    m = expand(GOLDEN["sets"]["munich"]["expected"])
    v = m["intel"]["body"]
    assert v["where_to_go"]["ranked"][0]["city"] == "Munich" and v["built_at"] == CLOCK and v["build_s"] == 0.0
    d = m["ecosystem"]["Munich"]["body"]
    assert d["coverage"]["families"]["Founder formation"] == "NOT COVERED"  # 28: the weakness stays visible
    assert {"Invented Kinetiq Robotics", "Invented Graspwerk", "Invented Neuron Hands"} <= {
        c["name"] for c in d["companies"]
    }
    assert d["next_best_action"].startswith("Decide on Invented Isar Pitch Night")
    plan = next(r["answer"]["body"] for r in m["sourcing_day"] if r["body"] == {"city": "Munich", "date": "2026-11-19"})
    assert plan["weekday"] == "Thursday" and any(s["kind"] == "event" and s["time"] == "18:00" for s in plan["stops"])
    assert m["map_wrote"] is True  # the OLD read wrote real_data.json; the port does not (decision a)
    states = {e["city"]: e["state"] for e in expand(GOLDEN["sets"]["blind"]["expected"])["intel"]["body"]["ecosystems"]}
    assert states["Tallinn"] == "UNDER-COVERED" and states["Hamburg"] == "LOW SIGNAL"  # 29
    noisy = expand(GOLDEN["sets"]["noisy"]["expected"])["intel"]["body"]["ecosystems"]
    order = [e["city"] for e in noisy]
    berlin = next(e for e in noisy if e["city"] == "Berlin")
    assert (
        order.index("Karlsruhe") < order.index("Berlin") and berlin["late"] == 50 and berlin["state"] == "NORMAL"
    )  # 30
    w = expand(GOLDEN["sets"]["watchers"]["expected"])["ecosystem"]["Munich"]["body"]
    assert [c["name"] for c in w["companies"]] == ["Invented Kinetiq Robotics", "Invented Rejected Robotics"]
    assert w["hidden_non_companies"] == 6 and "Invented Pitch Night" in [e["label"] for e in w["events"]]
    refusals = {r["answer"]["body"]["error"] for s in GOLDEN["sets"] for r in expand(GOLDEN["sets"][s]["expected"])["sourcing_day"]
                if r["answer"].get("code") == 400}  # fmt: skip
    assert {
        "date as YYYY-MM-DD",
        "unknown or unplaced ecosystem: Atlantis",
        "unknown or unplaced ecosystem: ",
    } <= refusals


def test_32_duplicate_media_is_not_convergence_independent_families_are() -> None:
    dup = [
        {"kind": "news", "id": "nw-1", "entity": "X", "family": "news", "early": False, "late": True, "recent": True}
    ] * 5
    assert not intel.convergence(dup)["converging"]
    five_articles = [{"kind": "news", "id": "nw-1", "entity": "X", "family": "news", "recent": True}] * 5
    assert not intel.convergence(five_articles)["converging"]
    mixed = [
        {"kind": "company", "id": "a", "entity": "Lab A", "family": "research", "recent": True, "source": "s1"},
        {"kind": "company", "id": "b", "entity": "Grantee B", "family": "grants", "recent": True, "source": "s2"},
        {"kind": "scout", "id": "c", "entity": "Scout C", "family": "scout00", "recent": True, "source": "scout"},
        {"kind": "person", "id": "d", "entity": "Founder D", "family": "founder_formation", "recent": True},
        {"kind": "event", "id": "e", "entity": "Demo day", "family": "event", "recent": True},
    ]
    c = intel.convergence(mixed)
    assert c["converging"] and len(c["families"]) == 5 and c["signals"] == 5
    one_list = [{"kind": "company", "id": f"x{i}", "entity": f"E{i}", "family": "research", "recent": True,
                 "source": "s1"} for i in range(40)]  # fmt: skip
    assert intel.convergence(one_list)["signals"] == 3 and not intel.convergence(one_list)["converging"]


def _munich() -> MapInputs:
    return inputs_of(munich_docs(), INJECT, TODAY)


def test_reads_never_write_and_pins_are_geocoded_in_memory() -> None:
    docs = munich_docs()
    before_docs = copy.deepcopy(docs)
    inputs = inputs_of(docs, INJECT, TODAY)
    before = copy.deepcopy(inputs)
    alpine = next(s for s in inputs.signals if isinstance(s, dict) and s.get("company") == "Invented Alpine Sensors")
    assert "lat" not in alpine  # placeable, no coordinates
    m = pins.map_view(inputs, TODAY)
    pin = next(p for p in m["startups"] if p["company"] == "Invented Alpine Sensors")
    assert (pin["lat"], pin["lng"]) == engine.GAZETTEER["Munich"][:2]
    intel.view(inputs, TODAY)
    for city in ("Munich", "Atlantis"):
        with contextlib.suppress(KeyError):
            intel.sourcing_day(inputs, city, "2026-11-19", TODAY)
    intel.search(inputs, "invented", TODAY)
    assert inputs == before and "lat" not in alpine and "data_warning" not in json.dumps(inputs.signals)
    assert docs == before_docs
    assert m["new_signals"] == 9 and m["orgs"] is not ORGS


def test_the_gazetteer_order_picks_the_pin_and_the_earliest_mention_picks_the_ecosystem() -> None:
    assert pins.geocode_location("Mannheim near Heidelberg") == engine.GAZETTEER["Heidelberg"][:2]  # dict order
    place = intel._Placer(intel._cities(_munich()))
    assert place.city("Mannheim near Heidelberg") == "Mannheim"  # the earliest mention
    assert place.city("TUM Garching / München") == "Munich" and place.city("Cambridge, MA, USA") == ""
    assert pins.geocode_location(None) is None and pins.geocode_location("Garching") is None


def test_the_news_key_order_decides_detail_news_and_the_theme_tie() -> None:
    inputs = _munich()
    d = intel.detail(inputs, "Munich", TODAY)
    assert [n["headline"][:12] for n in d["news"]][:2] == ["Munich robot", "Munich accel"]
    assert "2 news stories on robotics recently" in d["why_here"]  # robotics 2 / ai 2: the first seen wins
    flipped = dict(reversed(list(inputs.news_events.items())))
    d2 = intel.detail(dataclasses.replace(inputs, news_events=flipped), "Munich", TODAY)
    assert [n["headline"][:12] for n in d2["news"]][:2] == ["München: Inv", "Invented Gra"]
    assert "2 news stories on ai recently" in d2["why_here"]


def test_the_network_order_decides_the_source_candidates_cut() -> None:
    inputs = _munich()
    got = [c["name"] for c in intel.detail(inputs, "Munich", TODAY)["source_candidates"]]
    assert len(got) == 6 and got[0] == "Invented Munich founder meetup list"
    rev = intel.detail(dataclasses.replace(inputs, network=inputs.network[::-1]), "Munich", TODAY)["source_candidates"]
    assert rev[0]["name"] == "Invented seven" and len(rev) == 6


def test_the_collection_order_decides_search_results_first() -> None:
    inputs = _munich()
    assert intel.search(inputs, "invented", TODAY)[0]["label"] == "Invented Kinetiq Robotics"
    moved = dataclasses.replace(inputs, inbox=inputs.inbox[::-1])
    first = intel.search(moved, "invented", TODAY)[0]
    assert first["label"] == "Invented Heidelberg Bio" and first["city"] == "Heidelberg"
    assert intel.search(inputs, "a", TODAY) == [] and len(intel.search(inputs, "invented", TODAY)) == 20


def test_the_adapter_reads_like_the_old_loaders() -> None:
    empty = inputs_from_docs({}, TODAY)
    assert empty.inbox == [] and empty.scout_items == [] and empty.events == [] and empty.people == []
    assert empty.news_events == {} and empty.network == [] and empty.home_base is None
    assert len(empty.institutions) == 24 and empty.coverage_ecosystems and empty.coverage_all
    broken = inputs_from_docs(SETS["broken"]["docs"](), TODAY)
    assert broken.scout_items == [] and broken.news_events == {} and broken.people == [] and broken.events == []
    assert broken.declared_sources == [] and broken.coverage_all == []  # the old load_registry raised on a text source
    assert intel.view(broken, TODAY)["home"] == catalog.HOME_DEFAULT  # a text home base: Karlsruhe (geo) ...
    assert pins.map_view(broken, TODAY)["home"] == "Karlsruhe"  # ... and as stored (pins), as before
    trig = inputs_from_docs({"watch/triggers.jsonl": munich_docs()["watch/triggers.jsonl"]}, TODAY).watch_open
    assert [t["id"] for t in trig] == ["t1", "t3"]
