"""Review 037a: the pure parts of the WATCH store (no database) and the stored oracle golden."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from projectzero.network.view import BERLIN
from projectzero.ops import parity_watch_store as pws
from projectzero.watch import log as watch_log
from projectzero.watch import targets as watch_targets
from projectzero.watch import view as watch_view
from projectzero.watch import writes

TS = "2026-11-13T10:00:00"


def test_the_target_checks_run_in_the_old_order() -> None:
    with pytest.raises(writes.WatchError, match=r"^company name required$"):
        writes.parse_target({"name": "  GmbH ", "urls": ["ftp://bad"]})  # the name first
    with pytest.raises(writes.WatchError, match=r"^not a public http\(s\) URL: ftp://x\.invented\.example/$"):
        writes.parse_target({"name": "Invented Robotics", "urls": [" ftp://x.invented.example/ "]})
    with pytest.raises(writes.WatchError, match=r"^not a public http\(s\) URL: localhost/x$"):
        writes.parse_target({"name": "Invented Robotics", "urls": ["https://a.invented.example/", "localhost/x"]})
    for bad in ("https://a.invented.example/", [1], [None], {"u": 1}):
        with pytest.raises(writes.WatchError, match=r"^urls must be a list of strings$"):
            writes.parse_target({"name": "Invented Robotics", "urls": bad})
    many = [f"https://a.invented.example/{i}" for i in range(8)]
    req = writes.parse_target({"name": " Invented Robotics GmbH ", "urls": ["  ", *many, "ftp://ignored-after-six"]})
    assert (req.name, req.key, req.urls) == ("Invented Robotics GmbH", "invented robotics", many[:6])
    assert writes.parse_target({"name": "X Co Labs"}).urls == []


@pytest.mark.parametrize(("value", "active"), [(False, False), (True, True), ("false", True), (0, True), (None, True)])
def test_only_a_json_false_deactivates(value: object, active: bool) -> None:
    assert writes.parse_target({"name": "Invented Robotics", "active": value}).active is active
    assert writes.parse_target({"name": "Invented Robotics"}).active is True


def test_the_merge_keeps_the_creation_time_and_the_checks() -> None:
    req = writes.parse_target({"name": "Invented Robotics", "urls": ["https://a.invented.example/"]})
    new = writes.merged(None, req, TS)
    assert new == {"name": "Invented Robotics", "added_at": TS, "checks": {}, "urls": ["https://a.invented.example/"],
                   "candidate_id": "", "active": True, "updated_at": TS}  # fmt: skip
    assert list(new) == ["name", "added_at", "checks", "urls", "candidate_id", "active", "updated_at"]
    imported = {"name": "Old Name", "added_at": "2026-10-01T09:00:00", "checks": {"https://b.invented.example/": {"x": 1}},
                "urls": ["https://b.invented.example/"], "candidate_id": "c-1", "active": False, "extra": 1}  # fmt: skip
    out = writes.merged(imported, req, TS)
    assert out["added_at"] == "2026-10-01T09:00:00" and out["checks"] == imported["checks"]  # kept, never pruned
    assert (out["candidate_id"], out["active"], out["updated_at"], out["extra"]) == ("c-1", True, TS, 1)
    assert list(out) == ["name", "added_at", "checks", "urls", "candidate_id", "active", "extra", "updated_at"]
    assert imported["name"] == "Old Name"  # the effective record is never modified
    other = writes.parse_target({"name": "Invented Robotics", "candidate_id": "c-2"})
    assert writes.merged(imported, other, TS)["candidate_id"] == "c-2"


def test_the_acknowledgement_checks_the_status_first() -> None:
    with pytest.raises(writes.WatchError, match=r"^status must be reviewed or dismissed$"):
        writes.parse_ack({"id": "wt-1", "status": "closed"})
    with pytest.raises(writes.WatchError, match=r"^status must be reviewed or dismissed$"):
        writes.parse_ack({"id": "wt-1"})
    assert writes.parse_ack({"id": 7, "status": "dismissed", "note": "x" * 400}) == ("7", "dismissed", "x" * 300)
    assert writes.parse_ack({"status": "reviewed", "note": None}) == ("", "reviewed", "")
    assert writes.now_ts(datetime(2026, 11, 13, 9, 0, tzinfo=BERLIN)) == "2026-11-13T09:00:00"
    assert writes.now_ts(datetime(2026, 11, 13, 8, 0)) == "2026-11-13T08:00:00"  # naive: Berlin wall time
    assert writes.LOCK.format(schema="pz_itest_0") == "pz_itest_0.watch"


def test_the_log_is_one_reader() -> None:
    t = {"id": "wt-1", "kind": "trigger", "name": "Invented Robotics"}
    text = (
        "﻿"
        + json.dumps(t)
        + "\r\nnot json\n[1]\n"
        + json.dumps({"kind": "status", "trigger_id": "wt-1", "status": "reviewed"})
    )
    assert [e.get("id") for e in watch_log.events_of(text.encode("utf-8"))] == ["wt-1", None]  # the BOM hides nothing
    assert watch_log.events_of(b"\xff\xfe broken") == [] and watch_log.events_of(None) == []
    assert watch_log.events_of([t, "x", {"a": 1}]) == [t, {"a": 1}]
    [row] = watch_log.triggers(watch_log.events_of(text.encode("utf-8")))
    assert (row["status"], row["entity_key"], row["label"], row["high_value"]) == (
        "reviewed",
        "Invented Robotics",
        "change",
        False,
    )
    assert watch_log.open_triggers([t]) == [{**t, "status": "new", "status_at": "", "entity_key": "Invented Robotics",
                                             "high_value": False, "first_observed": "", "evidence": "", "source_kind": "",
                                             "url": "", "label": "change"}]  # fmt: skip
    assert watch_log.line({"b": 1, "a": "ü\n"}) == '{"a": "ü\\n", "b": 1}'  # JSON escapes the newline
    assert watch_log.joined("a", ["b"]) == "a\nb\n" and watch_log.joined("a\r\n", []) == "a\r\n"


def test_the_targets_overlay_and_the_watched_set() -> None:
    imported = {"b co": {"name": "B", "active": True}, "a co": {"name": "A", "active": False}}
    eff = watch_targets.overlay(imported, [("a co", {"name": "A2", "active": True}), ("c co", {"name": "C"})])
    assert list(eff) == ["b co", "a co", "c co"] and eff["a co"]["name"] == "A2"  # a row wins in place
    assert watch_targets.targets_of({"targets": [1]}) == {} and watch_targets.targets_of(None) == {}
    assert watch_targets.targets_of({"targets": {"x": 1, "y": {"name": "Y"}}}) == {"y": {"name": "Y"}}
    cands = [{"id": "c1", "name": "B Co", "decision": "watch"}, {"id": "c2", "name": "Z", "decision": "new"},
             {"id": "", "name": "No Id", "decision": "watch"}, {"id": "c3", "name": "", "decision": "watch"}]  # fmt: skip
    w = watch_targets.watched(cands, eff)
    assert list(w) == ["b", "b co", "a co", "c co"]
    assert w["b"]["candidate_id"] == "c1" and w["c co"] == {"name": "C", "candidate_id": "", "candidate": None}
    eff["a co"]["active"] = False
    assert "a co" not in watch_targets.watched(cands, eff)


def test_the_view_keeps_the_old_details() -> None:
    def trig(n: int, key: str, at: str) -> dict[str, object]:
        return {"id": f"wt-{key}{n}", "kind": "trigger", "entity_key": key, "name": key, "first_observed": at}

    events = [trig(i, "b", f"2026-11-{i:02d}T07:00:00") for i in range(1, 13)] + [trig(1, "a", "2026-11-02T07:00:00")]
    watched = {"b": {"name": "beta", "candidate_id": "c-b"}, "a": {"name": "Alpha", "candidate_id": "c-a"},
               "z": {"name": "zulu", "candidate_id": ""}}  # fmt: skip
    props = {"c-b": {"proposed_at": "2026-11-12T07:00:00", "proposal": "WATCH"},
             "c-a": {"proposed_at": "2026-11-01T07:00:00", "proposal": "KEEP"}}  # fmt: skip
    out = watch_view.build(watched, {"b": {"urls": ["https://b.invented.example/"]}}, props, events)
    assert [c["key"] for c in out["companies"]] == ["b", "a", "z"]  # (-open, name.lower())
    b, a, z = out["companies"]
    assert len(b["triggers"]) == 10 and b["triggers"][0]["first_observed"] == "2026-11-12T07:00:00" and b["open"] == 12
    assert b["triage_predates_evidence"] is False  # equal strings: not older
    assert a["triage_predates_evidence"] is True and a["machine_proposal"] == "KEEP"
    assert z == {"key": "z", "name": "zulu", "candidate_id": "", "urls": [], "checks": {}, "triggers": [], "open": 0,
                 "triage_predates_evidence": False, "machine_proposal": None}  # fmt: skip
    assert out["note"] == "Deterministic sensors only. Nothing here changes a decision or a score."
    assert "status" not in events[0]  # the inputs are never modified


def test_the_stored_golden_matches_the_pure_port() -> None:
    golden = json.loads(pws.GOLDEN.read_text(encoding="utf-8"))
    assert golden["expected"]["blocked"] == []
    assert golden["input"] == json.loads(json.dumps(pws.world_input(), ensure_ascii=False))
    assert pws.compare_pure(golden) == []
    labels = golden["expected"]["steps"][0]["view"]["labels"]
    assert list(labels.items()) == list(watch_view.LABEL.items())  # the old labels, in the old order
    old = [len(s["view"]["companies"]) for s in golden["expected"]["steps"]]
    with_a = [len(s["view_a"]["companies"]) for s in golden["expected"]["steps"]]
    assert all(n + 1 == m for n, m in zip(old, with_a, strict=True))  # (a): one Scout lead without a target joins
