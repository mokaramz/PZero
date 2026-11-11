"""The pure Events write rules (review 016): the save plan (create / edit / merge / 409 / 404), provenance, the
debrief's person and lead entities, the Scout 00 add body, and the stored-date rule of ``event_columns``."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from projectzero.dealflow.intake.contract import validate_entity
from projectzero.events import edits
from projectzero.events.columns import event_columns, stored_stated
from projectzero.events.edits import EventsError

TODAY = date(2026, 11, 11)


def stored(*events: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    return {e["id"]: e for e in events}, [e["id"] for e in events]


def test_the_slug_is_the_old_one() -> None:
    assert (
        edits.slug_id("Robotics Hackathon: Karlsruhe!", "2026-12-04T18:30")
        == "ev-robotics-hackathon-karlsruhe-2026-12-04"
    )
    assert edits.slug_id("", "") == "ev-event-"
    assert edits.slug_id("A" * 60, "x") == "ev-" + "a" * 36 + "-x"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({}, edits.NAME_REQUIRED),
        ({"name": "  "}, edits.NAME_REQUIRED),
        ({"name": 5}, "name must be text"),
        ({"id": 5}, "id must be text"),
        ({"name": "A", "start": 20261204}, "start must be text"),
        ({"name": "A", "city": ["Karlsruhe"]}, "city must be text"),
        ({"name": "A", "convert_lead": 3}, "convert_lead must be text"),
    ],
)
def test_save_refuses_what_the_old_code_crashed_on(body: dict[str, Any], error: str) -> None:
    with pytest.raises(EventsError) as exc:
        edits.validate_save(body)
    assert exc.value.status == 400 and str(exc.value) == error


def test_an_add_creates_under_the_slug() -> None:
    by_id, order = stored({"id": "ev-other-2026-12-01", "name": "Other Thing", "start": "2026-12-01"})
    assert edits.plan_save({"name": "Robotics Night", "start": "2026-12-04"}, by_id, order) == (
        "create", "ev-robotics-night-2026-12-04", "")  # fmt: skip


def test_an_edit_needs_a_known_id() -> None:
    by_id, order = stored({"id": "ev-a", "name": "A"})
    assert edits.plan_save({"id": "ev-a", "status": "planned"}, by_id, order) == ("edit", "ev-a", "")
    with pytest.raises(EventsError) as exc:
        edits.plan_save({"id": "ev-missing", "name": "Ghost"}, by_id, order)
    assert exc.value.status == 404 and exc.value.extra == {"id": "ev-missing"}


def test_a_slug_collision_merges_when_the_evidence_agrees_and_refuses_when_it_conflicts() -> None:
    e = {"id": "ev-robotics-night-2026-12-04", "name": "Robotics Night", "start": "2026-12-04", "city": "München"}
    by_id, order = stored(e)
    same = {"name": "Robotics Night", "start": "2026-12-04", "city": "Munich"}  # an alias of the same city
    assert edits.plan_save(same, by_id, order) == ("merge", e["id"], "Robotics Night")
    assert edits.plan_save({"name": "Robotics Night", "start": "2026-12-04"}, by_id, order)[0] == "merge"  # no city
    with pytest.raises(EventsError) as exc:
        edits.plan_save({"name": "Robotics Night", "start": "2026-12-04", "city": "Berlin"}, by_id, order)
    assert exc.value.status == 409 and exc.value.extra == {"id": e["id"], "collision": True}
    assert "city Munich vs Berlin" in str(exc.value)
    with pytest.raises(EventsError):
        edits.plan_save({"name": "Robotics Night", "start": "2026-12-04", "country": "AT"}, by_id, order)


def test_the_fuzzy_merge_skips_a_conflicting_event_and_takes_the_next() -> None:
    berlin = {"id": "ev-1", "name": "AI Founders Night 2026", "start": "2026-12-04", "city": "Berlin"}
    munich = {"id": "ev-2", "name": "AI Founders Night", "start": "2026-12-05", "city": "Munich"}
    by_id, order = stored(berlin, munich)
    body = {"name": "AI Founders Night (Munich)", "start": "2026-12-04", "city": "Munich"}
    assert edits.plan_save(body, by_id, order) == ("merge", "ev-2", "AI Founders Night")
    alone = {"name": "AI Founders Night", "start": "2026-12-04", "city": "Paris"}
    assert edits.plan_save(alone, by_id, order)[0] == "create"  # every similar event conflicts: a new one


def test_a_merge_fills_gaps_and_keeps_every_source() -> None:
    target = {"id": "ev-a", "name": "A", "notes": "mine", "sources": [{"source": "manual", "url": "", "added": "x"}]}
    edits.merge_into(
        target, {"name": "A2", "notes": "theirs", "venue": "Hall", "source": "Luma", "url": "https://l"}, TODAY
    )
    assert (target["name"], target["notes"], target["venue"]) == ("A", "mine", "Hall")
    assert target["sources"][-1] == {"source": "Luma", "url": "https://l", "added": "2026-11-11"}
    edits.merge_into(target, {"source": "Luma", "url": "https://l"}, TODAY)
    assert len(target["sources"]) == 2  # the same source is recorded once


def test_a_save_writes_the_fields_and_the_gazetteer_coordinates() -> None:
    ev = edits.new_event("ev-a", TODAY)
    edits.apply_fields(ev, {"name": "A", "city": "Karlsruhe", "source": "", "url": "", "ignored": 1}, TODAY)
    assert (ev["lat"], ev["lng"]) == (49.0069, 8.4037) and "ignored" not in ev and ev["sources"] == []
    kept = {"id": "ev-b", "city": "Karlsruhe", "lat": 1.0, "lng": 2.0}
    edits.apply_fields(kept, {"status": "planned"}, TODAY)
    assert (kept["lat"], kept["lng"]) == (1.0, 2.0)


@pytest.mark.parametrize(("body", "decision"), [({}, "dismissed"), ({"decision": "new"}, "new"),
                                                ({"decision": "converted"}, "converted")])  # fmt: skip
def test_lead_decisions(body: dict[str, Any], decision: str) -> None:
    assert edits.lead_decision(body) == decision


@pytest.mark.parametrize("decision", ["maybe", "", None, 3])
def test_a_lead_decision_outside_the_vocabulary_is_refused(decision: Any) -> None:
    with pytest.raises(EventsError) as exc:
        edits.lead_decision({"decision": decision})
    assert exc.value.status == 400


@pytest.mark.parametrize(
    "body",
    [{"people_met": "Ada"}, {"leads": [1]}, {"people_met": [{"name": 3}]}, {"leads": [{"name": "X", "url": 5}]},
     {"notes": ["x"]}],
)  # fmt: skip
def test_debrief_refuses_bad_shapes(body: dict[str, Any]) -> None:
    with pytest.raises(EventsError) as exc:
        edits.validate_debrief({"id": "ev-a", **body})
    assert exc.value.status == 400


def test_the_debrief_person_is_the_old_one() -> None:
    ev = {"name": "Robotics Night", "city": "Karlsruhe", "start": "2026-12-04T18:30"}
    assert edits.person_body(ev, {"name": " Ada Quill ", "note": "drones"}, TODAY) == {
        "name": "Ada Quill",
        "why_interesting": "drones",
        "discovery": "Met at Robotics Night (Karlsruhe, 2026-12-04)",
        "location": "Karlsruhe",
        "relationship_strength": "met_once",
        "last_interaction": "2026-11-11",
        "founder_potential": "maybe",
        "next_action": "SUGGESTED: follow up within 48h while the conversation is warm",
    }


def test_lead_entities_take_the_lead_url_else_the_event_url_as_evidence_only() -> None:
    ev = {"name": "Robotics Night", "city": "Karlsruhe", "url": "https://night.example.com/e"}
    out = edits.lead_entities(ev, [{"name": "Drone Co", "desc": "pre-seed"}, {"name": " "},
                                   {"name": "Arm Co", "url": "https://arm.example.com"}], TODAY)  # fmt: skip
    assert [e["name"] for e in out] == ["Drone Co", "Arm Co"]  # a blank name is skipped, as before
    assert (
        out[0]["evidence"][0]["url"] == "https://night.example.com/e"
        and out[1]["evidence"][0]["url"] == "https://arm.example.com"
    )
    assert all("website" not in e for e in out)  # never an identity key: two startups at one event stay distinct
    assert out[0]["key_fact"] == "pre-seed" and out[1]["key_fact"] == "Startup lead captured at Robotics Night"
    assert all(validate_entity(e) == [] for e in out)  # each is a valid intake entity


def test_a_lead_without_any_public_url_has_no_evidence() -> None:
    (e,) = edits.lead_entities({"name": "Night", "url": "not a url"}, [{"name": "Drone Co"}], TODAY)
    assert e["evidence"] == [] and validate_entity(e) != []


def test_the_debrief_tail_adds_each_person_once() -> None:
    ev: dict[str, Any] = {"people_met": ["p-a"], "outcomes": "first"}
    edits.apply_debrief(ev, ["p-a", "p-b"], "second")
    assert ev == {"people_met": ["p-a", "p-b"], "outcomes": "first\nsecond", "status": "attended"}


def test_the_scout_add_body_is_the_old_one() -> None:
    report = {"event_name": "Northern Summit", "date": "UNKNOWN", "city": "Helsinki", "official_url": "UNKNOWN",
              "cycle_id": "c7", "ev_class": "EV-A", "ax_class": "AX-1", "p_class": "P1", "why_it_matters": "density",
              "required_action": "register"}  # fmt: skip
    assert edits.scout_add_body(report) == {
        "name": "Northern Summit",
        "start": "",
        "city": "Helsinki",
        "url": "",
        "source": "Scout Intake cycle c7",
        "notes": "Scout Intake cycle c7 · EV EV-A · AX AX-1 · P P1 · why: density · action: register",
    }


# ── the stored date of an unchanged side (Codex H-107) ──────────────────────────────────────────────────────────
LEAP = {"id": "ev-leap", "name": "Leap Night", "start": "Feb 29", "end": "Feb 29"}


def test_an_unchanged_side_keeps_its_stored_date() -> None:
    imported = event_columns("ev-leap", LEAP, today=date(2024, 1, 15)).columns  # stored 2024-02-29
    assert imported["start_date"] == date(2024, 2, 29)
    keep = {s: stored_stated(LEAP[s], imported[f"{s}_date"], imported[f"{s}_time"]) for s in ("start", "end")}
    edited = event_columns("ev-leap", {**LEAP, "status": "planned"}, today=date(2025, 1, 10), kept=keep).columns
    assert (edited["start_date"], edited["end_date"]) == (date(2024, 2, 29), date(2024, 2, 29))
    assert edited["starts_at"] == imported["starts_at"] and edited["ends_at"] == imported["ends_at"]
    reresolved = event_columns("ev-leap", {**LEAP, "status": "planned"}, today=date(2025, 1, 10)).columns
    assert reresolved["start_date"] is None  # what an unrelated edit would have done without the kept sides


def test_a_changed_side_is_resolved_and_the_span_uses_both_effective_values() -> None:
    imported = event_columns("ev-leap", LEAP, today=date(2024, 1, 15)).columns
    keep = {"start": stored_stated("Feb 29", imported["start_date"], imported["start_time"])}
    edited = event_columns("ev-leap", {**LEAP, "end": "2024-03-01"}, today=date(2025, 1, 10), kept=keep)
    c = edited.columns
    assert (c["start_date"], c["end_date"]) == (date(2024, 2, 29), date(2024, 3, 1))
    assert c["ends_at"].isoformat() == "2024-03-02T00:00:00+01:00" and edited.notes["span_problem"] is None


def test_a_null_stored_side_stays_no_date() -> None:
    imported = event_columns("ev-leap", LEAP, today=date(2025, 1, 15)).columns  # 2025: no Feb 29 -> NULL
    assert imported["start_date"] is None
    keep = {s: stored_stated(LEAP[s], None, None) for s in ("start", "end")}
    edited = event_columns("ev-leap", {**LEAP, "status": "planned"}, today=date(2028, 1, 10), kept=keep).columns
    assert (edited["start_date"], edited["starts_at"]) == (None, None)
    assert edited["attrs"]["start"] == "Feb 29"  # the unparseable wording stays in attrs
