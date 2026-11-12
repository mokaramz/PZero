"""The Events read routes offline (the store faked) and the review 015 decisions: one Berlin clock per request, the
persisted year of a free-text date, the old crashes answered, the weekend window boundaries."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from projectzero.api.app import create_app
from projectzero.api.routers import events as router
from projectzero.core.config import Settings
from projectzero.events import engine, store, view
from projectzero.events.columns import event_columns
from projectzero.events.store import EventsData
from projectzero.events.when import BERLIN
from projectzero.ops.parity_events_read import data_of, rules_files, utc_instant

UNREACHABLE = Settings(db_url="postgresql://nobody:nothing@127.0.0.1:1/none")


@pytest.fixture
def rules() -> EventsData:
    return data_of(rules_files())


def make_client(
    monkeypatch: pytest.MonkeyPatch, data: EventsData, instant: datetime
) -> tuple[TestClient, dict[str, Any]]:
    monkeypatch.delenv("PZ_AUTH_TOKEN", raising=False)
    seen: dict[str, Any] = {}

    @contextmanager
    def fake_tx(_url: str) -> Iterator[None]:
        seen["read_only"] = True
        yield None

    def fake_load(_conn: Any, _schema: str, today: date, *, people: bool = True, records: bool = True) -> EventsData:
        seen["today"], seen["people"] = today, people
        if not records:
            seen["records"] = False
        return data

    monkeypatch.setattr(router, "read_only_transaction", fake_tx)
    monkeypatch.setattr(store, "load", fake_load)
    app = create_app(UNREACHABLE)
    app.state.clock = lambda: instant
    return TestClient(app, base_url="http://127.0.0.1:8177"), seen


# ── one Berlin clock per request ────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("instant", "today", "window"),
    [
        (datetime(2026, 11, 13, 22, 59, 59, tzinfo=UTC), "2026-11-13", ["2026-11-14", "2026-11-15"]),  # Fri 23:59:59
        (datetime(2026, 11, 13, 23, 0, 0, tzinfo=UTC), "2026-11-14", ["2026-11-14", "2026-11-15"]),  # Sat 00:00 Berlin
        (datetime(2026, 11, 15, 22, 59, 0, tzinfo=UTC), "2026-11-15", ["2026-11-14", "2026-11-15"]),  # Sun 23:59
        (datetime(2026, 11, 15, 23, 0, 0, tzinfo=UTC), "2026-11-16", ["2026-11-21", "2026-11-22"]),  # Mon 00:00
        (datetime(2026, 3, 28, 23, 0, 0, tzinfo=UTC), "2026-03-29", ["2026-03-28", "2026-03-29"]),  # CET midnight
        (datetime(2026, 3, 29, 22, 0, 0, tzinfo=UTC), "2026-03-30", ["2026-04-04", "2026-04-05"]),  # CEST midnight
    ],
)
def test_the_berlin_date_of_the_request_instant_decides_today_and_the_window(
    monkeypatch: pytest.MonkeyPatch, rules: EventsData, instant: datetime, today: str, window: list[str]
) -> None:
    client, seen = make_client(monkeypatch, rules, instant)
    body = client.get("/api/events").json()
    assert (body["today"], body["weekend_window"]) == (today, window)
    assert seen == {"read_only": True, "today": date.fromisoformat(today), "people": False}
    for e in body["events"]:
        assert e["when"].get("weekend_window", window) == window  # every event used the SAME date


def test_the_event_package_never_reads_the_machine_clock() -> None:
    """The old code read ``date.today()`` (the machine's date) in WSIG, the weekend planner and ``extract_date``."""
    root = Path(engine.__file__).parent
    for path in [*root.glob("*.py"), Path(router.__file__)]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner, attr = ast.unparse(node.func.value), node.func.attr
                assert (owner, attr) != ("date", "today"), path.name
                if (owner, attr) == ("datetime", "now"):
                    assert [ast.unparse(a) for a in node.args] == ["BERLIN"], path.name  # the request instant only


def test_the_tz_database_is_present() -> None:
    assert str(BERLIN) == "Europe/Berlin" and datetime(2026, 7, 1, tzinfo=BERLIN).utcoffset() is not None


def test_a_naive_instant_is_berlin_wall_time() -> None:
    assert view.berlin_today(datetime(2026, 11, 14, 0, 30)) == date(2026, 11, 14)
    assert view.berlin_today(utc_instant("2026-11-14T00:30:00")) == date(2026, 11, 14)


# ── the persisted year of a free-text date (Codex H-101) ────────────────────────────────────────────────────────
def test_a_yearless_date_keeps_the_year_it_was_stored_with() -> None:
    """Imported in August ("Sept 20" -> 2026-09-20), read in October: the old page re-read the words with October's
    date and moved the event to 2027-09-20; here the persisted date decides, and the raw wording stays."""
    record = {"id": "ev-a", "name": "Founder Mixer", "start": "Sept 20", "city": "Karlsruhe"}
    row = {"start_date": date(2026, 9, 20), "end_date": None}
    october = date(2026, 10, 10)
    pins = {"ev-a": store.pins_of(record, row)}
    assert pins == {"ev-a": {"start": date(2026, 9, 20)}}
    (pinned,) = engine.listing([record], october, pins=pins)
    (reread,) = engine.listing([record], october)  # the old behaviour
    assert (pinned["when"]["start_date"], pinned["when"]["group"], pinned["past"]) == ("2026-09-20", "past", True)
    assert (reread["when"]["start_date"], reread["when"]["group"]) == ("2027-09-20", "later")
    assert pinned["start"] == "Sept 20"  # the wording is displayed as stated


def test_the_listing_sorts_a_pinned_event_by_its_persisted_date() -> None:
    """The raw string "Aug 30" sorts after "2026-09-01" ('A' > '2'); its persisted date sorts it first."""
    events = [{"id": "ev-iso", "name": "B", "start": "2026-09-01"}, {"id": "ev-free", "name": "A", "start": "Aug 30"}]
    pins: dict[str, engine.Pins] = {"ev-free": {"start": date(2026, 8, 30)}}
    assert [e["id"] for e in engine.listing(events, date(2026, 8, 1), pins=pins)] == ["ev-free", "ev-iso"]


def test_only_free_text_is_pinned() -> None:
    row = {"start_date": date(2026, 9, 20), "end_date": date(2026, 9, 21)}
    assert store.pins_of({"start": "2026-09-20", "end": "21.09.2026"}, row) == {}
    assert store.pins_of({"start": "20 September", "end": "Sept 21"}, row) == {
        "start": date(2026, 9, 20),
        "end": date(2026, 9, 21),
    }
    assert store.pins_of({"start": "Sept 20"}, {"start_date": None}) == {"start": None}  # stored as no date
    assert store.pins_of({"start": "TBA", "end": ""}, {"start_date": None, "end_date": None}) == {"start": None}


def _imported(record: dict[str, Any], imported_on: date) -> dict[str, Any]:
    """The stored date columns of ``record``, as the importer computed them on ``imported_on``."""
    c = event_columns(record["id"], record, today=imported_on).columns
    return {"start_date": c["start_date"], "end_date": c["end_date"]}


LEAP = {"id": "ev-leap", "name": "Leap Founder Night", "start": "Feb 29", "end": "Feb 29", "city": "Karlsruhe",
        "status": "planned"}  # fmt: skip


@pytest.mark.parametrize(
    ("imported_on", "read_on", "stored", "effective", "group", "reread"),
    [
        # stored in a leap year, read in the next (non-leap) year: re-reading would LOSE the date
        (date(2024, 1, 15), date(2025, 1, 10), date(2024, 2, 29), "2024-02-29", "past", ""),
        # stored as NO date in a non-leap year, read in a leap year: re-reading would GAIN a date
        (date(2025, 1, 15), date(2028, 1, 10), None, "", "undated", "2028-02-29"),
    ],
)
def test_a_feb_29_keeps_its_stored_result_across_years(
    imported_on: date, read_on: date, stored: date | None, effective: str, group: str, reread: str
) -> None:
    row = _imported(LEAP, imported_on)
    assert row == {"start_date": stored, "end_date": stored}
    pins = {"ev-leap": store.pins_of(LEAP, row)}
    assert pins == {"ev-leap": {"start": stored, "end": stored}}  # a NULL result is kept, for both sides
    (e,) = engine.listing([LEAP], read_on, pins=pins)
    assert (e["start"], e["end"]) == ("Feb 29", "Feb 29")  # the wording is displayed as stated
    assert (e["when"]["start_date"], e["when"]["group"]) == (effective, group)
    (old,) = engine.listing([LEAP], read_on)  # what re-reading with the read date said
    assert old["when"]["start_date"] == reread


def test_the_planners_use_the_stored_span_of_a_feb_29() -> None:
    # stored 2024-02-29 (imported in a leap year): its span overlaps that day, whatever year it is read in
    kept = {"ev-leap": store.pins_of(LEAP, _imported(LEAP, date(2024, 1, 15)))}
    assert engine.overlaps(LEAP, "2024-02-28", "2024-02-29", date(2025, 1, 10), kept["ev-leap"]) is True
    assert engine.overlaps(LEAP, "2024-02-28", "2024-02-29", date(2025, 1, 10)) is False  # re-read: no date
    # stored as no date (imported in 2025): a leap-year read must not put it in the weekend plan or WSIG
    none = {"ev-leap": store.pins_of(LEAP, _imported(LEAP, date(2025, 1, 15)))}
    read_on = date(2028, 1, 10)
    data = EventsData([LEAP], [], pins=dict(none))
    assert view.weekend_payload(data, read_on, "2028-02-28", "2028-02-29")["missions"] == []
    assert view.wsig_payload(data, read_on, 60)["ranked"] == []
    reread = EventsData([LEAP], [])
    planned = view.weekend_payload(reread, read_on, "2028-02-28", "2028-02-29")["missions"]
    assert [p["what"] for m in planned for p in m["plan"]] == ["Leap Founder Night"]  # the bug Codex reproduced


def test_a_pinned_date_also_decides_the_weekend_and_wsig() -> None:
    record = {"id": "ev-a", "name": "Robotics Hackathon", "start": "Oct 24", "city": "Karlsruhe", "status": "planned"}
    pins: dict[str, engine.Pins] = {"ev-a": {"start": date(2026, 10, 24)}}
    today = date(2026, 10, 23)
    data = EventsData([record], [], pins=dict(pins))
    missions = view.weekend_payload(data, today, "2026-10-24", "2026-10-25")["missions"]
    assert [p["what"] for m in missions for p in m["plan"]] == ["Robotics Hackathon"]
    ranked = view.wsig_payload(data, today, 7)["ranked"]
    assert [r["id"] for r in ranked] == ["ev-a"] and ranked[0]["start"] == "2026-10-24"


# ── values the old code crashed on ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw", [20261121, ["2026-11-21"], {"d": 1}, 3.5, True])
def test_a_non_text_date_is_no_date_for_that_event_only(raw: Any) -> None:
    (row,) = engine.listing([{"id": "ev-a", "name": "A", "start": raw}], date(2026, 11, 11))
    assert row["when"]["group"] == "undated" and row["eligibility"]["label"] == "NO DATE"


def test_a_24_00_time_has_no_span_and_the_weekend_planner_still_answers() -> None:
    e = {"id": "ev-a", "name": "A", "start": "2026-11-14", "end": "2026-11-14T24:00"}
    assert engine.event_span(e, date(2026, 11, 11)) == (None, None)
    assert engine.overlaps(e, "2026-11-14", "2026-11-15", date(2026, 11, 11)) is False


# ── the weekend window boundaries through the route ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("clock", "start", "end", "names"),
    [
        # October: an event ending AT the window start and one starting AT its exclusive end are out
        ("2026-10-23T12:00:00", "2026-10-24", "2026-10-25",
         ["Hackathon Saturday", "Night Hack Session", "Sunday Pitch Session"]),
        # March: the event across the spring-forward gap is in; the Friday one ending at Saturday 00:00 is out
        ("2026-03-27T12:00:00", "2026-03-28", "2026-03-29", ["Spring Pitch Day", "Spring Startup Hackathon"]),
    ],
)  # fmt: skip
def test_the_weekend_selects_by_half_open_overlap_across_a_clock_change(
    monkeypatch: pytest.MonkeyPatch, rules: EventsData, clock: str, start: str, end: str, names: list[str]
) -> None:
    client, seen = make_client(monkeypatch, rules, utc_instant(clock))
    body = client.get(f"/api/events/weekend?start={start}&end={end}").json()
    planned = [p["what"] for m in body["missions"] for p in m["plan"]]
    assert [n for n in planned if not n.startswith("Coffee:")] == names
    assert seen["people"] is True


# ── the other routes ────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("query", "status"), [("days=abc", 400), ("days=1.5", 400), ("days=", 200), ("", 200),
                                               ("days=%207%20", 200), ("days=-3", 200)])  # fmt: skip
def test_wsig_days_must_be_a_whole_number(
    monkeypatch: pytest.MonkeyPatch, rules: EventsData, query: str, status: int
) -> None:
    client, seen = make_client(monkeypatch, rules, utc_instant("2026-11-11T12:00:00"))
    r = client.get(f"/api/events/wsig?{query}")
    assert r.status_code == status
    if status == 400:
        assert r.json()["ok"] is False and r.json()["error"].startswith("days must be a whole number")
        assert "today" not in seen  # refused before any read


def test_wsig_defaults_to_14_days(monkeypatch: pytest.MonkeyPatch, rules: EventsData) -> None:
    client, _seen = make_client(monkeypatch, rules, utc_instant("2026-11-11T12:00:00"))
    assert client.get("/api/events/wsig").json() == client.get("/api/events/wsig?days=14").json()


def test_suggest_takes_the_first_non_blank_value(monkeypatch: pytest.MonkeyPatch, rules: EventsData) -> None:
    client, seen = make_client(monkeypatch, rules, utc_instant("2026-11-11T12:00:00"))
    r = client.get(
        "/api/events/suggest?name=&name=Robotics%20founders%20hackathon&name=x&type=hackathon&city=Karlsruhe"
    )
    assert r.json() == {"parts": engine.suggest({"name": "Robotics founders hackathon", "type": "hackathon",
                                                 "city": "Karlsruhe"})}  # fmt: skip
    assert "today" not in seen  # no database read


def test_health_is_the_stored_scan_or_the_empty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _seen = make_client(monkeypatch, EventsData([], []), utc_instant("2026-11-11T12:00:00"))
    assert client.get("/api/events/health").json()["note"] == "No event scan yet — press Scan sources."


def test_the_leads_listed_are_the_new_ones_in_stored_order(monkeypatch: pytest.MonkeyPatch) -> None:
    leads = [{"id": f"l{i}", "decision": ("new", "dismissed")[i % 2]} for i in range(300)]
    client, _seen = make_client(monkeypatch, EventsData([], leads), utc_instant("2026-11-11T12:00:00"))
    assert [x["id"] for x in client.get("/api/events").json()["leads"]] == [f"l{i}" for i in range(0, 300, 2)]


def test_reads_are_gets_and_writes_are_posts() -> None:
    by_method: dict[str, set[str]] = {}
    for r in router.router.routes:
        for m in getattr(r, "methods", set()):
            by_method.setdefault(m, set()).add(getattr(r, "path", ""))
    reads = {"/api/events", "/api/events/health", "/api/events/suggest", "/api/events/wsig", "/api/events/weekend"}
    writes = {f"/api/events/{w}" for w in ("save", "verify", "lead", "debrief", "scout", "find")}
    assert by_method == {"GET": reads, "POST": writes}
