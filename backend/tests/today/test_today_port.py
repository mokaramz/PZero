"""Review 030a, offline: the catalog is the old text cut by script, the port carries only the old literals, and the pure
Today view matches the OLD code's goldens (``oracle_today.json``, ``python -m projectzero.ops.parity_today goldens``),
key order included, served and uncut, with the declared (c) and (f) normalised. Also: reads never write, the payload
and action key order, the titles the page parses, the dropped sections, the deferrals, the snapshot note over time,
the inbox order of the triage, the one clock and the adapter's tolerance."""

from __future__ import annotations

import ast
import copy
import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from projectzero.conviction.operator import OperatorInputs
from projectzero.ops.parity_ranking import OLD_REPO
from projectzero.ops.parity_today import (
    CLOCK,
    EXPIRED_CLOCK,
    WORLDS,
    as_read,
    compare_goldens,
    main_docs,
    read_golden,
)
from projectzero.today import UNREADABLE, TodayInputs, cases, catalog, compressor, core, inputs_from_docs, view

GOLDEN: dict[str, Any] = read_golden()
OLD = OLD_REPO / "backend" / "src" / "projectzero"
TODAY_PY = OLD / "services" / "today.py"
COMPRESSOR_PY = OLD / "services" / "compressor.py"
CASE_PREP_PY = OLD / "services" / "case_prep.py"
TOP = {TODAY_PY: ["MAX_ACTIONS", "TYPES", "_CLEAR_CONFLICT"], COMPRESSOR_PY: ["STATES", "LABEL", "DEFAULTS", "_job"]}
NOW = datetime.fromisoformat(CLOCK)
PAYLOAD_KEYS = ["date", "actions", "more", "considered", "exceptions", "machine_working", "triage", "rules", "snapshot"]
ACTION_KEYS = ["type", "title", "why", "next_step", "link", "urgency", "evidence", "subject", "conflict",
               "contact_appropriate"]  # fmt: skip
TRIAGE_KEYS = ["at", "total", "counts", "needs_mohamed", "calibration", "limit", "queued_beyond_budget", "resurfaced",
               "labels"]  # fmt: skip


def _hint_free(text: str) -> str:
    return re.sub(r"^(\w+): [^=\n]+ = ", r"\1 = ", text, flags=re.M)


def _served(name: str, uncut: bool = False) -> dict[str, Any]:
    e = GOLDEN["worlds"][name]["expected"]
    body: dict[str, Any] = (e["uncut"] if uncut else e)["ok"]
    return body


def _new(docs: dict[str, Any], clock: str = CLOCK) -> dict[str, Any]:
    now = datetime.fromisoformat(clock)
    return view(inputs_from_docs(as_read(docs), now.date(), now), now.date(), now)


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
        ns: dict[str, Any] = {"Any": Any}
        exec(compile(ast.Module(body=list(picked), type_ignores=[]), str(path), "exec"), ns)  # the old values
        for name in names:
            assert getattr(catalog, name) == ns[name], name


def _literals(path: Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_port_carries_the_old_literals_unchanged() -> None:
    old = _literals(TODAY_PY) | _literals(COMPRESSOR_PY) | _literals(CASE_PREP_PY)
    # decisions (d), (e) and (f): the note, the logged deferrals, the snapshot keys; the unreadable inputs' messages
    allowed = {
        core: {core.SNAPSHOT_NOTE, core.VERIFICATION_DEFERRED, core.SOURCE_DEFERRED, core.JOBS_DEFERRED, "snapshot",
               "triage_at", "cases_prepared_at", "today: %s", "today: %s (%s)",
               "the Conviction pipeline could not be read", "founder_calls.json could not be read",
               "the triage view could not be computed"},
        compressor: set(),
        cases: set(),
    }  # fmt: skip
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
    assert set(GOLDEN["worlds"]) == set(WORLDS)
    for name, (fn, clock) in WORLDS.items():
        w = GOLDEN["worlds"][name]
        assert w["clock"] == clock
        # serialized without sort_keys: the documents' insertion order is part of the input
        assert json.dumps(w["docs"]) == json.dumps(json.loads(json.dumps(fn()))), name


def test_the_pure_view_matches_the_old_code_served_and_uncut_including_key_order() -> None:
    assert compare_goldens(GOLDEN) == []


def test_the_goldens_cover_the_planned_cases() -> None:
    uncut = [a for name in GOLDEN["worlds"] if "ok" in GOLDEN["worlds"][name]["expected"]["uncut"]
             for a in _served(name, uncut=True)["actions"]]  # fmt: skip
    seen = {(a["type"], a["urgency"]) for a in uncut}
    assert {t for t, _u in seen} == set(catalog.TYPES) - {"NATIVE_INTEL", "SCOUT00_CYCLE"}  # decision (c)
    for branch in [("CONTACT_FOUNDER", "high"), ("ASK_OMAR_CONFLICT", "high"), ("ASK_OMAR_CONFLICT", "medium"),
                   ("PREPARE_FOUNDER_CALL", "high"), ("PREPARE_FOUNDER_CALL", "medium"),
                   ("REVIEW_VERIFICATION", "medium"), ("EVENT_ACTION", "high"), ("EVENT_ACTION", "medium"),
                   ("TRIAGE_REVIEW", "medium"), ("TRIAGE_REVIEW", "low"), ("WATCH_TRIGGER", "high"),
                   ("WATCH_TRIGGER", "low"), ("CASE_READY", "high"), ("CASE_READY", "medium"),
                   ("CASE_READY", "low")]:  # fmt: skip
        assert branch in seen, branch
    titles = [a["title"] for a in uncut]
    for start in ("Contact the founders: ", "Follow up once: ", "Prepare a founder call: ", "Follow up: ",
                  "Ask Omar about ", "Verify ", "Decide on "):  # fmt: skip
        assert any(t.startswith(start) for t in titles), start
    assert any("new candidate(s) touch the Project A portfolio" in t for t in titles)
    main = _served("main")
    assert main["more"] > 0 and len(main["actions"]) == catalog.MAX_ACTIONS
    assert [x["key"] for x in main["exceptions"]] == ["judgment", "founder_call", "omar", "watch", "event", "triage"]
    assert GOLDEN["worlds"]["main"]["expected"]["saves"] == 1  # the old IMQ save, in memory
    assert "1 possible portfolio conflict for Omars" in [x["text"] for x in _served("quiet")["exceptions"]]  # (h)
    unavailable = "temporarily unavailable — the rest of Today is complete"
    assert _served("failing")["considered"]["watch"] == unavailable
    assert _served("failing")["considered"]["triage"] == unavailable and _served("failing")["triage"] is None
    assert _served("norun")["triage"] is None and _served("norun")["actions"][0]["type"] == "TRIAGE_REVIEW"
    broken = _served("broken")["considered"]
    assert broken["pipeline"] == broken["calls"] == broken["cases"] == unavailable
    quiet = [a["type"] for a in _served("quiet", uncut=True)["actions"]]
    assert quiet[-3:] == ["TRIAGE_REVIEW", "WATCH_TRIGGER", "CASE_READY"]  # the rank-8 tie keeps the section order
    held = {a["subject"] for a in _served("main", uncut=True)["actions"]}
    assert {"Invented Kestrel Defence", "Invented Mallow Sensors", "Invented Corvid Labs",
            "Invented Nettlecombe"}.isdisjoint(held)  # fmt: skip  # the human-outcome hold, contact states
    assert "Invented Vellacott" in held  # re-opened by later evidence


def test_after_the_last_case_expired_the_note_keeps_its_timestamps() -> None:
    main, expired = _new(main_docs()), _new(main_docs(), EXPIRED_CLOCK)
    assert "CASE_READY" in [a["type"] for a in _served("main", uncut=True)["actions"]]
    assert expired["considered"]["cases"] == 0
    assert [a for a in _served("expired", uncut=True)["actions"] if a["type"] == "CASE_READY"] == []
    assert expired["snapshot"] == main["snapshot"] == {
        "note": core.SNAPSHOT_NOTE, "triage_at": "2026-11-12T23:05:10", "cases_prepared_at": "2026-11-01T19:36:00"}  # fmt: skip
    assert expired["triage"] == main["triage"]
    assert [a for a in expired["actions"] if a["type"] == "TRIAGE_REVIEW"] == [
        a for a in main["actions"] if a["type"] == "TRIAGE_REVIEW"]  # fmt: skip
    juniper = [a["title"] for a in _served("expired", uncut=True)["actions"] if a["subject"] == "Invented Juniper Grid"]
    assert juniper == ["Verify Invented Juniper Grid (traction, funding)"]  # its chore is back, the case is stale


def test_the_payload_and_action_key_order_and_the_dropped_sections() -> None:
    body = _new(main_docs())
    assert list(body) == PAYLOAD_KEYS  # the old order, the declared snapshot last
    assert (
        list(body["considered"]) == list(core.SECTIONS) == ["pipeline", "calls", "events", "triage", "watch", "cases"]
    )
    assert all(list(a) == ACTION_KEYS for a in body["actions"])  # ``rank`` popped from the shown actions
    assert list(body["triage"]) == TRIAGE_KEYS and list(body["triage"]["counts"]) == list(catalog.STATES)
    assert [x["key"] for x in body["exceptions"]] == ["judgment", "founder_call", "omar", "watch", "event", "triage"]
    assert body["machine_working"] == ""  # no case is ever being prepared


def test_the_titles_the_page_parses_stay_byte_identical() -> None:
    actions = [a for name in ("main", "quiet") for a in _new(WORLDS[name][0]()).get("actions", [])]
    actions += [a for a in _served("main", uncut=True)["actions"]]
    event = re.compile(r"^Decide on (.+?) \((\d{4})-(\d{2})-(\d{2}),\s*([^)]+)\)$")
    for a in actions:
        if a["type"] == "EVENT_ACTION":
            assert event.match(a["title"]), a["title"]
        if a["type"] == "CASE_READY":
            assert re.match(r"Recommended next action:\s*([^—.]+)", a["why"]), a["why"]
        if a["type"] == "TRIAGE_REVIEW":
            assert re.match(r"^Triage:\s*", a["title"])
        if a["type"] == "ASK_OMAR_CONFLICT" and a["link"] == "/conviction":
            assert re.match(r"^Ask Manager about ", re.sub(r"\bOmar\b", "Manager", a["title"]))  # the page's asRole
    cases_ = [a["title"] for a in actions if a["type"] == "CASE_READY"]
    assert any(re.search(r"(\d+) human decision", t) for t in cases_)


def test_reads_never_write_and_the_deferrals_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    docs = main_docs()
    before = copy.deepcopy(docs)
    inputs = inputs_from_docs(docs, NOW.date(), NOW)
    snapshot = copy.deepcopy(inputs)
    with caplog.at_level(logging.INFO, logger="projectzero.today.core"):
        body = view(inputs, NOW.date(), NOW)
    assert docs == before and inputs == snapshot  # decision (a): nothing is written, not even in memory
    text = caplog.text
    assert core.VERIFICATION_DEFERRED in text and core.SOURCE_DEFERRED in text and core.JOBS_DEFERRED in text
    assert all(x["key"] not in ("source", "jobs") for x in body["exceptions"])  # decision (d)
    verify = [a for a in body["actions"] + [] if a["type"] == "REVIEW_VERIFICATION"]
    assert all(a["title"].startswith("Verify ") for a in verify)  # decision (e)


def test_the_triage_names_follow_the_inbox_order() -> None:
    docs = main_docs()
    inputs = inputs_from_docs(docs, NOW.date(), NOW)
    assert inputs.triage is not None
    inbox = [c["id"] for c in docs["inbox.json"]["candidates"]]
    assert list(inputs.triage) == [cid for cid in inbox if cid in inputs.triage]  # not sorted by id
    card = next(a for a in _new(docs)["actions"] + _served("main", uncut=True)["actions"]
                if a["type"] == "ASK_OMAR_CONFLICT" and a["link"] == "/deal-flow?filter=triage")  # fmt: skip
    assert card["subject"] == "Invented Rookwood, Invented Quillon"  # c-205 before c-101: inbox order
    by_id = TodayInputs(**{**inputs.__dict__, "triage": dict(sorted(inputs.triage.items()))})
    reordered = view(by_id, NOW.date(), NOW)
    moved = [a for a in reordered["actions"] if a["type"] == "ASK_OMAR_CONFLICT" and a["link"].startswith("/deal")]
    assert all(a["subject"] == "Invented Quillon, Invented Rookwood" for a in moved)  # why the order is an input


def test_one_clock_decides_the_case_freshness_and_the_contact_days() -> None:
    docs = main_docs()
    edge = datetime(2026, 11, 15, 19, 36)  # exactly 14 days after the newest case: still fresh (strict ``>``)
    body = view(inputs_from_docs(docs, edge.date(), edge), edge.date(), edge)
    assert body["considered"]["cases"] == 1  # Juniper only: Ovenden (10-31) and Pellow (10-30) are already stale
    later = datetime(2026, 11, 15, 19, 37)
    assert view(inputs_from_docs(docs, later.date(), later), later.date(), later)["considered"]["cases"] == 0
    assert body["date"] == "2026-11-15"


def test_the_compressor_settings_and_the_idle_job() -> None:
    assert compressor.settings(None) == catalog.DEFAULTS
    assert compressor.settings(["not", "an", "object"]) == catalog.DEFAULTS
    over = compressor.settings({"attention_budget": {"human_review_daily_limit": 3, "unknown": 1}})
    assert over["human_review_daily_limit"] == 3 and "unknown" not in over
    s = compressor.summary({"at": "x", "routes": {"a": {"state": "NEEDS_MOHAMED", "priority": None}}}, {"a"}, {})
    assert s["job"] == catalog._job and s["job"]["running"] is False
    assert s["today"] == [{"candidate_id": "a", "name": None, "state": "NEEDS_MOHAMED", "reason": None,
                           "priority": None, "machine_proposal": None, "resurfaced": None}]  # fmt: skip
    assert compressor.summary({"routes": {"a": {"state": "NEEDS_MOHAMED"}}}, set(), {})["total"] == 0  # decided
    with pytest.raises(TypeError):
        compressor.summary(["not", "a", "document"], set(), {})


def test_the_adapter_reads_like_the_old_loaders() -> None:
    empty = inputs_from_docs({}, NOW.date(), NOW)
    assert empty.signals == [] and empty.triage == {} and empty.live_ids == frozenset()
    assert empty.founder_calls is None and empty.queue_routing == {}
    broken = inputs_from_docs({"real_data.json": UNREADABLE, "founder_calls.json": UNREADABLE}, NOW.date(), NOW)
    assert broken.signals is None and broken.founder_calls is UNREADABLE
    assert broken.operator.founder_calls == {}  # the tolerant reads behind the hold
    body = view(broken, NOW.date(), NOW)
    assert body["considered"]["pipeline"] == body["considered"]["calls"] == body["considered"]["cases"]
    assert isinstance(body["considered"]["pipeline"], str)
    assert (
        cases.newest_prepared_at(OperatorInputs(cases={"a": {"prepared_at": "2026-10-01"}, "b": "junk"}))
        == "2026-10-01"
    )
    assert cases.newest_prepared_at(OperatorInputs()) is None
    assert date.fromisoformat(body["date"]) == NOW.date()
