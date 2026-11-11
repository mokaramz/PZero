"""Events read parity: the port against the OLD code as oracle, with a FIXED clock on both sides (review 015).

    python -m projectzero.ops.parity_events_read goldens   # (re)generate tests/fixtures/golden_v1/oracle_events_read.json
    python -m projectzero.ops.parity_events_read real      # the real snapshot through the routes, at REAL_CLOCKS

The oracle (``scripts/oracle/events_read_oracle.py``) runs in the OLD repository's interpreter and package with
``PZ_DATA`` pointed at a temp folder: empty for the goldens (each synthetic set writes its files), or a byte-exact copy
of the captured snapshot for ``real``. The old data folder is only ever read.

Clocks are Berlin wall-clock times. The new side gets each as the UTC INSTANT it is (``utc_instant``), so the
request's Berlin date is derived exactly as in production, including just before and at Berlin midnight while UTC
still has the previous date.

``goldens``: synthetic sets (synthetic names only):
* ``rules``: every eligibility / price / action branch, undated / past / ongoing / Friday-only / Fri-Sat / Sat-Mon,
  offset times, a free-text date, city aliases and suburbs, human ``score_parts`` and ``type_human``, ties, the
  ``overlaps`` boundaries of a weekend spanning each DST change, Scout 00 reports (linked by id with a ``|merged:``
  suffix, by the dedup rule, annotated, closed, past), contacts for WSIG, source health;
* ``empty``: no files (the defaults);
* ``many_leads``: 300 leads (only ``new`` ones are listed, in stored order).
The new side is the pure ``events.view`` on the same records, with no pins (the old code at the same clock IS the
reference for a free-text date; the persisted-year difference is asserted separately, in the unit tests).

``real`` imports the SAME snapshot into a throw-away scratch schema with the production importer and compares
``GET /api/events``, ``/health``, ``/wsig`` (each of ``WSIG_DAYS``) and ``/weekend`` (this and next weekend) with the
old bodies at each clock: every event, every field, the exact id order. It prints AGGREGATES and difference PATHS
only; real records never leave the machine. Exit 1 on any difference.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.events import engine, view
from projectzero.events.store import EventsData
from projectzero.events.when import BERLIN
from projectzero.network import view as people_view
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "events_read_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_events_read.json"
CLOCKS = (
    "2026-11-11T12:00:00",  # Wednesday
    "2026-11-13T23:59:59",  # Friday, one second before Berlin midnight (UTC 22:59:59)
    "2026-11-14T00:00:00",  # Saturday at Berlin midnight (UTC still Friday 23:00)
    "2026-11-15T22:00:00",  # Sunday night
    "2026-10-23T12:00:00",  # the Friday before the October clock change (weekend 24-25 Oct)
    "2026-03-27T12:00:00",  # the Friday before the March clock change (weekend 28-29 Mar)
)
REAL_CLOCKS = (
    "2026-11-11T12:00:00",  # a weekday
    "2026-11-14T10:00:00",  # a Saturday
    "2026-11-15T23:30:00",  # a Sunday, late
    "2026-10-26T09:00:00",  # the day after the October clock change
    "2026-11-14T00:00:00",  # Berlin midnight while UTC is still Friday
)
WSIG_DAYS = (7, 14, 30)
GOLDEN_WSIG_DAYS = (7, 14, 30, 0, -1)


def utc_instant(berlin_wall_clock: str) -> datetime:
    return datetime.fromisoformat(berlin_wall_clock).replace(tzinfo=BERLIN).astimezone(UTC)


def weekends_for(clock: str) -> list[list[str]]:
    sat, sun = engine.weekend_window(datetime.fromisoformat(clock).date())
    nxt = sat + timedelta(days=7)
    return [[sat.isoformat(), sun.isoformat()], [nxt.isoformat(), (nxt + timedelta(days=1)).isoformat()]]


# ------------------------------------------------------------------ the oracle
def run_oracle(inp: Mapping[str, Any], files: Mapping[str, bytes] | None = None, mode: str = "reads") -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-events-oracle-") as tmp:
        tmpdir = Path(tmp)
        data = tmpdir / "data"
        data.mkdir()
        for rel, raw in (files or {}).items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        src, dst = tmpdir / "in.json", tmpdir / "out.json"
        src.write_text(json.dumps(inp), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)  # the oracle never needs, and never sees, the database
        run = subprocess.run(
            [str(python), str(ORACLE), mode, str(src), str(dst)], env=env, capture_output=True, text=True
        )
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


# ------------------------------------------------------------------ the synthetic corpus
_GOOD = {
    "city": "Karlsruhe",
    "url": "https://hall.example.com/e",
    "organizer": "Example Founders Lab",
    "route": "api",
    "venue": "Hall A",
    "format": "in_person",
    "price": {"amount": 0},
    "description": "A hackathon weekend for founders and engineers building robotics startups. Networking with investors.",
}


def ev(eid: str, name: str, start: Any, end: Any = None, **kw: Any) -> dict[str, Any]:
    e = {"id": eid, "name": name, "start": start, **({} if end is None else {"end": end}), **kw}
    return e


def rules_events() -> list[dict[str, Any]]:
    g = _GOOD
    return [
        ev("ev-hs", "Robotics Hackathon Karlsruhe", "2026-11-14T10:00", "2026-11-15T18:00", **g),
        ev("ev-tie-a", "Founder Demo Day Alpha", "2026-11-20", **g),
        ev("ev-tie-b", "Founder Demo Day Beta", "2026-11-20", **g),  # same start + score as tie-a: stored order
        ev("ev-undated", "Startup Pitch Evening", "TBA", **g),
        ev("ev-null-start", "Founders Breakfast", None, **g),
        ev("ev-empty-start", "Founders Lunch", "", **g),
        ev("ev-past", "Spin-off Day", "2026-11-01", **g),
        ev("ev-ongoing", "Deep Tech Accelerator Cohort Week", "2026-11-10", "2026-11-20", **g),
        ev("ev-friday", "Pitch Night Friday", "2026-11-13T18:00", **g),
        ev("ev-fri-sat", "Venture Studio Days", "2026-11-13", "2026-11-14", **g),
        ev("ev-sat-mon", "Incubator Retreat", "2026-11-14", "2026-11-16", **g),
        ev("ev-utc", "Late Founder Meetup", "2026-11-14T23:30Z", **g),  # Sunday 00:30 in Berlin
        ev("ev-offset", "Cohort Kickoff", "2026-11-21T09:00+05:30", **g),
        ev("ev-dmy", "Gründer Abend", "20.11.2026 18:30", "20.11.2026 21:00", **g),
        ev("ev-free", "Founder Mixer", "Nov 20", **g),  # free text: the clock gives the year
        ev("ev-start-only-time", "Startup Office Hours", "2026-11-20T18:00", **g),
        ev("ev-end-before", "Pitch Workshop", "2026-11-22", "2026-11-18", **g),
        ev("ev-soldout-wl", "Sold Out Hackathon", "2026-11-21", **{**g, "price": {"availability": "https://schema.org/SoldOut", "waitlist_url": "https://w.example.com"}}),
        ev("ev-soldout", "Packed Founder Summit", "2026-11-21", **{**g, "price": {"availability": "SoldOut"}}),
        ev("ev-soldout-notes", "Packed Pitch Day", "2026-11-21", **{**g, "price": {"availability": "SoldOut"}, "notes": "join the waitlist"}),
        ev("ev-range", "Accelerator Open House", "2026-11-22", **{**g, "price": {"low": 10, "high": 50}}),
        ev("ev-paid", "Investor Forum", "2026-11-22", **{**g, "price": {"amount": "25"}}),
        ev("ev-bad-amount", "Angel Evening", "2026-11-22", **{**g, "price": {"amount": "free"}}),
        ev("ev-no-price", "Founder Circle", "2026-11-22", **{k: v for k, v in g.items() if k != "price"}),
        ev("ev-cancel-name", "Founder Pitch Night (cancelled)", "2026-11-25", **g),
        ev("ev-cancel-status", "Demo Day West", "2026-11-25", **g, event_status="https://schema.org/EventCancelled"),
        ev("ev-excl", "Sunday Running Club", "2026-11-22", city="Karlsruhe", url="https://run.example.com", description="A relaxed 10k run along the river.", route="api"),
        ev("ev-excl-founder", "Founders Morning Run", "2026-11-22", city="Karlsruhe", url="https://run.example.com/f", description="A morning run for founders and operators.", route="ics", organizer="Example Ventures"),
        ev("ev-builders", "Builders Yoga Morning", "2026-11-22", city="Karlsruhe", url="https://yoga.example.com", description="Yoga for builders."),
        ev("ev-human", "Our Own Pick", "2026-11-23", city="Stuttgart", score_parts={"founder_density": 20, "tech_talent": 14, "earliness": 11, "domain_fit": 15, "network_value": 7, "accessibility": 10, "serendipity": 4}),
        ev("ev-human-75", "Ladder Seventy Five", "2026-11-23", city="Stuttgart", score_parts={"founder_density": 25, "tech_talent": 20, "earliness": 15, "domain_fit": 6, "network_value": 4, "accessibility": 4, "serendipity": 1}),
        ev("ev-human-74", "Ladder Seventy Four", "2026-11-23", city="Stuttgart", score_parts={"founder_density": 25, "tech_talent": 20, "earliness": 15, "domain_fit": 2, "network_value": 7, "accessibility": 4, "serendipity": 1}),
        ev("ev-human-55", "Ladder Fifty Five", "2026-11-23", city="Stuttgart", score_parts={"founder_density": 16, "tech_talent": 14, "earliness": 11, "domain_fit": 6, "network_value": 1, "accessibility": 4, "serendipity": 3}),
        ev("ev-human-40", "Ladder Forty", "2026-11-23", city="Stuttgart", score_parts={"founder_density": 8, "tech_talent": 7, "earliness": 6, "domain_fit": 6, "network_value": 4, "accessibility": 4, "serendipity": 5}),
        ev("ev-type-human", "Quarterly Gathering", "2026-11-23", city="Berlin", type_human="vc", url="https://q.example.com"),
        ev("ev-no-url", "Founder Talk", "2026-11-23", city="Karlsruhe", description="for founders", route="api", organizer="Example Lab"),
        ev("ev-no-city", "Remote Startup Clinic", "2026-11-23", url="https://r.example.com", description="for startups", route="api", organizer="Example Lab"),
        ev("ev-virtual", "Online Founder Clinic", "2026-11-23", url="https://v.example.com", format="virtual", description="for founders", route="json-ld", organizer="Example Lab"),
        ev("ev-watcher", "Hackathon Notice", "2026-11-23", city="Mannheim", url="https://w2.example.com", route="watcher"),
        ev("ev-planned", "Planned Coffee Meetup", "2026-11-24", city="Heidelberg", status="planned"),
        ev("ev-verified", "Verified Community Night", "2026-11-24", city="Heidelberg", human_verified=True),
        ev("ev-skipped", "Skipped Robotics Hackathon", "2026-11-14", "2026-11-15", **g, status="skipped"),
        ev("ev-munich-alias", "AI Founders Night", "2026-11-26", **{**g, "city": "München", "country": "DE"}),
        ev("ev-munich-comma", "Robotics Pitch", "2026-11-26", **{**g, "city": "Munich, Germany"}),
        ev("ev-frankfurt-us", "Startup Hackathon", "2026-11-26", **{**g, "city": "Frankfurt", "country": "US"}),
        ev("ev-egg", "Deep Tech Demo Day", "2026-11-27", **{**g, "city": "Egg", "country": ""}),
        ev("ev-source-city", "Quantum Accelerator Day", "2026-11-27", **{**g, "city": "Schlieren", "country": ""}, sources=[{"source_id": "src-zrh", "provenance": "json-ld", "url": "https://s.example.com"}]),
        ev("ev-provenance-route", "Energy Startup Meetup", "2026-11-27", city="Paris", url="https://p.example.com", sources=[{"source_id": "src-x", "provenance": "ics"}], description="for startups in energy"),
        ev("ev-auto", "Auto Promoted Event", "2026-11-27", city="Basel", auto_promoted=True, keywords="robotics, ai"),
        ev("ev-topics", "Topics Event", "2026-11-28", city="Zürich", topics=["climate"], url="https://t.example.com"),
        ev("ev-domains", "Defense Founders Forum", "2026-11-28", **g, domains="defence, industrial"),
        # the October clock change (Sun 25 Oct, 03:00 -> 02:00): window Sat 24 - Sun 25
        ev("ev-oct-before", "Friday Founder Social", "2026-10-23T19:00", "2026-10-24T00:00", **g),  # ends AT the start
        ev("ev-oct-sat", "Hackathon Saturday", "2026-10-24", **g),
        ev("ev-oct-repeat", "Night Hack Session", "2026-10-25T02:30", "2026-10-25T02:45", **g),  # the repeated hour
        ev("ev-oct-late", "Sunday Pitch Session", "2026-10-25T23:00", "2026-10-25T23:59", **g),
        ev("ev-oct-after", "Monday Demo Day", "2026-10-26T00:00", **g),  # starts AT the exclusive end
        # the March clock change (Sun 29 Mar, 02:00 -> 03:00): window Sat 28 - Sun 29
        ev("ev-mar-across", "Spring Startup Hackathon", "2026-03-29T01:30", "2026-03-29T03:30", **g),
        ev("ev-mar-sat", "Spring Pitch Day", "2026-03-28", **g),
        ev("ev-mar-before", "Spring Friday Social", "2026-03-27T20:00", "2026-03-28T00:00", **g),
    ]  # fmt: skip


def rules_people() -> list[dict[str, Any]]:
    return [
        {"id": "p-ka-1", "name": "Kim Karl", "location": "Karlsruhe, DE", "next_action": "SUGGESTED: coffee"},
        {"id": "p-ka-2", "name": "Kai Rhein", "location": "karlsruhe", "next_action": "intro"},
        {"id": "p-ka-3", "name": "Kay Quiet", "location": "Karlsruhe"},  # no open action: no bonus
        {"id": "p-ka-4", "name": "Kit Fourth", "location": "Near Karlsruhe", "next_action": "call"},
        {"id": "p-ka-5", "name": "Kian Fifth", "location": "Karlsruhe", "next_action": "demo"},
        {"id": "p-muc", "name": "Mia Munich", "location": "München", "next_action": "lunch"},
        {"id": "p-zrh", "name": "Zoe Zurich", "location": "Zurich", "next_action": "visit"},
    ]


def rules_scout() -> dict[str, Any]:
    base = {"status": "NEW", "ev_class": "EV-A", "p_class": "P1", "why_it_matters": "dense founder room",
            "required_action": "register", "official_url": "https://scout.example.com/a"}  # fmt: skip
    return {
        "cycles": {},
        "items": [],
        "events": [
            {**base, "id": "se-1", "cycle_id": "c1", "event_name": "Robotics Hackathon Karlsruhe", "date": "2026-11-14", "event_id": "ev-hs|merged:Robotics Hackathon Karlsruhe"},
            {**base, "id": "se-2", "cycle_id": "c2", "event_name": "Robotics Hackathon Karlsruhe (demo area, Day 0)", "date": "2026-11-15", "p_class": "P2"},
            {**base, "id": "se-3", "cycle_id": "c2", "event_name": "Northern Founder Summit 2026", "date": "2026-12-02", "city": "Helsinki", "status": "MONITOR", "ev_class": "EV-B"},
            {**base, "id": "se-4", "cycle_id": "c3", "event_name": "Northern Founder Summit 2026 (side events)", "date": "2026-12-03", "city": "Espoo", "official_url": "UNKNOWN"},
            {**base, "id": "se-5", "cycle_id": "c3", "event_name": "Closed Pitch Day", "date": "2026-11-30", "status": "ADDED"},
            {**base, "id": "se-6", "cycle_id": "c3", "event_name": "Old Demo Day", "date": "2026-10-01"},
            {**base, "id": "se-7", "cycle_id": "c4", "event_name": "Undated Investor Day", "date": "UNKNOWN", "p_class": "P3"},
            {**base, "id": "se-8", "cycle_id": "c4", "event_name": "UNKNOWN", "date": "2026-11-30"},
            {**base, "id": "se-9", "cycle_id": "c4", "event_name": "Bad Date Forum", "date": "2026-13-45", "ev_class": "UNKNOWN"},
            {**base, "id": "se-10", "cycle_id": "c5", "event_name": "Founder Demo Day Alpha", "date": "2026-11-21", "status": "MONITOR"},
            {**base, "id": "se-11", "cycle_id": "c5", "event_name": "Western Pitch Day (side stage)", "date": "2026-12-05"},
            {**base, "id": "se-12", "cycle_id": "c6", "event_name": "Western Pitch Day", "date": "2026-12-05", "p_class": "P2"},
            {**base, "id": "se-13", "cycle_id": "c6", "event_name": "Incubator Retreat", "date": "2026-11-16"},
            {**base, "id": "se-14", "cycle_id": "c6", "event_name": "Hackathon", "date": "2026-11-14"},
        ],
    }  # fmt: skip


def rules_files() -> dict[str, Any]:
    return {
        "events.json": {"events": rules_events(), "leads": [
            {"id": "evlead-1", "title": "Robotics meetup", "decision": "new", "date": "2026-12-03"},
            {"id": "evlead-2", "title": "Dismissed thing", "decision": "dismissed"},
            {"id": "evlead-3", "title": "Converted thing", "decision": "converted"},
            {"id": "evlead-4", "title": "Another new", "decision": "new"},
        ]},
        "event_sources.json": {"sources": [{"id": "src-zrh", "city": "Zürich", "kind": "jsonld"}, {"id": "src-x", "city": "Paris"}, "junk"]},
        "event_health.json": {"scan_time": "2026-11-10 08:00", "totals": {"review": 3}, "sources": [
            {"name": "A", "kind": "luma"}, {"name": "B", "kind": "luma"}, {"name": "C", "kind": "ics"},
            {"name": "D", "kind": "watcher"}, {"name": "E", "kind": "other"}]},
        "scout_intake.json": rules_scout(),
        "people.json": {"people": rules_people()},
    }  # fmt: skip


def old_crash_files(case: str) -> dict[str, Any]:
    """A value the old code crashed on (intentional difference, review 015): the new side reads it as no date."""
    bad = {
        "int_start": ev(
            "ev-int", "Founder Demo Day", 20261121, **_GOOD
        ),  # old parse_when: 'int'.strip -> the page 500s
        "time_24": ev("ev-24", "Midnight Hack Day", "2026-11-21", "2026-11-21T24:00", **_GOOD),  # old event_span raises
    }[case]
    return {"events.json": {"events": [bad, ev("ev-fine", "Founder Pitch Night", "2026-11-21", **_GOOD)], "leads": []}}


def many_leads_files() -> dict[str, Any]:
    leads = [
        {"id": f"evlead-{i:03d}", "title": f"Lead {i}", "decision": ("new", "dismissed", "converted")[i % 3]}
        for i in range(300)
    ]
    return {"events.json": {"events": [ev("ev-one", "Founder Demo Day", "2026-11-20", **_GOOD)], "leads": leads}}


SUGGEST = [
    {"name": "AI Hackathon at KIT", "type": "hackathon", "city": "Karlsruhe"},
    {"name": "Alumni reunion info session", "organizer": "ETH"},
    {"name": "Founders build night", "organizer": "TUM", "city": "Munich"},
    {"type": "vc", "city": "Berlin"},
    {"name": "Defense robotics founders summit", "city": "Paris"},
    {"name": "Machine learning meetup", "city": "Nowhere"},
    {"name": "Quiet evening", "city": "Helsinki"},
    {},
]


def goldens_input() -> dict[str, Any]:
    sets = [
        {"name": "rules", "files": rules_files()},
        {"name": "empty", "files": {}},
        {"name": "many_leads", "files": many_leads_files()},
        {"name": "old_crash_int_start", "files": old_crash_files("int_start")},
        {"name": "old_crash_time_24", "files": old_crash_files("time_24")},
    ]
    weekends = {c: weekends_for(c) for c in CLOCKS}
    for c in CLOCKS:
        weekends[c] += [["2026-10-24", "2026-10-25"], ["2026-03-28", "2026-03-29"], ["bad", "window"],
                        ["2026-11-15", "2026-11-14"]]  # fmt: skip
    return {"clocks": list(CLOCKS), "sets": sets, "wsig_days": list(GOLDEN_WSIG_DAYS), "weekends": weekends,
            "suggest": SUGGEST}  # fmt: skip


# ------------------------------------------------------------------ the new side
def _try(fn: Any) -> Any:
    try:
        return {"ok": js(fn())}
    except Exception as exc:
        return {"raises": type(exc).__name__}


def data_of(files: Mapping[str, Any]) -> EventsData:
    """``EventsData`` from the old files, as the importer + ``store.load`` would give it (no pins)."""
    doc = files.get("events.json") or {}
    scout_doc = files.get("scout_intake.json")
    documents = {k: files[k] for k in ("event_sources.json", "event_health.json") if k in files}
    if scout_doc is not None:
        documents["scout_intake.json#rest"] = {k: v for k, v in scout_doc.items() if k not in ("cycles", "items")}
    return EventsData(
        events=[e for e in doc.get("events", []) if isinstance(e, dict)],
        leads=[x for x in doc.get("leads", []) if isinstance(x, dict)],
        documents=documents,
        people=people_view.records((files.get("people.json") or {}).get("people", [])),
    )


def new_reads(data: EventsData, clock: str, inp: Mapping[str, Any]) -> dict[str, Any]:
    today = view.berlin_today(utc_instant(clock))
    windows = inp.get("weekends", {}).get(clock, [])
    return {
        "events": _try(lambda: view.events_payload(data, today)),
        "health": _try(data.health),
        "wsig": {str(d): _try(lambda d=d: view.wsig_payload(data, today, d)["ranked"]) for d in inp["wsig_days"]},
        "weekend": {
            f"{a}|{b}": _try(lambda a=a, b=b: view.weekend_payload(data, today, a, b)["missions"]) for a, b in windows
        },
    }


def new_goldens(inp: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"sets": {}}
    for s in inp["sets"]:
        data = data_of(s["files"])
        out["sets"][s["name"]] = {c: new_reads(data, c, inp) for c in inp["clocks"]}
    out["suggest"] = [_try(lambda b=b: engine.suggest(b)) for b in inp["suggest"]]
    return out


OLD_CRASH_SETS = ("old_crash_int_start", "old_crash_time_24")


def _crash_differences(old: Any, new: Any, path: str) -> list[str]:
    """In an old-crash set, the ONLY allowed difference is: the old code raised, the new code answered."""
    if isinstance(old, dict) and set(old) == {"raises"}:
        return [] if isinstance(new, dict) and "ok" in new else [f"{path}: old raised, new did not answer"]
    if isinstance(old, dict) and isinstance(new, dict) and set(old) != {"ok"}:
        return [p for k in sorted(old) for p in _crash_differences(old[k], new.get(k), f"{path}/{k}")]
    return diff(old, new, path)


def compare_goldens(golden: Mapping[str, Any]) -> list[str]:
    expected = js({k: v for k, v in golden["expected"].items() if k != "meta"})
    got = js(new_goldens(golden["input"]))
    crash_old = {n: expected["sets"].pop(n) for n in OLD_CRASH_SETS}
    crash_new = {n: got["sets"].pop(n) for n in OLD_CRASH_SETS}
    problems = diff(expected, got)
    for name in OLD_CRASH_SETS:
        problems += _crash_differences(crash_old[name], crash_new[name], f"/sets/{name}")
    return problems


def write_goldens() -> int:
    inp = goldens_input()
    oracle = run_oracle(inp)
    meta = oracle.pop("meta")
    golden = {"provenance": {**meta, "clocks": list(CLOCKS)}, "input": inp, "expected": oracle}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    problems = compare_goldens(golden)
    counts = {
        name: {c: len((v["events"].get("ok") or {}).get("events", [])) for c, v in per.items()}
        for name, per in oracle["sets"].items()
    }
    print(json.dumps({"golden": str(GOLDEN), "events_per_clock": counts, "old": meta}, indent=2))
    for p in problems[:60]:
        print("  DIFF", p)
    print("EVENTS GOLDENS MATCH" if not problems else f"EVENTS GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


# ------------------------------------------------------------------ the real snapshot
def _ids(body: Any) -> list[Any]:
    return [e.get("id") for e in ((body or {}).get("ok") or {}).get("events", [])]


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot.files()}
    weekends = {c: weekends_for(c) for c in REAL_CLOCKS}
    inp = {"clocks": list(REAL_CLOCKS), "sets": None, "wsig_days": list(WSIG_DAYS), "weekends": weekends}
    old = run_oracle(inp, files)["sets"]["data"]

    schema = "pz_verify_" + _secrets.token_hex(4)
    admin = connect(settings.db_url, autocommit=True)
    problems: list[str] = []
    report: dict[str, Any] = {"schema_prefix": "pz_verify_", "clocks": list(REAL_CLOCKS)}
    try:
        admin.execute(_scratch_sql(schema).encode())
        with transaction(settings.db_url) as conn:
            applied = apply_plan(build_plan(snapshot), schema=schema, conn=conn)
        if not applied.get("applied"):
            raise SystemExit(f"import into the scratch schema failed: {applied}")
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for clock in REAL_CLOCKS:
                app.state.clock = lambda clock=clock: utc_instant(clock)
                got: dict[str, Any] = {
                    "events": {"ok": client.get("/api/events").json()},
                    "health": {"ok": client.get("/api/events/health").json()},
                    "wsig": {str(d): {"ok": client.get(f"/api/events/wsig?days={d}").json()["ranked"]} for d in WSIG_DAYS},
                    "weekend": {
                        f"{a}|{b}": {"ok": client.get(f"/api/events/weekend?start={a}&end={b}").json()["missions"]}
                        for a, b in weekends[clock]
                    },
                }  # fmt: skip
                d = diff(js(old[clock]), js(got), f"@{clock}")
                problems += d
                ev_old = (old[clock]["events"].get("ok") or {}).get("events", [])
                groups: dict[str, int] = {}
                for e in ev_old:
                    groups[e["when"]["group"]] = groups.get(e["when"]["group"], 0) + 1
                report[clock] = {
                    "events": len(ev_old),
                    "groups": dict(sorted(groups.items())),
                    "id_order_equal": _ids(old[clock]["events"]) == _ids(got["events"]),
                    "wsig": {k: len(v.get("ok") or []) for k, v in got["wsig"].items()},
                    "weekend_missions": {k: len(v.get("ok") or []) for k, v in got["weekend"].items()},
                    "scout_reports": len((got["events"]["ok"] or {}).get("scout_reports", [])),
                    "differences": len(d),
                }
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2, default=str))
    for p in problems[:60]:
        print("  DIFF", p)
    print("EVENTS READ PARITY PASSED" if not problems else "EVENTS READ PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    if argv[1:] == ["real"]:
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
