"""Review 037b unit tests: the cut sensors, the pure run helpers (traversal, the resume point, the check record, the
note), the fetch through ``core/net`` and the stored oracle golden. No database, no network."""

from __future__ import annotations

import importlib.util
import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from projectzero.core import net
from projectzero.ops import parity_watch_sensors as pws
from projectzero.ops.parity_ranking import OLD_REPO
from projectzero.watch import run, sensors, view

ROOT = Path(__file__).resolve().parents[3]
OLD = OLD_REPO / "backend" / "src" / "projectzero" / "services" / "watch.py"
GOLDEN: dict[str, Any] = json.loads(pws.GOLDEN.read_text(encoding="utf-8"))
TODAY = date(2026, 11, 13)
KEY, URL = "invented robotics", "https://robotics.invented.example/news"
W = {"name": "Invented Robotics", "candidate_id": "c-1", "candidate": None}


def _generator() -> Any:
    spec = importlib.util.spec_from_file_location("gen_watch_sensors", ROOT / "scripts" / "gen_watch_sensors.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_sensors_are_the_old_top_level_lines_cut_by_script() -> None:
    built = _generator().build()  # every cut checked node for node against the old module inside build()
    assert built == Path(sensors.__file__ or "").read_text(encoding="utf-8")  # regenerating changes nothing


def test_the_cut_keeps_the_old_vocabulary_and_the_views_labels() -> None:
    assert [k for k, _l, _r in sensors.PREDICATES][:3] == ["regulatory_approval", "certification", "procurement"]
    assert len(sensors.PREDICATES) == 18 and sensors.PREDICATES[-1][0] == "incorporation"
    assert sensors.LABEL == view.LABEL and list(sensors.LABEL) == list(view.LABEL)
    assert (sensors.MATERIAL_MIN_LINES, sensors.MATERIAL_SHARE) == (6, 0.3)
    assert "first_institutional_round" in sensors.HIGH_VALUE and "material_page_change" not in sensors.HIGH_VALUE
    assert run.LOCK == "{schema}.watch.check" and (run.JOB_BUDGET_S, run.CHECK_NOW_BUDGET_S) == (600.0, 120.0)
    assert run.REQUEST_TIMEOUT_S == 20.0 and net.MAX_BYTES == 8_000_000 and net.MAX_REDIRECTS == 5


def test_the_old_classifier_examples() -> None:
    assert sensors.classify("We raised a €2M pre-seed round led by Speedinvest") == "funding"
    assert sensors.classify("Selected for the Y Combinator W27 batch") == "accelerator"
    assert sensors.classify("Received CE mark for our device") == "regulatory_approval"
    assert sensors.classify("We're hiring: senior robotics engineer") == "team_growth"
    assert sensors.classify("Our office moved to the second floor") is None
    assert sensors._norm("Posted 10:30 ·  3 days ago  Hello") == sensors._norm("posted · hello")


def test_a_sensor_outside_a_run_context_has_no_world() -> None:
    with pytest.raises(LookupError):
        sensors.check_page(KEY, W, URL, set())


def _page(*lines: str) -> str:
    return pws.page(*lines)


def test_a_page_baseline_unchanged_pilot_reflow_and_material_change() -> None:
    base = ["Invented Robotics news", "Invented Robotics builds inspection robots."]
    name = run.snapshot_name(KEY, URL)
    first = run.check_one(KEY, W, URL, _page(*base), baselines={}, fired=set(), proposals={}, ts="T0", today=TODAY)
    assert first.res == {"url": URL, "state": "baseline", "fired": []} and first.lines == []
    lines = first.saved[name]
    same = run.check_one(KEY, W, URL, _page(*base), baselines={name: lines}, fired=set(), proposals={}, ts="T1",
                         today=TODAY)  # fmt: skip
    assert same.res["state"] == "unchanged" and same.res["new_lines"] == 0
    fired: set[str] = set()
    pilot = "Invented Robotics starts a pilot with an invented utility on 12.10.2026"
    hit = run.check_one(KEY, W, URL, _page(*base, pilot), baselines={name: lines}, fired=fired, proposals={}, ts="T2",
                        today=TODAY)  # fmt: skip
    (row,) = hit.res["fired"]
    assert (row["predicate"], row["high_value"], row["source_date"], row["first_observed"]) == (
        "pilot",
        True,
        "2026-10-12",
        "T2",
    )
    assert hit.case_refresh == [["Invented Robotics", "Pilot"]]  # decision (f): recorded by the seam, never run
    assert json.loads(hit.lines[0]) == row and hit.lines[0] == json.dumps(row, ensure_ascii=False, sort_keys=True)
    reflow = run.check_one(KEY, W, URL, _page(*base, pilot.replace("starts a", "starts   a")), baselines={name: lines},
                           fired=fired, proposals={}, ts="T3", today=TODAY)  # fmt: skip
    assert reflow.res["fired"] == [] and reflow.lines == []  # the dedupe key is over the normalised line
    material = [f"Completely new invented section number {i}" for i in range(8)]
    big = run.check_one(KEY, W, URL, _page(*base, *material), baselines={name: lines}, fired=set(), proposals={},
                        ts="T4", today=TODAY)  # fmt: skip
    assert [r["predicate"] for r in big.res["fired"]] == ["material_page_change"]
    failed = run.check_one(KEY, W, URL, OSError("invented reset"), baselines={}, fired=set(), proposals={}, ts="T5",
                           today=TODAY)  # fmt: skip
    assert (failed.ok, failed.err, failed.res["state"], failed.saved) == (
        False,
        "OSError: invented reset",
        "failed",
        {},
    )


def test_rehits_funding_of_a_pre_funding_candidate_is_its_first_institutional_round() -> None:
    cand = {"id": "c-1", "name": "Invented Robotics", "first_seen": "2026-09-01",
            "also_seen": [{"source_id": "s-1", "source": "Invented Press", "discovery_tier": "announcement",
                           "first_seen": "2026-10-01 08:00:00", "url": "https://press.invented.example/r"},
                          {"source_id": "s-0", "discovery_tier": "grant", "first_seen": "2026-08-01"}]}  # fmt: skip
    w = {"name": cand["name"], "candidate_id": "c-1", "candidate": cand}
    pre = run.rehits_of(KEY, w, fired=set(), proposals={"c-1": {"capital_stage": "PRE_COMPANY"}}, ts="T", today=TODAY)
    assert [r["predicate"] for r in pre.rows] == ["first_institutional_round"] and len(pre.lines) == 1
    funded = run.rehits_of(KEY, w, fired=set(), proposals={"c-1": {"capital_stage": "ALREADY_INSTITUTIONALLY_FUNDED"}},
                           ts="T", today=TODAY)  # fmt: skip
    assert [r["predicate"] for r in funded.rows] == ["funding"]
    again = run.rehits_of(KEY, w, fired={pre.rows[0]["dedupe_key"]}, proposals={}, ts="T", today=TODAY)
    assert again.rows == []  # deduplicated


def test_the_traversal_rotation_and_successor_follow_revision_4() -> None:
    watched = {"k1": W, "k2": W, "k3": W}
    targets = {"k1": {"urls": ["A", "B"], "active": False}, "k2": {"urls": ["C"]}, "k4": {"urls": ["X"]}}
    pages = run.traversal(watched, targets, None)
    assert pages == [("k1", "A"), ("k1", "B"), ("k2", "C")]  # an inactive target's URLs of a watched company count
    assert run.traversal(watched, targets, "K2") == [("k2", "C")]
    assert run.rotate(pages, None) == pages
    assert run.rotate(pages, ("k1", "B")) == [("k1", "B"), ("k2", "C"), ("k1", "A")]
    assert run.rotate(pages, ("k2", "gone")) == [("k2", "C"), ("k1", "A"), ("k1", "B")]  # its company's first page
    assert run.rotate(pages, ("k9", "gone")) == pages
    assert run.successor(pages, ("k1", "A")) == ("k1", "B") and run.successor(pages, ("k2", "C")) == ("k1", "A")


def test_a_duplicate_url_is_visited_once_so_the_resume_point_cannot_strand_a_later_page() -> None:
    """Codex H-391: a stored list ``[A, A, B]`` traverses ``[A, B]``; after A is cut, its successor is B, and B is
    where the next run starts (the old order kept the duplicate: A's successor was A again)."""
    watched = {"k1": W, "k2": W}
    targets = {"k1": {"urls": ["A", "A", "B"]}, "k2": {"urls": ["C", "A"]}}  # the same URL at another company stays
    pages = run.traversal(watched, targets, None)
    assert pages == [("k1", "A"), ("k1", "B"), ("k2", "C"), ("k2", "A")]
    assert targets["k1"]["urls"] == ["A", "A", "B"]  # the stored list is never changed
    nxt = run.successor(pages, ("k1", "A"))
    assert nxt == ("k1", "B") and run.rotate(pages, nxt)[0] == ("k1", "B")
    assert run.traversal(watched, {"k1": {"urls": ["A", "A"]}}, None) == [("k1", "A")]
    assert run.successor([("k1", "A")], ("k1", "A")) == ("k1", "A")


def test_normalise_drops_an_old_repeated_visit_and_refuses_one_that_fired() -> None:
    row = {"entity": "Invented Robotics", "url": "A", "state": "baseline", "fired": [], "error": ""}
    step = {"op": "check", "answer": {"fired": 0, "pages": [row, {**row, "state": "unchanged", "new_lines": 0}],
            "failures": 0}, "log": "", "targets": None, "snapshots": {}, "view": {}}  # fmt: skip
    assert pws.normalise(step)["answer"]["pages"] == [row]
    assert pws.fetched_once(["A", "A", "B"]) == ["A", "B"]
    step["answer"]["pages"][1]["fired"] = [{"id": "wt-x"}]
    with pytest.raises(ValueError, match="repeated visit"):
        pws.normalise(step)


def test_the_check_record_is_the_old_one() -> None:
    record = {"name": "Invented Robotics", "urls": [URL]}  # no ``checks`` yet: appended last, as setdefault did
    failed = run.recorded(record, URL, "failed", False, "OSError: x", "T1")
    assert list(failed) == ["name", "urls", "checks"] and record == {"name": "Invented Robotics", "urls": [URL]}
    assert failed["checks"][URL] == {
        "last_checked": "T1",
        "last_state": "failed",
        "failures_in_row": 1,
        "last_error": "OSError: x",
    }
    twice = run.recorded(failed, URL, "failed", False, "OSError: y", "T2")
    assert twice["checks"][URL]["failures_in_row"] == 2
    ok = run.recorded(twice, URL, "unchanged", True, "", "T3")
    assert ok["checks"][URL] == {"last_checked": "T3", "last_state": "unchanged", "failures_in_row": 0,
                                 "last_error": "OSError: y", "last_ok": "T3"}  # fmt: skip


def test_the_note_names_the_pages_left_only_when_some_were() -> None:
    out = {"fired": 2, "pages": [{}, {}], "failures": 1, "skipped": 0}
    assert run.note(out) == "2 new trigger(s) · 2 page(s) checked · 1 failure(s)"
    assert (
        run.note({**out, "skipped": 3})
        == "2 new trigger(s) · 2 page(s) checked · 1 failure(s) · 3 page(s) left for the next run"
    )
    assert run.JOB_BUSY_NOTE == "skipped — A WATCH check is already running."


def test_a_fetch_goes_through_core_net_with_the_old_headers_and_the_deadline() -> None:
    t = pws.PageTransport({URL: {"body": "<p>hello there</p>"}, "https://slow.invented.example/": {"slow": 5}})
    deadline = time.monotonic() + 30
    text, cut = run.fetch_page(URL, deadline, t, pws.fixture_resolver)
    assert (text, cut) == ("<p>hello there</p>", False)
    q = t.asked[0]
    assert (
        q["headers"]["User-Agent"] == net.BROWSER_HEADERS["User-Agent"]
        and q["headers"]["Accept-Language"] == "de,en;q=0.8"
    )
    assert (
        q["timeout"] <= 20
        and q["max_bytes"] == net.MAX_BYTES
        and q["deadline"] == deadline
        and q["ip"] == pws.FIXTURE_IP
    )
    err, cut = run.fetch_page("https://slow.invented.example/", time.monotonic() + 0.2, t, pws.fixture_resolver)
    assert isinstance(err, net.FetchError) and cut is True  # the deadline: skipped, never a failure
    err, cut = run.fetch_page("https://inner.invented.example/", time.monotonic() + 30, t, lambda h: ["10.0.0.7"])
    assert isinstance(err, net.UnsafeURLError) and cut is False  # a private host: a failed check


def test_the_stored_golden_matches_the_pure_new_side() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False and GOLDEN["expected"]["blocked"] == []
    assert GOLDEN["input"] == json.loads(json.dumps(pws.world_input(), ensure_ascii=False))
    assert pws.compare_pure(GOLDEN) == []
    fired = [s["answer"].get("fired", s["answer"].get("watch_triggers")) for s in GOLDEN["expected"]["steps"]]
    assert fired == [3, 1, 0, 1, 1, None, 0, 2, 0, 0]  # (the target step answers its record)
