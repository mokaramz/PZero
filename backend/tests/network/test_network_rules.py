"""Offline rules of the Network port: the save / ritual / signal-log write rules (incl. decisions a and b and the
deferred Founder Radar rename), the Berlin clock, the record order helpers and the shared row mapping."""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime
from typing import Any

import pytest

from projectzero.network import edits, view
from projectzero.network.edits import NetworkError
from projectzero.network.people import columns_of, distinct_identifiers, identifiers_of, record_of, slug

TODAY = date(2026, 11, 11)


# ── the clock ───────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("now", "today"),
    [
        (datetime(2026, 11, 11, 23, 30), date(2026, 11, 11)),  # a naive clock is Berlin wall time already
        (datetime(2026, 11, 11, 22, 59, tzinfo=UTC), date(2026, 11, 11)),  # 23:59 Berlin (CET, +01:00)
        (datetime(2026, 11, 11, 23, 0, tzinfo=UTC), date(2026, 11, 12)),  # 00:00 Berlin: the next day
        (datetime(2026, 7, 1, 22, 0, tzinfo=UTC), date(2026, 7, 2)),  # summer time (+02:00)
        (datetime(2026, 7, 1, 21, 59, tzinfo=UTC), date(2026, 7, 1)),
    ],
)
def test_today_is_the_berlin_date_of_the_clock(now: datetime, today: date) -> None:
    assert view.berlin_today(now) == today


def test_the_due_boundary_moves_at_berlin_midnight() -> None:
    p = {"id": "p-a", "name": "A", "next_action": "call", "next_action_date": "2026-11-12"}
    before = view.berlin_today(datetime(2026, 11, 11, 22, 59, tzinfo=UTC))
    after = view.berlin_today(datetime(2026, 11, 11, 23, 0, tzinfo=UTC))
    assert view.listing([p], before)[0]["due"] is False
    assert view.listing([p], after)[0]["due"] is True


# ── the read helpers ────────────────────────────────────────────────────────────────────────────────────────────
def test_get_is_the_first_record_with_an_equal_id() -> None:
    a, b = {"id": "p-x", "name": "First"}, {"id": "p-x", "name": "Second"}
    odd = {"id": ["p-x"], "name": "List id"}
    idx = view.Index([a, b, odd])
    assert idx.get("p-x") is a and idx.get(["p-x"]) is odd and idx.get({"id": 1}) is None and idx.get(None) is None


def test_reads_never_change_the_records() -> None:
    people = [{"id": "p-a", "name": "A", "recommended": ["p-b"]}, {"id": "p-b", "name": "B", "introduced_by": "p-a"}]
    snapshot = copy.deepcopy(people)
    view.people_view(people, TODAY)
    view.graph_view(people)
    view.watchlist_view(people, TODAY)
    assert people == snapshot


def test_the_people_view_carries_the_old_tables() -> None:
    body = view.people_view([], TODAY)
    assert body == {"people": [], "strengths": view.STRENGTHS, "potential": view.POTENTIAL}


# ── person_save ─────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("body", "error"),
    [
        ({}, "name required"),
        ({"name": "  "}, "name required"),
        ({"id": "", "name": ""}, "name required"),
        ({"name": 5}, "name must be text"),
        ({"id": 5, "name": "A"}, "id must be text"),
        ({"name": "A", "recommended": "p-b"}, "recommended must be a list of person ids"),
        ({"name": "A", "recommended": [1]}, "recommended must be a list of person ids"),
        ({"name": "A", "introduced_by": ["p-b"]}, "introduced_by must be a person id"),
    ],
)
def test_save_refusals(body: dict[str, Any], error: str) -> None:
    with pytest.raises(NetworkError) as exc:
        edits.validate_save(body)
    assert exc.value.status == 400 and str(exc.value) == error


def test_an_edit_needs_no_name() -> None:
    edits.validate_save({"id": "p-a", "next_action": "x"})  # follow-up / log contact / judgment carry only an id


def test_a_new_record_is_the_old_upsert_start() -> None:
    rec = edits.new_record("p-ada-quill", TODAY)
    edits.apply_save(rec, {"name": "Ada Quill", "startups": "A, , B ", "id": "ignored", "unknown_field": 1})
    assert rec == {"id": "p-ada-quill", "recommended": [], "startups": ["A", "B"], "created": "2026-11-11",
                   "provenance": "user_provided", "name": "Ada Quill"}  # fmt: skip


def test_an_edit_changes_only_the_fields_it_carries() -> None:
    rec = {"id": "p-a", "name": "A", "company": "Old Co", "orcid": "0000-0002-1825-0097"}
    body = {"id": "p-a", "next_action": "call", "watch": True}
    edits.apply_save(rec, body)
    assert rec == {"id": "p-a", "name": "A", "company": "Old Co", "orcid": "0000-0002-1825-0097",
                   "next_action": "call", "watch": True}  # fmt: skip
    nameless = {"id": "p-b"}
    edits.apply_save(nameless, {"notes": "x"})
    assert nameless["name"] == "?"  # the old setdefault


def test_apply_save_copies_values() -> None:
    body = {"recommended": ["p-b"]}
    rec: dict[str, Any] = {"id": "p-a"}
    edits.apply_save(rec, body)
    body["recommended"].append("p-c")
    assert rec["recommended"] == ["p-b"]


# ── the ritual (decision b) ─────────────────────────────────────────────────────────────────────────────────────
def ritual(records: dict[str, dict[str, Any]], host: str, persons: list[dict[str, Any]]) -> tuple[Any, ...]:
    work = copy.deepcopy(records)
    return edits.apply_talented(host, persons, work.get, TODAY)


def test_a_new_person_gets_the_old_ritual_record() -> None:
    created, work, notes = ritual({"p-host": {"id": "p-host", "name": "Host Person"}}, "p-host",
                                  [{"name": " Cleo Vance ", "note": "robotics"}, {"name": ""}, {"name": None}])  # fmt: skip
    assert created == ["p-cleo-vance"]
    assert work["p-cleo-vance"] == {
        "id": "p-cleo-vance", "name": "Cleo Vance", "recommended": [], "startups": [], "created": "2026-11-11",
        "relationship_strength": "met_once", "founder_potential": "maybe", "last_interaction": "",
        "introduced_by": "p-host", "discovery": "Recommended by Host Person ('3 most talented' ask)",
        "why_interesting": "robotics", "next_action": "SUGGESTED: reach out with a warm reference to Host Person",
        "provenance": "user_provided",
    }  # fmt: skip
    assert work["p-host"]["recommended"] == ["p-cleo-vance"] and work["p-host"]["last_interaction"] == "2026-11-11"
    assert notes == {"p-cleo-vance": {"new": True}}


def test_an_existing_parent_is_never_overwritten() -> None:
    records = {
        "p-ben": {"id": "p-ben", "name": "Ben"},
        "p-cleo": {"id": "p-cleo", "name": "Cleo", "introduced_by": "p-ada", "discovery": "Recommended by Ada",
                   "why_interesting": "Ada's note", "next_action": "call"},
    }  # fmt: skip
    created, work, notes = ritual(records, "p-ben", [{"name": "Cleo", "note": "Ben's note"}])
    cleo = work["p-cleo"]
    assert created == ["p-cleo"] and work["p-ben"]["recommended"] == ["p-cleo"]  # the recommendation lands
    assert (cleo["introduced_by"], cleo["discovery"], cleo["why_interesting"]) == (
        "p-ada", "Recommended by Ada", "Ada's note")  # fmt: skip
    assert cleo["next_action"] == "call" and cleo["provenance"] == "user_provided"
    assert notes == {"p-cleo": {"introduction_kept": "p-ada", "note": "Ben's note"}}


def test_a_recommendation_fills_an_empty_why_interesting_only() -> None:
    records = {"p-ben": {"id": "p-ben", "name": "Ben"}, "p-cleo": {"id": "p-cleo", "name": "Cleo",
               "introduced_by": "p-ada"}}  # fmt: skip
    _, work, _ = ritual(records, "p-ben", [{"name": "Cleo", "note": "Ben's note"}])
    assert work["p-cleo"]["why_interesting"] == "Ben's note" and work["p-cleo"]["introduced_by"] == "p-ada"


def test_an_empty_parent_is_filled_and_a_retry_is_the_old_write() -> None:
    records = {"p-ada": {"id": "p-ada", "name": "Ada"}, "p-cleo": {"id": "p-cleo", "name": "Cleo",
               "introduced_by": "", "why_interesting": "imported"}}  # fmt: skip
    _, work, _ = ritual(records, "p-ada", [{"name": "Cleo", "note": "first"}])
    assert work["p-cleo"]["introduced_by"] == "p-ada" and work["p-cleo"]["why_interesting"] == "first"
    again = {k: copy.deepcopy(v) for k, v in work.items()}
    created, work2, _ = edits.apply_talented("p-ada", [{"name": "Cleo", "note": "second"}], again.get, TODAY)
    assert created == ["p-cleo"] and work2["p-ada"]["recommended"] == ["p-cleo"]  # one recommendation
    assert work2["p-cleo"]["why_interesting"] == "second"  # its own introducer again: the old overwrite


def test_a_person_is_never_their_own_introducer() -> None:
    created, work, _ = ritual({"p-ada": {"id": "p-ada", "name": "Ada"}}, "p-ada", [{"name": "Ada"}])
    assert created == ["p-ada"] and "introduced_by" not in work["p-ada"] and work["p-ada"]["recommended"] == ["p-ada"]


def test_named_twice_in_one_ritual() -> None:
    created, work, _ = ritual({"p-h": {"id": "p-h", "name": "H"}}, "p-h", [{"name": "Dev Rao"}, {"name": "dev rao"}])
    assert created == ["p-dev-rao", "p-dev-rao"] and work["p-h"]["recommended"] == ["p-dev-rao"]


def test_no_named_person_leaves_recommended_absent() -> None:
    created, work, _ = ritual({"p-h": {"id": "p-h", "name": "H"}}, "p-h", [{"name": " "}])
    assert created == [] and "recommended" not in work["p-h"] and work["p-h"]["last_interaction"] == "2026-11-11"


def test_a_recommended_that_is_not_a_list_refuses_the_ritual() -> None:
    with pytest.raises(NetworkError) as exc:
        ritual({"p-h": {"id": "p-h", "name": "H", "recommended": "p-x"}}, "p-h", [{"name": "Dev"}])
    assert exc.value.status == 409


@pytest.mark.parametrize(
    "body",
    [{"id": "p-h", "persons": None}, {"id": "p-h", "persons": "Dev"}, {"id": "p-h", "persons": ["Dev"]},
     {"id": "p-h", "persons": [{"name": 5}]}, {"id": "p-h", "persons": [{"name": "Dev", "note": 1}]},
     {"id": 7, "persons": []}],
)  # fmt: skip
def test_ritual_refusals(body: dict[str, Any]) -> None:
    with pytest.raises(NetworkError) as exc:
        edits.validate_talented(body)
    assert exc.value.status == 400


def test_ritual_ids_are_the_host_and_every_slug() -> None:
    assert edits.ritual_ids("p-h", [{"name": "Zed"}, {"name": ""}, {"name": "Amy"}]) == ["p-h", "p-zed", "p-amy"]


# ── watch_log ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_watch_log_appends_the_signal_and_marks_checked() -> None:
    p: dict[str, Any] = {"id": "p-a"}
    edits.apply_watch_log(p, "new paper", TODAY)
    assert p == {"id": "p-a", "notes": "[2026-11-11 signal] new paper", "last_checked": "2026-11-11"}
    edits.apply_watch_log(p, "talk", date(2026, 11, 12))
    assert p["notes"] == "[2026-11-11 signal] new paper\n[2026-11-12 signal] talk"
    edits.apply_watch_log(p, "", date(2026, 11, 13))
    assert p["last_checked"] == "2026-11-13" and p["notes"].endswith("talk")


def test_watch_log_refusals() -> None:
    with pytest.raises(NetworkError) as exc:
        edits.validate_watch_log({"id": "p-a", "note": 5})
    assert exc.value.status == 400
    with pytest.raises(NetworkError) as exc:
        edits.apply_watch_log({"id": "p-a", "notes": ["x"]}, "y", TODAY)
    assert exc.value.status == 409


# ── the shared row mapping (importer and writes) ────────────────────────────────────────────────────────────────
def test_columns_mirror_the_record() -> None:
    rec = {"id": "p-a", "name": "Prof. Dr. Jürgen Groß", "country": {"code": "DE"}, "identity_status": "resolved",
           "company": "X", "record": {"nested": True}}  # fmt: skip
    cols = columns_of("p-a", rec)
    assert cols["name"] == "Prof. Dr. Jürgen Groß" and cols["normalized_name"] == "jurgen gross"
    assert cols["country"] is None and cols["attrs"]["country"] == {"code": "DE"}
    assert cols["identity_status"] == "resolved" and "identity_status" not in cols["attrs"]
    assert "record" not in cols["attrs"] and "id" not in cols["attrs"] and cols["attrs"]["company"] == "X"
    assert columns_of("p-b", {"id": "p-b", "name": " "})["name"] == "p-b"


def test_identifiers_follow_the_012_rules() -> None:
    rec = {"orcid": "0000-0002-1825-0097", "openalex_id": "A123", "github_id": 42, "aliases": ["ada", "ADA"],
           "profile_urls": ["https://github.com/ada", "https://acme.example.com/", "https://orcid.org/0000-0002-1825-0097"]}  # fmt: skip
    assert identifiers_of(rec) == [
        ("orcid", "https://orcid.org/0000-0002-1825-0097"), ("openalex", "https://openalex.org/A123"),
        ("github", "42"), ("profile_url", "https://github.com/ada"), ("url", "https://acme.example.com"),
        ("profile_url", "https://orcid.org/0000-0002-1825-0097"), ("alias", "ada"),
    ]  # fmt: skip
    assert len(distinct_identifiers({"profile_urls": ["https://x.example.com", "http://www.x.example.com/"]})) == 1


def test_record_of_prefers_the_application_record() -> None:
    row = {"id": "p-a", "legacy": {"id": "p-a", "name": "Old"}, "attrs": {"record": {"id": "p-a", "name": "New"}}}
    assert record_of(row)["name"] == "New"
    assert record_of({**row, "attrs": {}})["name"] == "Old"


def test_slug_is_the_old_person_id() -> None:
    assert slug("Jürgen Groß") == "p-juergen-gross" and slug("李小龙") == "p-person" and len(slug("a" * 99)) == 42
