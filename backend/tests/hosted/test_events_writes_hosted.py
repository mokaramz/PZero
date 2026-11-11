"""Review 016 acceptance tests (Codex H-107) against the hosted project, in throw-away scratch schemas:

* concurrent saves of one event: no lost update, the history in order; two concurrent adds of one event: one event;
* a slug collision with conflicting evidence is a 409, an unknown id a 404, nothing written;
* an edit keeps the STORED date of each side it did not change ("Feb 29" across years: a status-only edit and an
  end-only edit);
* a lead conversion is ONE transaction: a retry answers it again without a second event; an unknown lead writes nothing;
* a debrief: a new person, an existing person linked (never overwritten), startup leads through intake (origin
  event_debrief), a repeated debrief, and a rollback after a person write (no person, history or intake row left);
* Scout 00: add then a second add of the same event (merged, not duplicated); concurrent actions on two reports of
  the same document (no lost update).
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from tests.hosted.test_events_hosted import GOOD, client_at, schema, seed, settings

from projectzero.core.config import Settings
from projectzero.core.db import transaction
from projectzero.dealflow.intake.service import IntakeService
from projectzero.events.columns import event_columns
from projectzero.events.writes import EventsWriter
from projectzero.network.people import columns_of

pytestmark = pytest.mark.hosted
_ = (schema, settings)  # fixtures
NOW = datetime(2026, 11, 11, 11, 0, tzinfo=UTC)


def q(settings: Settings, schema: str, query: str, params: Any = ()) -> list[tuple[Any, ...]]:
    with transaction(settings.db_url) as conn:
        return conn.execute(query.replace("{s}", schema).encode(), params).fetchall()


def record(settings: Settings, schema: str, eid: str) -> dict[str, Any]:
    ((attrs, legacy),) = q(settings, schema, "select attrs, legacy from {s}.events where id = %s", (eid,))
    rec: dict[str, Any] = attrs.get("record") or legacy
    return rec


def history(settings: Settings, schema: str) -> list[tuple[Any, ...]]:
    return q(settings, schema, "select coalesce(event_id, lead_id), action from {s}.event_history order by id")


def held(settings: Settings, schema: str, write: Any) -> tuple[psycopg.Connection[Any], Any]:
    """Run ``write(EventsWriter)`` in an OPEN transaction on its own connection (its locks held until commit)."""
    conn = psycopg.connect(settings.db_url, autocommit=False)
    out = write(EventsWriter(conn, schema, NOW))
    return conn, out


def in_thread(fn: Any) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {}

    def run() -> None:
        box["out"] = fn()

    t = threading.Thread(target=run)
    t.start()
    return t, box


# ── save ────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_concurrent_saves_of_one_event_lose_nothing_and_are_ordered(settings: Settings, schema: str) -> None:
    seed(settings, schema, [{"id": "ev-a", "name": "Robotics Hackathon", "start": "2026-11-14", **GOOD}], [])
    conn, _ = held(settings, schema, lambda w: w.save({"id": "ev-a", "notes": "first writer"}))
    with client_at(settings, schema, NOW) as client:
        t, box = in_thread(lambda: client.post("/api/events/save", json={"id": "ev-a", "venue": "Second Hall"}))
        time.sleep(1.5)
        assert t.is_alive()  # waiting for the events lock
        conn.commit()
        conn.close()
        t.join(30)
    assert box["out"].status_code == 200
    rec = record(settings, schema, "ev-a")
    assert (rec["notes"], rec["venue"]) == ("first writer", "Second Hall")
    assert history(settings, schema) == [("ev-a", "save"), ("ev-a", "save")]


def test_two_concurrent_adds_of_one_event_make_one_event(settings: Settings, schema: str) -> None:
    seed(settings, schema, [], [])
    body = {
        "name": "Replay Robotics Night",
        "start": "2026-12-04",
        "city": "Karlsruhe",
        **{"url": "https://r.example.com"},
    }
    conn, first = held(settings, schema, lambda w: w.save(body))
    with client_at(settings, schema, NOW) as client:
        t, box = in_thread(lambda: client.post("/api/events/save", json={**body, "name": "Replay Robotics Night 2026",
                                                                       "venue": "Hall B"}))  # fmt: skip
        time.sleep(1.5)
        conn.commit()
        conn.close()
        t.join(30)
    assert first["id"] == "ev-replay-robotics-night-2026-12-04"
    assert box["out"].json()["id"] == "ev-replay-robotics-night-2026-12-04|merged:Replay Robotics Night"
    assert q(settings, schema, "select id from {s}.events") == [("ev-replay-robotics-night-2026-12-04",)]
    assert record(settings, schema, "ev-replay-robotics-night-2026-12-04")["venue"] == "Hall B"  # a gap filled


def test_a_conflicting_slug_collision_and_an_unknown_id_write_nothing(settings: Settings, schema: str) -> None:
    seed(settings, schema, [{"id": "ev-robotics-night-2026-12-04", "name": "Robotics Night", "start": "2026-12-04",
                             "city": "Karlsruhe"}], [])  # fmt: skip
    with client_at(settings, schema, NOW) as client:
        r = client.post("/api/events/save", json={"name": "Robotics Night", "start": "2026-12-04", "city": "Berlin"})
        assert (
            r.status_code == 409 and r.json()["collision"] is True and r.json()["id"] == "ev-robotics-night-2026-12-04"
        )
        r = client.post("/api/events/save", json={"id": "ev-ghost", "name": "Ghost"})
        assert r.status_code == 404
    assert q(settings, schema, "select count(*) from {s}.events") == [(1,)] and history(settings, schema) == []
    assert record(settings, schema, "ev-robotics-night-2026-12-04")["city"] == "Karlsruhe"


def _seed_leap(settings: Settings, schema: str, imported_on: date) -> None:
    """A "Feb 29" event imported on ``imported_on`` (its stored columns computed with that clock)."""
    rec = {"id": "ev-leap", "name": "Leap Founder Night", "start": "Feb 29", "end": "Feb 29", **GOOD}
    c = event_columns("ev-leap", rec, today=imported_on).columns
    with transaction(settings.db_url) as conn:
        conn.execute(
            f"insert into {schema}.events (id, name, starts_at, ends_at, start_date, start_time, end_date, end_time,"
            " city, url, attrs, legacy) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)".encode(),
            ("ev-leap", c["name"], c["starts_at"], c["ends_at"], c["start_date"], c["start_time"], c["end_date"],
             c["end_time"], c["city"], c["url"], Jsonb(c["attrs"]), Jsonb(rec)),
        )  # fmt: skip


def test_an_edit_keeps_the_stored_date_of_a_side_it_did_not_change(settings: Settings, schema: str) -> None:
    _seed_leap(settings, schema, date(2024, 1, 15))  # stored 2024-02-29
    with client_at(settings, schema, datetime(2025, 1, 10, 10, 0, tzinfo=UTC)) as client:
        assert client.post("/api/events/save", json={"id": "ev-leap", "status": "planned"}).status_code == 200
        cols = q(settings, schema, "select start_date, end_date from {s}.events where id = 'ev-leap'")
        assert cols == [(date(2024, 2, 29), date(2024, 2, 29))]  # a 2025 re-read would have lost both
        r = client.post("/api/events/save", json={"id": "ev-leap", "start": "Feb 29", "end": "2024-03-01"})
        assert r.status_code == 200  # the identical start wording is resent by the form: still unchanged
        (e,) = client.get("/api/events").json()["events"]
    cols = q(settings, schema, "select start_date, end_date, ends_at from {s}.events where id = 'ev-leap'")
    assert cols[0][:2] == (date(2024, 2, 29), date(2024, 3, 1))
    assert cols[0][2].astimezone(UTC).isoformat() == "2024-03-01T23:00:00+00:00"  # the span from both effective values
    assert (e["start"], e["when"]["start_date"], e["when"]["end_date"]) == ("Feb 29", "2024-02-29", "2024-03-01")


def test_a_span_that_does_not_run_forward_is_refused(settings: Settings, schema: str) -> None:
    seed(settings, schema, [{"id": "ev-a", "name": "Night Run", "start": "2026-11-14", **GOOD}], [])
    with client_at(settings, schema, NOW) as client:
        r = client.post("/api/events/save", json={"id": "ev-a", "start": "2026-03-29T02:45", "end": "2026-03-29T03:15"})
    assert r.status_code == 400 and "span" in r.json()["error"]
    assert record(settings, schema, "ev-a")["start"] == "2026-11-14" and history(settings, schema) == []


# ── leads ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_a_lead_conversion_is_one_transaction_and_a_retry_answers_it_again(settings: Settings, schema: str) -> None:
    seed(settings, schema, [], [{"id": "evlead-1", "title": "Robotics meetup", "decision": "new"}])
    body = {"name": "Converted Robotics Meetup", "start": "2026-12-09", "city": "Stuttgart", "convert_lead": "evlead-1"}
    with client_at(settings, schema, NOW) as client:
        first = client.post("/api/events/save", json=body).json()
        retry = client.post("/api/events/save", json=body).json()
        r = client.post("/api/events/save", json={**body, "name": "Another", "convert_lead": "evlead-missing"})
    assert first == {"ok": True, "id": "ev-converted-robotics-meetup-2026-12-09"}
    assert retry == {**first, "replayed": True}
    assert r.status_code == 404
    assert q(settings, schema, "select id from {s}.events") == [("ev-converted-robotics-meetup-2026-12-09",)]
    assert q(settings, schema, "select decision from {s}.event_leads") == [("converted",)]
    assert history(settings, schema) == [("ev-converted-robotics-meetup-2026-12-09", "create"), ("evlead-1", "convert")]


def test_lead_decisions_refuse_unknown_values_and_ids(settings: Settings, schema: str) -> None:
    seed(settings, schema, [], [{"id": "evlead-1", "title": "T", "decision": "new", "date": "Sept 20"}])
    before = q(settings, schema, "select lead_date from {s}.event_leads")
    with client_at(settings, schema, datetime(2027, 10, 1, tzinfo=UTC)) as client:
        assert client.post("/api/events/lead", json={"id": "evlead-1", "decision": "maybe"}).status_code == 400
        assert client.post("/api/events/lead", json={"id": "evlead-x"}).status_code == 404
        assert client.post("/api/events/lead", json={"id": "evlead-1"}).json() == {"ok": True}
    assert q(settings, schema, "select decision, lead_date from {s}.event_leads") == [("dismissed", before[0][0])]
    assert history(settings, schema) == [("evlead-1", "lead_decision")]


# ── debrief ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _seed_person(settings: Settings, schema: str, person: dict[str, Any]) -> None:
    cols = columns_of(person["id"], person)
    with transaction(settings.db_url) as conn:
        conn.execute(
            f"insert into {schema}.people (id, name, normalized_name, attrs, legacy) values (%s, %s, %s, %s, %s)".encode(),
            (person["id"], cols["name"], cols["normalized_name"], Jsonb(cols["attrs"]), Jsonb(person)),
        )


DEBRIEF = {"id": "ev-a", "people_met": [{"name": "Nia Newcomer", "note": "builds arms"}, {"name": "Ada Quill",
           "note": "met again"}], "leads": [{"name": "Replay Drone Startup", "desc": "pre-seed drone team"}],
           "notes": "great room"}  # fmt: skip


def test_a_debrief_creates_links_and_hands_the_leads_to_intake(settings: Settings, schema: str) -> None:
    seed(settings, schema, [{"id": "ev-a", "name": "Robotics Hackathon", "start": "2026-11-10", **GOOD}], [])
    ada = {"id": "p-ada-quill", "name": "Ada Quill", "introduced_by": "p-host", "discovery": "Recommended by Host",
           "why_interesting": "original note", "relationship_strength": "strong"}  # fmt: skip
    _seed_person(settings, schema, ada)
    with client_at(settings, schema, NOW) as client:
        out = client.post("/api/events/debrief", json=DEBRIEF).json()
        again = client.post("/api/events/debrief", json=DEBRIEF).json()
    assert out == {"ok": True, "people": ["p-nia-newcomer", "p-ada-quill"], "leads": 1}
    assert again == {"ok": True, "people": ["p-nia-newcomer", "p-ada-quill"], "leads": 0}  # the same batch: a no-op
    rec = record(settings, schema, "ev-a")
    assert rec["people_met"] == ["p-nia-newcomer", "p-ada-quill"] and rec["status"] == "attended"  # each once
    ((ada_now,),) = q(
        settings, schema, "select coalesce(attrs->'record', legacy) from {s}.people where id = 'p-ada-quill'"
    )
    assert {k: ada_now.get(k) for k in ada} == ada  # the introduction and the notes are never overwritten
    assert ada_now["last_interaction"] == "2026-11-11"
    assert q(settings, schema, "select origin, outcome from {s}.intake_submissions") == [("event_debrief", "accepted")]
    assert q(settings, schema, "select name, origins from {s}.candidates") == [
        ("Replay Drone Startup", ["event_debrief"])
    ]
    ((evidence,),) = q(settings, schema, "select payload->'evidence' from {s}.observations")
    assert evidence[0]["url"] == GOOD["url"]  # the event's URL, as evidence only


def test_a_lead_without_evidence_refuses_the_whole_debrief(settings: Settings, schema: str) -> None:
    seed(settings, schema, [{"id": "ev-a", "name": "Robotics Hackathon", "start": "2026-11-10",
                             **{k: v for k, v in GOOD.items() if k != "url"}}], [])  # fmt: skip
    with client_at(settings, schema, NOW) as client:
        r = client.post("/api/events/debrief", json=DEBRIEF)
        ok = client.post(
            "/api/events/debrief", json={**DEBRIEF, "leads": [{"name": "Arm Co", "url": "https://arm.example.com"}]}
        )
    assert (
        r.status_code == 400 and "startup lead 1 (Replay Drone Startup)" in r.json()["error"] and r.json()["lead"] == 0
    )
    assert ok.status_code == 200  # a lead with its own evidence URL needs no event URL
    assert q(settings, schema, "select count(*) from {s}.intake_submissions") == [(1,)]


def test_a_debrief_failing_after_the_person_writes_leaves_nothing(
    settings: Settings, schema: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(settings, schema, [{"id": "ev-a", "name": "Robotics Hackathon", "start": "2026-11-10", **GOOD}], [])

    def fail(*_: Any, **__: Any) -> Any:
        raise RuntimeError("intake down")

    monkeypatch.setattr(IntakeService, "submit_trusted", fail)
    with client_at(settings, schema, NOW) as client, pytest.raises(RuntimeError):
        client.post("/api/events/debrief", json=DEBRIEF)
    assert q(settings, schema, "select count(*) from {s}.people") == [(0,)]
    assert q(settings, schema, "select count(*) from {s}.person_events") == [(0,)]
    assert history(settings, schema) == [] and record(settings, schema, "ev-a").get("status") != "attended"
    assert q(settings, schema, "select count(*) from {s}.intake_submissions") == [(0,)]
    assert q(settings, schema, "select count(*) from {s}.observations") == [(0,)]


# ── Scout 00 ────────────────────────────────────────────────────────────────────────────────────────────────────
def _seed_scout(settings: Settings, schema: str) -> None:
    base = {"status": "NEW", "ev_class": "EV-A", "ax_class": "AX-1", "p_class": "P1", "why_it_matters": "density",
            "required_action": "register", "official_url": "https://summit.example.com", "city": "Helsinki",
            "history": []}  # fmt: skip
    doc = {"events": [
        {**base, "id": "se-1", "cycle_id": "c1", "event_name": "Northern Founder Summit", "date": "2026-12-02"},
        {**base, "id": "se-2", "cycle_id": "c2", "event_name": "Northern Founder Summit (side events)", "date": "2026-12-03"},
        {**base, "id": "se-3", "cycle_id": "c2", "event_name": "Other Pitch Day", "date": "2026-12-10"},
    ]}  # fmt: skip
    with transaction(settings.db_url) as conn:
        conn.execute(
            f"insert into {schema}.documents (key, body) values ('scout_intake.json#rest', %s)".encode(), (Jsonb(doc),)
        )


def _reports(settings: Settings, schema: str) -> dict[str, dict[str, Any]]:
    ((doc,),) = q(settings, schema, "select body from {s}.documents where key = 'scout_intake.json#rest'")
    return {r["id"]: r for r in doc["events"]}


def test_a_second_scout_add_of_the_same_event_is_merged(settings: Settings, schema: str) -> None:
    seed(settings, schema, [], [])
    _seed_scout(settings, schema)
    with client_at(settings, schema, NOW) as client:
        one = client.post("/api/events/scout", json={"id": "se-1", "action": "add"}).json()
        two = client.post("/api/events/scout", json={"id": "se-2", "action": "add"}).json()
    eid = "ev-northern-founder-summit-2026-12-02"
    assert one == {"ok": True, "status": "ADDED TO EVENTS", "event_id": eid}
    assert two == {"ok": True, "status": "ADDED TO EVENTS", "event_id": f"{eid}|merged:Northern Founder Summit"}
    assert q(settings, schema, "select id from {s}.events") == [(eid,)]
    reps = _reports(settings, schema)
    assert reps["se-1"]["event_id"] == reps["se-2"]["event_id"] == eid  # the plain id
    assert reps["se-2"]["history"] == [
        {"on": "2026-11-11 12:00", "from": "NEW", "to": "ADDED TO EVENTS", "note": "operator"}
    ]
    assert [h[1] for h in history(settings, schema)] == ["scout_add", "scout_add"]


def test_concurrent_actions_on_two_reports_of_one_document_lose_nothing(settings: Settings, schema: str) -> None:
    seed(settings, schema, [], [])
    _seed_scout(settings, schema)
    conn, first = held(settings, schema, lambda w: w.scout({"id": "se-1", "action": "monitor"}))
    with client_at(settings, schema, NOW) as client:
        t, box = in_thread(lambda: client.post("/api/events/scout", json={"id": "se-3", "action": "ignore"}))
        time.sleep(1.5)
        assert t.is_alive()  # waiting for the document row
        conn.commit()
        conn.close()
        t.join(30)
    assert first["status"] == "MONITOR" and box["out"].json()["status"] == "IGNORED"
    reps = _reports(settings, schema)
    assert (reps["se-1"]["status"], reps["se-3"]["status"], reps["se-2"]["status"]) == ("MONITOR", "IGNORED", "NEW")
    assert history(settings, schema) == []  # Monitor / Ignore: audited in the report's own history only


def test_follow_up_notes_for_a_linked_person_survive_in_history(settings: Settings, schema: str) -> None:
    """Codex H-109: an attended event, a person already in people_met, blank event notes: each debrief's note for that
    person has no other home than the history (the person's own notes are never overwritten)."""
    seed(settings, schema, [{"id": "ev-a", "name": "Robotics Hackathon", "start": "2026-11-10", **GOOD,
                             "status": "attended", "people_met": ["p-ada-quill"]}], [])  # fmt: skip
    ada = {"id": "p-ada-quill", "name": "Ada Quill", "notes": "original profile notes", "why_interesting": "drones",
           "last_interaction": "2026-11-11"}  # fmt: skip
    _seed_person(settings, schema, ada)
    with client_at(settings, schema, NOW) as client:
        for note in ("first follow-up note", "second, different note"):
            body = {"id": "ev-a", "people_met": [{"name": "Ada Quill", "note": note}], "leads": [], "notes": ""}
            assert client.post("/api/events/debrief", json=body).json() == {
                "ok": True,
                "people": ["p-ada-quill"],
                "leads": 0,
            }
    rows = q(
        settings,
        schema,
        "select action, detail->'linked_notes' from {s}.event_history where event_id = 'ev-a' order by id",
    )
    assert rows == [
        ("debrief", {"p-ada-quill": "first follow-up note"}),
        ("debrief", {"p-ada-quill": "second, different note"}),
    ]
    assert record(settings, schema, "ev-a")["people_met"] == ["p-ada-quill"]  # the event itself did not change
    ((profile,),) = q(
        settings, schema, "select coalesce(attrs->'record', legacy) from {s}.people where id = 'p-ada-quill'"
    )
    assert (profile["notes"], profile["why_interesting"]) == ("original profile notes", "drones")
