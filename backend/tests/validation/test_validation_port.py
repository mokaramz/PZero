"""Review 027a, offline: the catalog is the old text cut by script, the port carries only the old literals, and the pure
Validation read side matches the OLD code's goldens (``oracle_validation.json``, ``python -m
projectzero.ops.parity_validation goldens``), key order included, with the declared (a), (c) and (d) normalised
(review 028a closed (b): the News panel and the packet's News sections are the News port's). Also: reads
never write, the snapshot last-row rule and the 60-row window, the per-list 30-row windows applied after retractions
over the FULL logs, the order-sensitive points, the adapter's tolerance and decision (f)."""

from __future__ import annotations

import ast
import copy
import dataclasses
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from projectzero.news import base_from_docs
from projectzero.ops.parity_ranking import OLD_REPO
from projectzero.ops.parity_validation import CLOCK, SETS, compare_goldens, jl, main_docs, snap
from projectzero.validation import (
    ValidationInputs,
    build,
    candidate_record,
    catalog,
    core,
    inputs_from_docs,
    packet,
    routing,
    scout_packet,
    view,
)

GOLDEN: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1" / "oracle_validation.json").read_text(
        encoding="utf-8"
    )
)
OLD = OLD_REPO / "backend" / "src" / "projectzero"
VALIDATION = OLD / "services" / "validation.py"
COMPRESSOR = OLD / "services" / "compressor.py"
TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 10, 0)
TOP = {VALIDATION: ["OUTCOMES", "AUDITS", "SNAPSHOTS", "SCOUT_LOG", "MIN_N", "POSITIVE_KINDS", "NEGATIVE_KINDS",
                    "BENCHMARK_KINDS", "KINDS", "LEAD_KINDS", "REAL_WORLD_STRONG", "MISS_REASONS", "FP_CAUSES",
                    "EVIDENCE_CLASS", "STAGES", "STAGE_LABEL", "MISS_TYPES", "VALUE_WEIGHTS", "SMOOTH",
                    "BENCHMARK_KINDS_ALL", "_NAME_COLS", "_DATE_COLS"],
       COMPRESSOR: ["STATES"]}  # fmt: skip
PAYLOAD_KEYS = ["date", "headline", "sources", "conversion", "stage_labels", "lead_times", "strength", "horizon",
                "calibration", "patterns", "misses", "false_positive_audits", "false_positive_watch", "outcomes", "scout",
                "snapshots", "measurement", "benchmarks", "news", "verification_calibration", "data_issues", "cost",
                "routing", "native_bridge", "vocab"]  # fmt: skip


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
        ns: dict[str, Any] = {}
        exec(compile(ast.Module(body=list(picked), type_ignores=[]), str(path), "exec"), ns)  # the old values
        for name in names:
            assert getattr(catalog, name) == ns[name], name
    defined = []
    for n in ast.parse(Path(catalog.__file__ or "").read_text(encoding="utf-8")).body:
        target = n.target if isinstance(n, ast.AnnAssign) else n.targets[0] if isinstance(n, ast.Assign) else None
        if isinstance(target, ast.Name):
            defined.append(target.id)
    assert defined == [*TOP[VALIDATION], *TOP[COMPRESSOR]]
    assert list(catalog.KINDS) == [*catalog.POSITIVE_KINDS, *catalog.NEGATIVE_KINDS, *catalog.BENCHMARK_KINDS]


def _literals(path: Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_port_carries_the_old_literals_unchanged() -> None:
    old = _literals(VALIDATION) | _literals(COMPRESSOR) | _literals(OLD / "services" / "news.py")
    old |= _literals(OLD / "services" / "source_network.py") | _literals(OLD / "inference" / "ledger.py")  # TS_FORMAT
    # decisions (c) and (d): the deferred panels' visible reasons and keys
    allowed = {
        core: {core.NATIVE_BRIDGE_REASON, "available", "reason"},
        packet: {packet.SOURCE_NETWORK_REASON, "not available: "},
        routing: set(),
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
    main = sets["main"]["view"]["body"]
    assert list(main) == PAYLOAD_KEYS
    # (a) the old view appended today's point (a stored row dated today in the MIDDLE does not stop it) ...
    assert len(sets["main"]["appended"]) == 1 and main["snapshots"][-1]["date"] == "2026-11-12"
    assert main["snapshots"][-1]["at"] == CLOCK and len(main["snapshots"]) == 60
    assert [r["date"] for r in main["snapshots"]].count("2026-11-12") == 2  # no duplicate suppressed elsewhere
    # ... but not when the LAST stored row is today's
    assert sets["today"]["appended"] == [] and len(sets["today"]["view"]["body"]["snapshots"]) == 4
    # a log without a final newline: the old append joined its last line, both rows are lost
    assert [r["date"] for r in sets["torn"]["view"]["body"]["snapshots"]] == ["2026-11-09", "2026-11-10"]
    # the 30-row windows, each after its own filtering; the retractions lie outside the raw tails
    assert len(main["outcomes"]) == len(main["misses"]) == len(main["false_positive_audits"]) == 30
    assert "oc-002" not in {o["id"] for o in main["outcomes"]} and main["misses"][0]["id"] == "au-m07"
    assert main["false_positive_audits"][0]["id"] == "au-f06"
    assert main["scout"]["cycles"] == ["cycle-010", "c-9", "cycle-002", "cycle-777"]  # the archive key order
    assert main["patterns"] and main["routing"] is not None
    # review 028a: the old News panel ran (its GET-time seeding in memory) over the same entities
    assert (
        main["news"]["available"] is True and main["news"]["reviewed"] == 10 and main["news"]["historical_cases"] == 1
    )
    assert main["news"]["preventable_misses"] == 2 and sets["broken"]["view"]["body"]["news"] == {"available": False}
    assert sets["main"]["news_saved"]["seeded"] == ["nw-case-1"] and sets["empty"]["news_saved"] is None
    assert main["native_bridge"] is None and len(main["calibration"]["disagreements"]) == 20
    assert sets["broken"]["build"]["body"]["issues"] == ["news observations could not be read"]
    assert sets["broken"]["view"]["body"]["routing"] is None
    packet_text = sets["main"]["packets"][""]["body"]["text"]
    assert "- none in probation yet" in packet_text and "source learning: unavailable" in packet_text  # (c)
    assert "- HISTORICAL: Invented Case Robotics" in packet_text and "Scout use: early-signal source" in packet_text


def _main() -> ValidationInputs:
    return inputs_from_docs(main_docs(), TODAY)


def test_reads_never_write_and_answer_the_deferred_panels_with_a_reason() -> None:
    reason = "The source network arrives with its port"
    docs = main_docs()
    before = copy.deepcopy(docs)
    inputs = inputs_from_docs(docs, TODAY)
    frozen = copy.deepcopy(inputs)
    v = view(inputs, TODAY, NOW)
    p = scout_packet(inputs, "", TODAY, NOW)
    build(inputs, TODAY)
    assert inputs == frozen and docs == before
    assert list(v) == PAYLOAD_KEYS
    assert v["news"]["available"] is True  # review 028a: the News port, over this view's entities
    assert v["native_bridge"]["available"] is False and v["native_bridge"]["reason"]
    assert p["text"].count(f"- not available: {reason}") == 1  # the source network only
    assert f"source learning: not available: {reason}" in p["text"]
    assert v["stage_labels"] is not catalog.STAGE_LABEL and v["vocab"]["kinds"] is not catalog.KINDS
    # the same inputs at the same clock: the same answer (the daily point is computed, never stored)
    assert view(inputs, TODAY, NOW) == v


def test_the_snapshot_compares_the_last_row_only_and_keeps_the_last_60() -> None:
    def series(rows: list[Any], tail: str = "") -> list[dict[str, Any]]:
        inputs = inputs_from_docs({"validation/snapshots.jsonl": jl(rows) + tail}, TODAY)
        out: list[dict[str, Any]] = view(inputs, TODAY, NOW)["snapshots"]
        return out

    assert [r["date"] for r in series([snap("2026-11-12", 1), snap("2026-11-11", 2)])][-1] == "2026-11-12"
    assert len(series([snap("2026-11-12", 1), snap("2026-11-11", 2)])) == 3  # appended despite the earlier today row
    assert len(series([snap("2026-11-11", 1), snap("2026-11-12", 2)])) == 2  # the last row is today's: no append
    rows = [snap(f"2026-10-{d:02d}", d) for d in range(1, 32)] * 2
    got = series(rows)
    assert len(got) == 60 and got[-1]["at"] == "2026-11-12T10:00:00" and got[0] == snap("2026-10-04", 4)
    appended = got[-1]
    assert list(appended) == sorted(appended)  # written with sort_keys and read back, as the old file was
    assert series([snap("2026-11-10", 1)], tail=json.dumps(snap("2026-11-11", 2))) == [snap("2026-11-10", 1)]
    aware = datetime(2026, 11, 12, 9, 30, tzinfo=UTC)  # the request instant, as Berlin wall time
    inputs = inputs_from_docs({}, TODAY)
    assert view(inputs, TODAY, aware)["snapshots"][-1]["at"] == "2026-11-12T10:30:00"


def test_the_windows_are_cut_after_retractions_over_the_full_logs() -> None:
    inputs = _main()
    v = view(inputs, TODAY, NOW)
    lines = inputs.outcomes_log.splitlines()
    assert any('"oc-002"' in ln for ln in lines[:-30]) and '"retracts": "oc-002"' in lines[-1]
    tail_only = dataclasses.replace(inputs, outcomes_log="\n".join(lines[-30:]) + "\n")
    assert view(tail_only, TODAY, NOW)["outcomes"] != v["outcomes"]  # the raw tail alone is not the old answer
    assert [o["id"] for o in v["outcomes"]][-1] == "oc-050" and "oc-010" not in {o["id"] for o in v["outcomes"]}
    audits = inputs.audits_log.splitlines()
    assert any('"au-m01"' in ln for ln in audits[:-30])
    assert "au-m01" not in {a["id"] for a in v["misses"]} and "au-f02" not in {
        a["id"] for a in v["false_positive_audits"]
    }
    assert v["headline"]["never_seen"] == 42  # the aggregates read everything: 34 live misses + 8 strong never seen


def test_the_archive_key_orders_decide_the_latest_cycle_and_the_news_tie() -> None:
    inputs = _main()
    cycles = dict(reversed(list(inputs.scout_cycles.items())))
    flipped = view(dataclasses.replace(inputs, scout_cycles=cycles), TODAY, NOW)["scout"]["cycles"]
    assert flipped == ["cycle-002", "c-9", "cycle-010", "cycle-777"]
    obs = core.observations(inputs.news)
    assert obs["invented batch co 4"]["source"] == "Invented Daily nw-9"  # the first event of the date tie
    news = dict(inputs.news)
    news["events"] = dict(reversed(list(news["events"].items())))
    assert core.observations(news)["invented batch co 4"]["source"] == "Invented Daily nw-1"


def test_the_first_seen_tie_keeps_the_earlier_candidate() -> None:
    e = build(_main(), TODAY)[0]["invented alpha robotics"]
    assert e["candidate_ids"] == ["a1", "a2"] and e["first_tier"] == "pre_company" and e["country"] == "DE"
    assert e["first_seen"] == "2026-10-28"  # the Scout Intake date is earlier
    assert e["observed_news"]["date_basis"] == "news publication"  # News (2026-11-06) is earlier than the also-seen


def test_the_adapter_reads_like_the_old_loaders() -> None:
    empty = inputs_from_docs({}, TODAY)
    news = base_from_docs({})  # review 028a: the News inputs (the packaged curated cases by default)
    assert empty == ValidationInputs(inbox=[], proposals={}, signals=[], scout_items=None, news_inputs=news)
    assert news.cases and news.cases[0][0] == "robco.json" and news.entities is None
    assert view(empty, TODAY, NOW)["snapshots"][-1]["date"] == "2026-11-12"
    crlf = inputs_from_docs(
        {"validation/snapshots.jsonl": b'{"date": "2026-11-12"}\r\n', "inference_ledger.jsonl": b"\xff\xfe"}, TODAY
    )
    assert crlf.snapshots_log == '{"date": "2026-11-12"}\n' and crlf.inference_ledger == []
    led = inputs_from_docs({"inference_ledger.jsonl": '{"ts": "2026-11-01T00:00:00", "usd": 1}\nnope\n[1]\n'}, TODAY)
    assert led.inference_ledger == [{"ts": "2026-11-01T00:00:00", "usd": 1}, [1]]  # the old ``r.get`` raised on [1]
    with pytest.raises(AttributeError):
        view(led, TODAY, NOW)
    broken = inputs_from_docs(SETS["broken"](), TODAY)
    assert build(broken, TODAY)[1] == ["news observations could not be read"]
    assert view(broken, TODAY, NOW)["routing"] is None


def test_candidates_created_after_the_import_use_their_berlin_first_seen_and_intake_tier() -> None:
    legacy = {"id": "c-1", "name": "Invented Old Co", "status": "watch", "first_seen_at": datetime(2026, 1, 1, tzinfo=UTC),
              "legacy": {"id": "c-1", "name": "Invented Old Co", "decision": "new", "discovery_tier": "grant",
                         "source_id": "s-lab", "first_seen": "2025-12-30"}}  # fmt: skip
    rec = candidate_record(legacy)
    assert rec["first_seen"] == "2025-12-30" and rec["discovery_tier"] == "grant" and rec["decision"] == "watch"
    record = {"id": "live-9", "name": "Invented Late Lead", "source": "Manual", "source_id": "live-manual",
              "discovery_tier": "manual", "decision": "new", "all_source_ids": ["live-manual"]}  # fmt: skip
    tagged = {"id": "live-9", "name": "Invented Late Lead", "status": "new", "attrs": {"tagging": {"version": 1, "record": record}},
              "first_seen_at": datetime(2026, 11, 9, 23, 30, tzinfo=UTC)}  # fmt: skip
    rec = candidate_record(tagged)
    assert rec["first_seen"] == "2026-11-10" and rec["discovery_tier"] == "manual"  # the BERLIN calendar date
    partial = {
        "id": "p-1",
        "name": "Invented Partial",
        "status": "new",
        "first_seen_at": datetime(2026, 11, 1, 12, tzinfo=UTC),
    }
    rec = candidate_record(partial)
    assert rec["first_seen"] == "2026-11-01" and "discovery_tier" not in rec
    assert candidate_record({"id": "p-2", "name": "Invented No Date", "status": "new"})["first_seen"] == ""
