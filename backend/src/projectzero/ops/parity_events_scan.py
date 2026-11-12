"""Event source scan parity: the port against the OLD ``event_sources.scan()`` as oracle, with recorded responses on
both sides and a FIXED clock (review 017). Nothing touches the network.

    python -m projectzero.ops.parity_events_scan goldens   # (re)generate tests/fixtures/golden_v1/oracle_events_scan.json
    python -m projectzero.ops.parity_events_scan real      # the real registry + data, recorded responses, the route

The oracle replaces the old ``connectors._get_raw`` (the old tests' hook) with the recorded responses; the new side
uses ``RecordedFetcher`` with the SAME responses (an unknown URL raises ``ConnectionError("no recorded response")``
on both sides, so a failing source has the same note).

``goldens``: one synthetic set (synthetic names; example.com hosts) through the PURE path (``registry.prepare`` ->
``_fetch_all`` -> ``compute``), compared with the old scan: the health document (``seconds`` removed: wall time), the
events and leads after the scan, the registry and every watcher baseline. It covers JSON-LD (@graph, ItemList,
offers, a place, online mode, a past event, a nameless item, the same event from two sources, the merge into an
existing event), the Luma secondary route (with and without ``__NEXT_DATA__``), ICS (folded lines, VALUE=DATE, a past
and a nameless VEVENT), the Devpost API (location object / string, a non-JSON answer), watchers (a first scan with a
title + date pair and a past year; an archived baseline with one new line), config-required sources, a timeout, the
STATION F repair and the newly offered default sources.

Intentional differences (asserted in the unit tests, not here): an EMPTY saved baseline is a baseline (H-113), leads
are never trimmed to 250 (decision b), a lead id repeated within one scan is added once (the table's key).

``real`` imports the snapshot into a throw-away schema and runs ``POST /api/events/find`` with a recorded fetcher built
from the REAL registry (synthetic pages per source kind); the old scan runs on a copy of the same snapshot. Compared:
the health (without ``seconds``), the events and leads after the scan, the registry and the baselines.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.events import registry
from projectzero.events.collectors import uid
from projectzero.events.scan import Fetched, _fetch_all, compute, registry_cities
from projectzero.events.when import BERLIN
from projectzero.ops.parity_events_read import run_oracle, utc_instant
from projectzero.ops.parity_ranking import GOLDEN_DIR, diff, js

GOLDEN = GOLDEN_DIR / "oracle_events_scan.json"
CLOCK = "2026-11-20T10:00:00"


class RecordedFetcher:
    def __init__(self, responses: Mapping[str, Mapping[str, Any]]) -> None:
        self.responses = responses
        self.asked: list[str] = []

    def get_text(self, url: str) -> str:
        self.asked.append(url)
        r = self.responses.get(url)
        if r is None:
            raise ConnectionError("no recorded response")
        if "error" in r:
            raise {"TimeoutError": TimeoutError, "ConnectionError": ConnectionError, "ValueError": ValueError}[
                r["error"]
            ](r.get("message", ""))
        return str(r["text"])


def _ld(*objs: Any) -> str:
    return "".join(f'<script type="application/ld+json">{json.dumps(o)}</script>' for o in objs)


def corpus() -> tuple[dict[str, Any], dict[str, Any]]:
    """(files, responses) of the synthetic set."""
    place = {"@type": "Place", "name": "Hall A", "address": {"addressLocality": "Karlsruhe", "addressCountry": "DE",
                                                             "streetAddress": "Main St 1"}}  # fmt: skip
    a = (
        _ld(
            {
                "@graph": [
                    {
                        "@type": "Event",
                        "name": "Robotics Builders Night",
                        "startDate": "2026-12-04T18:00",
                        "location": place,
                        "offers": {
                            "price": "0",
                            "priceCurrency": "EUR",
                            "availability": "https://schema.org/InStock",
                            "url": "https://a.example.com/rsvp",
                        },
                        "organizer": {"name": "Example Founders Lab"},
                        "description": "For founders and engineers building robots.",
                    },
                    {"@type": "Event", "name": "Old Pitch Day", "startDate": "2026-10-01"},
                    {"@type": "Event", "name": "Same Day Founder Lunch", "startDate": "2026-11-20T12:00"},
                    {"@type": "Event", "startDate": "2026-12-05"},
                ]
            },
            {
                "@type": "ItemList",
                "itemListElement": [
                    {
                        "item": {
                            "@type": ["Event", "Thing"],
                            "name": "Hackathon Weekend Alpha",
                            "startDate": "2026-12-12",
                            "eventAttendanceMode": "https://schema.org/OnlineEventAttendanceMode",
                        }
                    }
                ],
            },
        )
        + '<script type="application/ld+json">{not json</script>'
    )
    b = _ld(
        {
            "@type": "Event",
            "name": "Robotics Builders Night 2026",
            "startDate": "2026-12-04",
            "location": {"name": "Hall A"},
        },
        {
            "@type": "SocialEvent",
            "name": "AI Founder Breakfast",
            "startDate": "2026-12-06T08:30",
            "location": {"@type": "Place", "name": "Other Hall", "address": "Kaiserstr 12, Karlsruhe"},
            "keywords": ["ai", "founders"],
        },
    )
    next_data = {"props": {"pageProps": {"initialData": {"events": [
        {"name": "Luma Demo Night", "start_at": "2026-12-10T19:00:00Z", "url": "demo-night",
         "description_mirror": {"text": "Founders  demo\\n their startups"}},
        {"name": "Luma Demo Night", "start_at": "2026-12-10T19:00:00Z"},
        {"name": "Luma Robotics Social", "startAt": "2026-12-14", "api_id": "evt-123", "audience": "builders"},
    ]}}}}  # fmt: skip
    luma = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script></html>'
    ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nSUMMARY:ICS Founder Meetup with a very long title that is fol\r\n ded\r\n"
           "DTSTART;VALUE=DATE:20261215\r\nLOCATION:Stuttgart Hub\r\nURL:https://ics.example.com/e1\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nSUMMARY:ICS Past Meetup\r\nDTSTART:20261001T100000Z\r\nEND:VEVENT\r\n"
           "BEGIN:VEVENT\r\nDTSTART:20261216\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")  # fmt: skip
    devpost = json.dumps({"hackathons": [
        {"title": "Devpost Robotics Hack", "url": "https://devpost.example.com/r", "displayed_location": {"location": "Munich, Germany"},
         "submission_period_dates": "Dec 01 - 03, 2026"},
        {"title": "Devpost Online Jam", "displayed_location": "Online", "submission_period_dates": "Jan 10 - 12, 2027"},
    ]})  # fmt: skip
    w1 = ("<html><nav>Home Events About</nav><h1>Community events</h1><p>Founder Pitch Night on 12.12.2026</p>"
          "<p>Our hackathon in 2019 was great</p><p>Spring Venture Summit</p><p>Dec 18, 2026, 6:00 PM</p>"
          "<p>Weekly newsletter for builders</p><p>Robotics Builders Night 04.12.2026</p><footer>Imprint</footer></html>")  # fmt: skip
    w2 = "<html><p>Startup Meetup on 2026-12-20</p><p>Founders breakfast every Friday</p><p>Contact us today</p></html>"
    stationf = "<html><p>STATION F Demo Day 2026-12-03</p><p>Visit the campus</p></html>"
    sources = [
        {"id": "s-a", "name": "Example A events", "kind": "jsonld", "url": "https://a.example.com/events", "city": "Karlsruhe", "organizer": "UNKNOWN"},
        {"id": "s-b", "name": "Example B calendar", "kind": "jsonld", "url": "https://b.example.com/cal", "city": "Karlsruhe"},
        {"id": "s-luma", "name": "Luma Example City", "kind": "luma", "url": "https://lu.example.com/city", "city": "Berlin", "organizer": "Luma Org"},
        {"id": "s-luma-empty", "name": "Luma Empty", "kind": "luma", "url": "https://lu2.example.com/x", "city": "Munich"},
        {"id": "s-ics", "name": "ICS Example", "kind": "ics", "url": "https://ics.example.com/feed.ics", "city": "", "type": "founder_meetup"},
        {"id": "s-ics-unset", "name": "ICS Unset", "kind": "ics", "url": "", "requires_config": "Paste an ICS link."},
        {"id": "s-opt", "name": "Optional Token API", "kind": "optional", "url": "https://opt.example.com", "requires_config": "Token not configured."},
        {"id": "s-api", "name": "Devpost Example", "kind": "api", "url": "https://api.example.com/hackathons", "organizer": "Devpost"},
        {"id": "s-api-bad", "name": "Broken API", "kind": "api", "url": "https://api2.example.com/bad"},
        {"id": "s-w1", "name": "Watcher One", "kind": "watcher", "url": "https://w.example.com/events", "city": "Karlsruhe"},
        {"id": "s-w2", "name": "Watcher Two", "kind": "watcher", "url": "https://w2.example.com/", "city": "Paris", "type": "community"},
        {"id": "ev-stationf", "name": "Station F", "kind": "jsonld", "url": "https://stationf.co/events", "city": "Paris"},
        {"id": "s-down", "name": "Down Source", "kind": "jsonld", "url": "https://down.example.com/"},
        {"id": "s-weird", "name": "Weird Kind", "kind": "telepathy", "url": "https://x.example.com/"},
    ]  # fmt: skip
    files = {
        "event_sources.json": {"sources": sources},  # no offered_defaults: the new default sources are offered
        "event_health.json": {"scan_time": "2026-11-19 08:00", "totals": {}, "sources": [{"id": "s-a", "last_ok": "2026-11-19 08:00"}]},
        "events.json": {
            "events": [{"id": "ev-ai-founder-breakfast-2026-12-06", "name": "AI Founder Breakfast", "start": "2026-12-06T08:30",
                        "city": "Karlsruhe", "venue": "Original Hall", "status": "planned", "sources": []}],
            "leads": [{"id": "evlead-existing", "title": "Founder Pitch Night", "date": "2026-12-12", "decision": "new"}],
        },
        f".watch/ev-{uid('https://w2.example.com/')}.json": ["Founders breakfast every Friday", "Contact us today"],
    }  # fmt: skip
    responses: dict[str, Any] = {
        "https://a.example.com/events": {"text": a},
        "https://b.example.com/cal": {"text": b},
        "https://lu.example.com/city": {"text": luma},
        "https://lu2.example.com/x": {"text": "<html>nothing here</html>"},
        "https://ics.example.com/feed.ics": {"text": ics},
        "https://api.example.com/hackathons": {"text": devpost},
        "https://api2.example.com/bad": {"text": "<html>not json</html>"},
        "https://w.example.com/events": {"text": w1},
        "https://w2.example.com/": {"text": w2},
        "https://stationf.co/events": {"text": stationf},
        "https://down.example.com/": {"error": "TimeoutError", "message": "timed out"},
    }
    return files, responses


# ------------------------------------------------------------------ the new side (pure)
def _strip_seconds(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _strip_seconds(v) for k, v in o.items() if k != "seconds"}
    if isinstance(o, list):
        return [_strip_seconds(v) for v in o]
    return o


def new_scan(files: Mapping[str, Any], responses: Mapping[str, Any], clock: str) -> dict[str, Any]:
    now = utc_instant(clock)
    reg = registry.prepare(files.get("event_sources.json"), now)
    prev: dict[str, Any] = {
        str(s.get("id")): s
        for s in ((files.get("event_health.json") or {}).get("sources") or [])
        if isinstance(s, dict)
    }
    baselines = {}
    for s in reg.sources:
        if s.get("kind") == "watcher":
            seeded = files.get(f".watch/ev-{uid(str(s.get('url', '')))}.json")
            if isinstance(seeded, list):
                baselines[s["id"]] = {"lines": seeded, "seeded_from": "archive"}
    fetched: list[Fetched] = _fetch_all(reg.sources, prev, baselines, RecordedFetcher(responses), now, float("inf"),
                                        lambda: 0.0)  # fmt: skip
    doc = files.get("events.json") or {}
    events = [e for e in doc.get("events", []) if isinstance(e, dict)]
    leads = [x for x in doc.get("leads", []) if isinstance(x, dict)]
    today = now.astimezone(BERLIN).date()
    plan = compute(fetched, events, leads, registry_cities(reg), {}, now, today, 0.0)
    after = [plan.merged.get(str(e.get("id")), e) for e in events] + plan.created
    watch = {}
    for s in reg.sources:  # the baselines the old .watch folder would hold after the scan
        if s.get("kind") == "watcher":
            key = f".watch/ev-{uid(str(s.get('url', '')))}.json"
            new = next((lines for src, lines in plan.snapshots if src["id"] == s["id"]), None)
            if new is not None:
                watch[key] = new
            elif key in files:
                watch[key] = files[key]
    return {"health": {"ok": plan.health}, "events": after, "leads": plan.leads + leads,
            "event_sources": reg.document, "watch": dict(sorted(watch.items()))}  # fmt: skip


def compare(old: Mapping[str, Any], new: Mapping[str, Any], where: str) -> list[str]:
    return diff(js(_strip_seconds(old)), js(_strip_seconds(new)), where)


def write_goldens() -> int:
    files, responses = corpus()
    inp = {"clock": CLOCK, "responses": responses, "sets": [{"name": "synthetic", "files": files}]}
    oracle = run_oracle(inp, mode="scan")
    meta = oracle.pop("meta")
    golden = {"provenance": {**meta, "clock": CLOCK}, "input": inp, "expected": oracle}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    problems = compare(oracle["sets"]["synthetic"], new_scan(files, responses, CLOCK), "/synthetic")
    totals = ((oracle["sets"]["synthetic"]["health"].get("ok") or {}).get("totals")) or {}
    print(json.dumps({"golden": str(GOLDEN), "old": meta, "totals": _strip_seconds(totals)}, indent=1))
    for p in problems[:60]:
        print("  DIFF", p)
    print("EVENT SCAN GOLDENS MATCH" if not problems else f"EVENT SCAN GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def compare_goldens(golden: Mapping[str, Any]) -> list[str]:
    inp = golden["input"]
    files = inp["sets"][0]["files"]
    return compare(
        golden["expected"]["sets"]["synthetic"], new_scan(files, inp["responses"], inp["clock"]), "/synthetic"
    )


# ------------------------------------------------------------------ the real snapshot
def real_responses(sources: list[dict[str, Any]]) -> dict[str, Any]:
    """A synthetic page per REAL source, by kind (no network): one future event each, plus a watcher line."""
    out: dict[str, Any] = {}
    for i, s in enumerate(sources):
        url, kind, day = str(s.get("url") or ""), s.get("kind"), f"2026-12-{(i % 20) + 5:02d}"
        if not url:
            continue
        if kind in ("jsonld", "luma"):
            out[url] = {"text": _ld({"@type": "Event", "name": f"Replay Event {i} Founders", "startDate": f"{day}T18:00",
                                     "location": {"@type": "Place", "name": "Replay Hall", "address": {"addressLocality": s.get("city") or "Berlin"}}})}  # fmt: skip
        elif kind == "ics":
            out[url] = {
                "text": f"BEGIN:VEVENT\nSUMMARY:Replay ICS {i}\nDTSTART:{day.replace('-', '')}\nURL:{url}\nEND:VEVENT\n"
            }
        elif kind == "api":
            out[url] = {
                "text": json.dumps(
                    {"hackathons": [{"title": f"Replay Hack {i}", "submission_period_dates": "Dec 10 - 12, 2026"}]}
                )
            }
        elif kind == "watcher":
            out[url] = {"text": f"<p>Replay Startup Meetup {i} on {day}</p><p>About this page</p>"}
    return out


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.events import store
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot.files()}
    reg = registry.prepare(snapshot.json("event_sources.json", None), utc_instant(CLOCK))
    responses = real_responses(reg.sources)
    old = run_oracle({"clock": CLOCK, "responses": responses, "sets": [{"name": "data", "files": None}]}, files,
                     mode="scan")["sets"]["data"]  # fmt: skip
    schema = "pz_verify_" + _secrets.token_hex(4)
    admin = connect(settings.db_url, autocommit=True)
    problems: list[str] = []
    try:
        admin.execute(_scratch_sql(schema).encode())
        with transaction(settings.db_url) as conn:
            applied = apply_plan(build_plan(snapshot), schema=schema, conn=conn)
        if not applied.get("applied"):
            raise SystemExit(f"import into the scratch schema failed: {applied}")
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: utc_instant(CLOCK)
        app.state.events_fetcher = RecordedFetcher(responses)
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            r = client.post("/api/events/find", json={})
        with transaction(settings.db_url) as conn:
            data = store.load(conn, schema, datetime.fromisoformat(CLOCK).date(), people=False)
            docs: dict[str, Any] = dict(conn.execute(_sql.SQL("select key, body from {}.documents where key = 'event_sources.json'").format(_sql.Identifier(schema))).fetchall())  # fmt: skip
            snaps = conn.execute(_sql.SQL("select url, lines from {}.event_watch_snapshots").format(_sql.Identifier(schema))).fetchall()  # fmt: skip
        watched: dict[str, Any] = dict(sorted((f".watch/ev-{uid(u)}.json", lines) for u, lines in snaps))
        new = {"health": {"ok": r.json()["health"]}, "events": data.events, "leads": data.leads,
               "event_sources": docs.get("event_sources.json"),
               "watch": dict(sorted((f".watch/ev-{uid(u)}.json", lines) for u, lines in snaps))}  # fmt: skip
        old_watch = {
            k: v
            for k, v in old["watch"].items()
            if k in watched
            or k in {f".watch/ev-{uid(str(s.get('url', '')))}.json" for s in reg.sources if s.get("kind") == "watcher"}
        }
        problems = compare({**old, "watch": old_watch}, new, "/real")
        print(json.dumps({"status": r.status_code, "totals": _strip_seconds(r.json()["health"]["totals"])}, indent=1))
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    for p in problems[:60]:
        print("  DIFF", p)
    print("EVENT SCAN REAL PARITY PASSED" if not problems else f"EVENT SCAN REAL PARITY FAILED ({len(problems)})")
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
