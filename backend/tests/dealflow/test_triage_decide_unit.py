"""Review 035a: the pure parts of the machine-triage decisions (no database) and the stored oracle golden."""

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

import pytest

from projectzero.dealflow.triage import decide as td
from projectzero.dealflow.triage import log, view
from projectzero.network.view import BERLIN
from projectzero.ops import parity_triage_decide as ptd


def test_the_old_checks_run_in_their_order() -> None:
    with pytest.raises(td.TriageError, match=r"^verdict must be one of KEEP, RESEARCH, WATCH, REJECT$"):
        td.parse_decide({"id": "x", "verdict": "maybe", "mode": "later"})  # the verdict first
    with pytest.raises(td.TriageError, match=r"^mode must be accept or override$"):
        td.parse_decide({"id": "x", "verdict": "keep", "mode": "later"})
    req = td.parse_decide({"id": 7, "verdict": "watch", "note": "", "expected_status": "new"})
    assert (req.candidate_id, req.verdict, req.mode, req.note, req.notes, req.expected_status) == (
        "7", "WATCH", "accept", "", None, "new")  # fmt: skip
    assert td.parse_decide({"verdict": "KEEP", "note": "Hi"}).notes == "Hi"
    assert td.parse_decide({"verdict": "KEEP"}).candidate_id == ""
    with pytest.raises(td.TriageError, match=r"^accept means taking the machine proposal \(REJECT\); use override"):
        td.check_accept("accept", "KEEP", {"proposal": "REJECT"})
    td.check_accept("override", "KEEP", {"proposal": "REJECT"})
    td.check_accept("accept", "REJECT", {"proposal": "REJECT"})


def test_the_line_is_the_old_line() -> None:
    c = {"id": "c1", "name": "Invented Robotics"}
    p = {"proposal": "REJECT", "path": "both reject", "reject_basis": "NON_VENTURE", "model": "m", "run_id": "r",
         "prompt_version": "triage-v3"}  # fmt: skip
    e = td.log_entry(c, p, "RESEARCH", "override", "research", "x" * 600, "2026-11-13T10:00:00")
    assert sorted(e) == sorted(["ts", "candidate_id", "name", "machine", "machine_path", "machine_reject_basis",
                                "machine_model", "machine_run_id", "prompt_version", "verdict", "mode", "agreed",
                                "inbox_decision_applied", "note"])  # fmt: skip
    assert e["agreed"] is False and len(e["note"]) == td.NOTE_MAX
    line = log.line({**e, "note": "ünï"})
    assert line == json.dumps({**e, "note": "ünï"}, ensure_ascii=False, sort_keys=True) and "ünï" in line
    assert td.now_ts(datetime(2026, 11, 13, 9, 0, tzinfo=BERLIN)) == "2026-11-13T09:00:00"


def test_the_log_text_is_the_archive_then_the_rows() -> None:
    assert log.joined("a\n", []) == "a\n"
    assert log.joined("a\n", ["b", "c"]) == "a\nb\nc\n"
    assert log.joined("a\r\n", ["b"]) == "a\r\nb\n"
    assert log.joined("a", ["b"]) == "a\nb\n"  # never glued onto an archive without a final newline
    assert log.joined("", ["b"]) == "b\n"


def test_the_latest_verdict_is_chosen_per_survivor() -> None:
    lines = [{"candidate_id": "old", "verdict": "WATCH"}, {"candidate_id": "s", "verdict": "REJECT"},
             {"candidate_id": "x", "verdict": "KEEP"}, {"candidate_id": "old", "verdict": "RESEARCH"}, {"candidate_id": ""}]  # fmt: skip
    assert view.latest_verdicts(lines) == {"old": lines[3], "s": lines[1], "x": lines[2]}  # no aliases: as recorded
    latest = view.latest_verdicts(lines, {"old": "s"})
    assert latest == {"s": lines[3], "x": lines[2]} and lines[3]["candidate_id"] == "old"  # the line keeps its id
    cal = view.calibration(latest)
    assert cal["decisions"] == 2


def test_batch_ids_and_eligibility() -> None:
    with pytest.raises(td.TriageError, match=r"^ids must be a non-empty list$"):
        td.batch_ids({"ids": []})
    with pytest.raises(td.TriageError):
        td.batch_ids({"ids": "a"})
    assert td.batch_ids({"ids": ["a", 1, "a", "1"]}) == ["a", "1"]
    s = {"obvious_reject": True}
    new = {"decision": "new"}
    assert td.ineligible(None, new, None) == td.NO_PROPOSAL
    assert td.ineligible(s, None, None) == td.NO_PROPOSAL
    assert td.ineligible(s, {"decision": "research"}, None) == td.ALREADY_DECIDED
    assert td.ineligible(s, new, {"verdict": "KEEP", "inbox_decision_applied": None}) == td.ALREADY_DECIDED  # rev 2
    assert td.ineligible(s, new, {"verdict": "WATCH", "inbox_decision_applied": "watch"}) is None
    assert td.ineligible({"obvious_reject": False}, new, None) == td.NOT_OBVIOUS
    assert td.ineligible(s, new, None) is None


def test_a_batch_classifies_in_request_order_and_folds_aliases() -> None:
    ids = ["b-old", "b", "gone", "c", "a"]
    resolved: dict[str, str | None] = {"b-old": "b", "b": "b", "gone": None, "c": "c", "a": "a"}
    summaries = {"a": {"obvious_reject": True}, "b": {"obvious_reject": True}, "c": {"obvious_reject": False}}
    records: dict[str, dict[str, Any]] = {k: {"decision": "new"} for k in "abc"}
    eligible, skipped = td.classify_batch(ids, resolved, summaries, records, {})
    assert eligible == ["b", "a"]
    assert list(skipped.items()) == [(td.SAME_CANDIDATE, 1), (td.NO_PROPOSAL, 1), (td.NOT_OBVIOUS, 1)]


def test_the_stored_oracle_golden_matches_the_new_pure_parts() -> None:
    golden = json.loads(ptd.GOLDEN.read_text(encoding="utf-8"))
    assert golden["expected"]["blocked"] == []
    assert golden["input"] == json.loads(json.dumps(ptd.world_input(), ensure_ascii=False))
    assert ptd.compare_pure(golden) == []
    assert [len(s["case_prep"]) for s in golden["expected"]["steps"]][:4] == [1, 0, 0, 1]  # declared (c), recorded


def test_the_check_sees_a_changed_old_answer_line_and_view() -> None:
    golden = json.loads(ptd.GOLDEN.read_text(encoding="utf-8"))
    broken = copy.deepcopy(golden)
    broken["expected"]["steps"][0]["answer"]["agreed"] = False
    broken["expected"]["steps"][1]["log"] += '{"candidate_id": "extra"}\n'
    broken["expected"]["steps"][12]["survivor"]["calibration"]["decisions"] += 1
    problems = ptd.compare_pure(broken)
    assert any(p.startswith("/step0/answer/agreed") for p in problems)
    assert any(p.startswith("/step1/log") for p in problems)
    assert any(p.startswith("/step12/view/calibration/decisions") for p in problems)
