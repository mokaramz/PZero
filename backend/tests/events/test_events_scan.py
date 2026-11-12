"""The event source scan without the network or a database (review 017): the goldens the OLD scan generated, and the
intentional differences (Codex H-113): an empty saved baseline is a baseline, a failed watcher keeps its last good
baseline, the registry is repaired and new defaults offered once BEFORE fetching, leads are never deleted, the
deadline, and the Berlin date of the scan instant."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from projectzero.events import registry
from projectzero.events.collectors import fetch_watch_page
from projectzero.events.promotion import add_leads
from projectzero.events.scan import DEADLINE_NOTE, _fetch_all, compute
from projectzero.ops.parity_events_scan import CLOCK, GOLDEN, RecordedFetcher, compare_goldens, corpus

GOLDEN_DOC: dict[str, Any] = json.loads(GOLDEN.read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
TODAY = date(2026, 11, 20)


def test_provenance_and_input() -> None:
    prov = GOLDEN_DOC["provenance"]
    assert prov["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e" and prov["old_dirty"] is False
    files, responses = corpus()
    assert GOLDEN_DOC["input"] == json.loads(json.dumps({"clock": CLOCK, "responses": responses,
                                                          "sets": [{"name": "synthetic", "files": files}]}))  # fmt: skip


def test_the_scan_matches_the_old_one() -> None:
    assert compare_goldens(GOLDEN_DOC) == []


def test_the_corpus_reaches_every_branch() -> None:
    health = GOLDEN_DOC["expected"]["sets"]["synthetic"]["health"]["ok"]
    statuses = {r["status"] for r in health["sources"]}
    routes = {r["route"] for r in health["sources"]}
    assert statuses == {"ok", "failed", "config_required"}
    assert {"json-ld", "luma-next-data", "ics", "api", "watcher"} <= routes
    t = health["totals"]
    assert t["ingested"] > 0 and t["dups"] > 0 and t["past"] > 0 and t["watcher_review"] > 0


# ── watchers ────────────────────────────────────────────────────────────────────────────────────────────────────
SRC = {"id": "s-w", "name": "Watcher", "kind": "watcher", "url": "https://w.example.com/", "city": "Paris"}
PAGE = "<p>Founders breakfast every Friday</p><p>Startup Meetup on 2026-12-20</p>"


def test_an_empty_saved_baseline_is_a_baseline() -> None:
    fetcher = RecordedFetcher({SRC["url"]: {"text": PAGE}})
    first = fetch_watch_page(SRC, fetcher, None, TODAY)
    empty = fetch_watch_page(SRC, fetcher, [], TODAY)
    assert first.first is True and empty.first is False  # the old code read [] as a first scan and re-flooded
    assert {x["source"] for x in empty.leads} == {"Watcher"}  # a later scan: no "(first scan)" label
    assert empty.lines == ["Founders breakfast every Friday", "Startup Meetup on 2026-12-20"]


def test_a_failed_watcher_fetch_keeps_the_last_good_baseline() -> None:
    reg = registry.prepare({"sources": [SRC], "offered_defaults": registry.NEW_DEFAULTS}, NOW)
    fetched = _fetch_all(reg.sources, {}, {"s-w": {"lines": ["old line"], "seeded_from": None}},
                         RecordedFetcher({SRC["url"]: {"error": "TimeoutError", "message": "timed out"}}), NOW,
                         float("inf"), lambda: 0.0)  # fmt: skip
    assert fetched[0].row["status"] == "failed" and fetched[0].row["note"] == "TimeoutError: timed out"
    plan = compute(fetched, [], [], {}, {}, NOW, TODAY, 0.0)
    assert plan.snapshots == []  # nothing replaces the baseline


# ── the registry ────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_registry_is_repaired_and_offered_the_new_defaults_once() -> None:
    stored = {
        "sources": [{"id": "ev-stationf", "name": "Station F", "kind": "jsonld", "url": "https://stationf.co/events"}]
    }
    reg = registry.prepare(stored, NOW)
    assert reg.changed and reg.sources[0]["kind"] == "watcher"
    assert [s["id"] for s in reg.sources[1:]] == registry.NEW_DEFAULTS  # they take part in THIS scan
    assert reg.document["offered_defaults"] == registry.NEW_DEFAULTS
    assert all(s["added_note"] == "2026-11-20: new default source" for s in reg.sources[1:])
    removed = {**reg.document, "sources": reg.document["sources"][:1]}  # the operator removed the new ones
    again = registry.prepare(removed, NOW)
    assert not again.changed and [s["id"] for s in again.sources] == ["ev-stationf"]  # never re-added
    assert stored["sources"][0]["kind"] == "jsonld"  # prepare never mutates what it was given


def test_a_repair_alone_changes_the_registry() -> None:
    stored = {"sources": [{"id": "ev-stationf", "name": "Station F", "kind": "jsonld", "url": "https://stationf.co/events"}],
              "offered_defaults": list(registry.NEW_DEFAULTS)}  # fmt: skip
    reg = registry.prepare(stored, NOW)
    assert reg.changed and [s["kind"] for s in reg.sources] == ["watcher"]
    assert not registry.prepare(reg.document, NOW).changed  # idempotent


def test_a_missing_registry_is_the_defaults() -> None:
    reg = registry.prepare(None, NOW)
    assert reg.changed and len(reg.sources) == len(registry.DEFAULT_SOURCES) == 33


# ── leads ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _lead(i: int, **kw: Any) -> dict[str, Any]:
    return {"id": f"evlead-{i}", "title": f"Distinct lead {i} xq{i}", "date": "2026-12-01", "decision": "new", **kw}


def test_leads_are_never_trimmed_and_a_repeated_id_is_added_once() -> None:
    existing = [_lead(i) for i in range(300)]
    out = add_leads([_lead(1000), _lead(1000)], existing, [], TODAY)
    assert out.added == 1 and [x["id"] for x in out.new] == ["evlead-1000"]  # the old code kept only 250 in total


def test_a_lead_dated_before_the_scan_day_is_dropped() -> None:
    out = add_leads([_lead(1, date="2026-11-19"), _lead(2, date="2026-11-20")], [], [], TODAY)
    assert (out.added, out.dropped_past) == (1, 1)


# ── the deadline and the clock ──────────────────────────────────────────────────────────────────────────────────
def test_sources_after_the_deadline_are_failed_and_never_fetched() -> None:
    srcs = [{"id": f"s{i}", "name": f"S{i}", "kind": "jsonld", "url": f"https://s{i}.example.com/"} for i in range(3)]
    fetcher = RecordedFetcher({s["url"]: {"text": ""} for s in srcs})
    ticks = iter([0.0, 1.0, 5.0, 11.0, 12.0])  # source 0 at 0 s; source 1 at 5 s (> deadline 4 s)
    fetched = _fetch_all(srcs, {}, {}, fetcher, NOW, 4.0, lambda: next(ticks))
    assert [f.row["status"] for f in fetched] == ["ok", "failed", "failed"]
    assert fetched[1].row["note"] == DEADLINE_NOTE and fetcher.asked == ["https://s0.example.com/"]


def test_the_scan_dates_by_the_berlin_day_of_its_instant() -> None:
    late = datetime(2026, 11, 19, 23, 30, tzinfo=UTC)  # 00:30 on 20 Nov in Berlin
    fetcher = RecordedFetcher(
        {SRC["url"]: {"text": "<p>Startup Meetup on 19.11.2026</p><p>Startup Meetup on 20.11.2026</p>"}}
    )
    fetched = _fetch_all([SRC], {}, {}, fetcher, late, float("inf"), lambda: 0.0)
    plan = compute(fetched, [], [], {}, {}, late, date(2026, 11, 20), 0.0)
    assert [x["date"] for x in plan.leads] == ["2026-11-20"]  # the 19th is already past in Berlin
    assert {x["detected_on"] for x in plan.leads} == {"2026-11-20"}
    assert plan.health["scan_time"] == "2026-11-20 00:30"
