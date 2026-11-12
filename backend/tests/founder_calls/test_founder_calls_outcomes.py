"""Review 023: the write outcomes of the pure routes — the new document, the changed ids, idempotency, no mutation of
the input, and the old insertion order (new records appended, merges in place)."""

from __future__ import annotations

import copy
import json
from datetime import date, datetime
from typing import Any

from projectzero.founder_calls import Outcome, due_state, followup, link, routes, save
from projectzero.ops.parity_founder_calls import counter_ids, main_doc

TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 10, 0, 0)  # naive: Berlin wall time
LATER = datetime(2026, 11, 12, 11, 0, 0)
PEOPLE = [{"id": "p-bo", "name": "Bo Fictiv"}, {"id": "p-ada", "name": "Ada Inventa-Smith"}]
PIPELINE = [{"company": "Invented Harbor Grid GmbH"}, {"company": "Invented Quill Robotics"}]
NONE: dict[str, list[str]] = {"companies": [], "founders": [], "calls": []}


def frozen(doc: Any) -> str:
    return json.dumps(doc)


def test_a_new_call_creates_company_founder_and_call_appended_last() -> None:
    doc = main_doc()
    before = frozen(doc)
    o = save(doc, {"company": "Invented Novel Optics", "founder": "Ivy Newman"}, today=TODAY, now=NOW,
             new_id=counter_ids())  # fmt: skip
    assert frozen(doc) == before  # the input is never mutated
    assert o.status == 200 and o.body["changed"] is True
    assert o.changed == {"companies": ["fc-co-000000000001"], "founders": ["fc-f-000000000002"],
                         "calls": ["fc-call-000000000003"]}  # fmt: skip
    for k in ("companies", "founders", "calls"):
        assert list(o.doc[k])[:-1] == list(doc[k])  # appended, the rest in place
    call = o.doc["calls"]["fc-call-000000000003"]
    assert call["date"] == "2026-11-12" and call["created"] == call["updated"] == "2026-11-12 10:00:00"
    assert o.body["call"]["founder_name"] == "Ivy Newman" and "pipeline_slug" not in o.body


def test_an_unchanged_save_returns_the_input_and_changes_nothing() -> None:
    doc = main_doc()
    first = save(doc, {"id": "k1", "objective": "Again"}, today=TODAY, now=NOW)
    assert first.changed == {"companies": [], "founders": ["fc-f-orphan0000000004"], "calls": ["k1"]}
    again = save(first.doc, {"id": "k1", "objective": "Again"}, today=TODAY, now=LATER)
    assert again.body["changed"] is False and again.doc is first.doc and again.changed == NONE
    assert again.body["call"]["updated"] == first.doc["calls"]["k1"]["updated"]


def test_a_refused_save_returns_the_input() -> None:
    doc = main_doc()
    o = save(doc, {"company": "Invented Lonely Co"}, today=TODAY, now=NOW)
    assert (o.status, o.body, o.doc, o.changed) == (400, {"error": "founder name and company are required"}, doc, NONE)
    assert o.doc is doc


def test_a_save_on_a_pipeline_company_answers_its_slug() -> None:
    o = save(main_doc(), {"id": "fc-call-tiedsecond0002", "observations": "x"}, today=TODAY, now=NOW)
    assert o.body["pipeline_slug"] == "invented-harbor-grid"
    assert list(o.body) == ["ok", "call", "changed", "founder_id", "company_id", "pipeline_slug"]


def test_followup_done_reopen_and_the_in_memory_default() -> None:
    doc = main_doc()
    done = followup(doc, {"id": "fc-call-tiedsecond0002"}, today=TODAY, now=NOW)
    assert done.changed == {"companies": [], "founders": [], "calls": ["fc-call-tiedsecond0002"]}
    na = done.doc["calls"]["fc-call-tiedsecond0002"]["next_action"]
    assert na["done"] is True and na["done_on"] == "2026-11-12"
    reopened = followup(done.doc, {"id": "fc-call-tiedsecond0002", "done": False}, today=TODAY, now=LATER)
    assert reopened.doc["calls"]["fc-call-tiedsecond0002"]["next_action"]["done_on"] == ""
    same = followup(reopened.doc, {"id": "fc-call-tiedsecond0002", "done": False}, today=TODAY, now=LATER)
    assert same.doc is reopened.doc and same.changed == NONE
    # a call without next_action: the old answer showed the default, the old file was not rewritten
    bare = followup(doc, {"id": "fc-call-nonextaction12", "done": False}, today=TODAY, now=NOW)
    assert bare.doc is doc and bare.changed == NONE and "next_action" not in doc["calls"]["fc-call-nonextaction12"]
    assert bare.body["call"]["next_action"] == {"text": "", "owner": "Mohamed", "due": "", "done": False}
    assert followup(doc, {"id": "nope"}, today=TODAY, now=NOW) == Outcome(404, {"error": "unknown call"}, doc, NONE)


def test_a_founder_link_to_an_already_linked_person_merges_in_place() -> None:
    doc = main_doc()
    before = copy.deepcopy(doc)
    o = link(doc, {"founder_id": "fc-f-orphan0000000004", "person_id": "p-bo"}, people=PEOPLE, pipeline=PIPELINE,
             today=TODAY, now=NOW)  # fmt: skip
    assert doc == before
    assert o.body == {"ok": True, "founder_id": "fc-f-personlinked00003"}
    assert o.changed == {"companies": [], "founders": ["fc-f-personlinked00003", "fc-f-orphan0000000004"],
                         "calls": ["k1"]}  # fmt: skip
    assert list(o.doc["founders"]) == list(doc["founders"])  # both records stay in place
    loser = o.doc["founders"]["fc-f-orphan0000000004"]
    assert loser["merged_into"] == "fc-f-personlinked00003" and list(loser)[-1] == "merged_into"
    assert "Cy Nowhere" in o.doc["founders"]["fc-f-personlinked00003"]["aliases"]
    assert o.doc["calls"]["k1"]["founder_id"] == "fc-f-personlinked00003"


def test_link_refusals_and_unknown_records_return_the_input() -> None:
    doc = main_doc()
    kw: dict[str, Any] = {"people": PEOPLE, "pipeline": PIPELINE, "today": TODAY, "now": NOW}
    for body, status, answer in (
        ({"founder_id": "fc-f-longfounderaaaa01", "person_id": "p-ghost"}, 404, {"error": "unknown person"}),
        ({"founder_id": "fc-f-nobody"}, 200, {"ok": False, "founder_id": None}),
        (
            {"company_id": "fc-co-longinventedaaa01", "pipeline_slug": "nope"},
            404,
            {"error": "unknown pipeline company"},
        ),
        ({"company_id": "fc-co-nope"}, 200, {"ok": False, "company_id": None}),
        ({}, 400, {"error": "founder_id or company_id required"}),
    ):
        o = link(doc, body, **kw)
        assert (o.status, o.body, o.changed) == (status, answer, NONE) and o.doc is doc, body


def test_a_company_link_merge_and_its_idempotent_repeat() -> None:
    doc = main_doc()
    kw: dict[str, Any] = {"people": PEOPLE, "pipeline": PIPELINE, "today": TODAY, "now": NOW}
    o = link(doc, {"company_id": "fc-co-tiedname0000005", "pipeline_slug": "invented-harbor-grid"}, **kw)
    assert o.body == {"ok": True, "company_id": "fc-co-pipelinelinked02"}
    assert o.changed == {"companies": ["fc-co-pipelinelinked02", "fc-co-tiedname0000005"],
                         "founders": ["fc-f-legacynoaliases08"], "calls": ["fc-call-followuptype13"]}  # fmt: skip
    assert o.doc["companies"]["fc-co-pipelinelinked02"]["aliases"] == ["Invented quill robotics",
                                                                       "Invented Harbor Grid GmbH"]  # fmt: skip
    again = link(o.doc, {"company_id": "fc-co-tiedname0000005", "pipeline_slug": "invented-harbor-grid"}, **kw)
    assert again.doc is o.doc and again.changed == NONE  # same clock, same content: nothing changed


def test_an_empty_store_gets_the_old_default_document() -> None:
    o = save(None, {"company": "Invented First Co", "founder": "Una First"}, today=TODAY, now=NOW, new_id=counter_ids())
    assert list(o.doc) == ["version", "label", "companies", "founders", "calls"]
    assert routes.workspace(None, people=[], pipeline=[], evaluations={}, today=TODAY)["counts"] == {
        "companies": 0, "founders": 0, "calls": 0, "due": 0}  # fmt: skip


def test_due_state_boundaries() -> None:
    def st(due: str, done: bool = False, text: str = "x") -> str:
        return due_state({"next_action": {"text": text, "due": due, "done": done}}, TODAY)

    assert [st("2026-11-11"), st("2026-11-12"), st("2026-11-19"), st("2026-11-20"), st(""), st("2026-13-45"),
            st("x", done=True), st("", text="")] == ["overdue", "due", "upcoming", "scheduled", "open", "open",
                                                    "done", ""]  # fmt: skip
    assert due_state({}, TODAY) == ""
