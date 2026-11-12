"""Review 024: the write outcomes of the pure routes — the new document, the changed ids, the Founder Calls and
Conviction parts of ``end`` / ``imq_trigger``, no mutation of any input, the old insertion order — plus the
evaluator-owned evidence rules and ``imq.record_trigger``."""

from __future__ import annotations

import copy
import json
from datetime import date, datetime
from typing import Any

import pytest

from projectzero import evaluator
from projectzero.conviction import imq
from projectzero.evaluator.evidence import add_evidence, is_recent, valid_activity_date
from projectzero.ops.parity_evaluator import LONG_ID, SHORT_ID, corpus, counter_hex

TODAY = date(2026, 11, 12)
NOW = datetime(2026, 11, 12, 10, 0, 0)  # naive: Berlin wall time
URL = "https://invented.example/source"


def frozen(v: Any) -> str:
    return json.dumps(v)


class World:
    def __init__(self) -> None:
        c = corpus()
        self.doc = c["evaluations.json"]
        self.conviction = c["real_data.json"]["signals"]
        self.people = c["people.json"]["people"]
        self.radar = c["radar_companies.json"]
        self.calls = c["founder_calls.json"]
        self.new_hex = counter_hex()

    def kw(self, **extra: Any) -> dict[str, Any]:
        return {"conviction": self.conviction, "people": self.people, "today": TODAY, "now": NOW,
                "new_hex": self.new_hex, **extra}  # fmt: skip

    def act(self, act: str, body: dict[str, Any]) -> evaluator.Outcome:
        before = (frozen(self.doc), frozen(self.conviction), frozen(self.calls))
        o = evaluator.action(act, self.doc, body, **self.kw(radar_companies=self.radar, founder_calls=self.calls))
        assert (frozen(self.doc), frozen(self.conviction), frozen(self.calls)) == before, "an input was mutated"
        return o


@pytest.fixture
def w() -> World:
    return World()


def test_start_appends_the_session_last_and_keeps_the_key_order(w: World) -> None:
    o = w.act("start", {"subject": {"slug": "invented-lattice-freight"}})
    sid = o.body["id"]
    assert sid == "ev-20261112100000-000001" and o.changed == [sid]
    assert list(o.doc) == ["version", "sessions"]
    assert list(o.doc["sessions"]) == [*w.doc["sessions"], sid]
    assert o.doc["sessions"][LONG_ID] is w.doc["sessions"][LONG_ID]  # untouched sessions are shared, not copied
    assert set(o.body) == {"ok", "id", "session", "next", "panel"}  # start answers without a row, as before
    assert o.body["next"]["id"] == "q-00000200" and o.founder_calls is None and o.conviction == ()
    seeded = [c["state"] for c in o.doc["sessions"][sid]["ledger"]]
    assert seeded == ["OPERATOR VERIFIED", "OPERATOR VERIFIED", "PUBLIC SOURCED FACT", "PUBLIC SOURCED FACT"]


def test_a_missing_document_reads_as_no_sessions() -> None:
    assert evaluator.loaded(None) == {"sessions": {}}
    assert evaluator.workspace(None)["sessions"] == []
    o = evaluator.start(None, {"subject": {"name": "Invented Solo"}}, conviction=[], people=[], radar_companies=None,
                        today=TODAY, now=NOW, new_hex=counter_hex())  # fmt: skip
    assert list(o.doc) == ["sessions"]
    assert "research_facts" not in o.body["session"]["context"]  # no radar match: the old code set nothing


def test_an_unreadable_radar_file_means_no_research_facts() -> None:
    o = evaluator.start(None, {"subject": {"slug": "invented-lattice-freight"}}, conviction=corpus()["real_data.json"]["signals"],
                        people=[], radar_companies=object(), today=TODAY, now=NOW)  # fmt: skip
    assert o.body["session"]["context"]["research_facts"] == {}


def test_the_workspace_sorts_by_created_and_keeps_the_document_order_on_ties(w: World) -> None:
    rows = [r["id"] for r in evaluator.workspace(w.doc)["sessions"]]
    assert rows == ["ev-20261005100000-mid002", LONG_ID, SHORT_ID]


def test_get_session_next_includes_a_skipped_question(w: World) -> None:
    v = evaluator.session_view(w.doc, LONG_ID, conviction=w.conviction, people=w.people, today=TODAY)
    assert v is not None and v["next"]["id"] == "q-skipped01"
    assert evaluator.session_view(w.doc, "ev-nope", conviction=[], people=[], today=TODAY) is None
    ended = evaluator.session_view(w.doc, "ev-20261005100000-mid002", conviction=[], people=[], today=TODAY)
    assert ended is not None and ended["next"] is None


@pytest.mark.parametrize(
    ("act", "body", "error"),
    [
        ("skip", {"qid": "q-nope"}, "unknown question"),
        ("skip", {"qid": "q-answered1"}, "already answered"),
        ("answer", {"qid": "q-nope", "text": "x"}, "unknown question"),
        ("evidence", {"claim_id": "cl-nope", "url": URL, "label": "x"}, "unknown claim"),
        ("evidence", {"claim_id": "cl-oldunknown", "kind": "operator"}, "explicit confirmation required"),
        ("evidence", {"claim_id": "cl-oldunknown", "url": "https://linkedin.com/in/x", "label": "x"}, "LinkedIn"),
        ("resolve", {"claim_id": "cl-oldunknown"}, "unknown contradiction"),
        ("frobnicate", {}, "unknown evaluator action"),
    ],
)
def test_a_refusal_returns_the_input_document(w: World, act: str, body: dict[str, Any], error: str) -> None:
    o = w.act(act, {"id": LONG_ID, **body})
    assert o.status == 200 and o.body["ok"] is False and error in o.body["error"]
    assert o.doc is w.doc and o.changed == []
    assert {"session", "panel", "row"} <= set(o.body)


def test_an_unknown_session_answers_without_the_panel(w: World) -> None:
    o = w.act("deck", {"id": "ev-nope", "text": "x"})
    assert o.body == {"ok": False, "error": "unknown session"} and o.doc is w.doc


def test_next_with_an_open_question_changes_nothing_and_a_new_question_changes_the_session(w: World) -> None:
    o = w.act("start", {"subject": {"name": "Invented Solo"}})
    sid = o.body["id"]
    w.doc = o.doc
    same = w.act("next", {"id": sid})
    assert same.doc is w.doc and same.changed == [] and same.body["next"]["id"] == o.body["next"]["id"]
    skipped = w.act("skip", {"id": sid, "qid": o.body["next"]["id"]})
    assert skipped.changed == [sid] and skipped.doc is not w.doc
    assert list(skipped.doc["sessions"]) == list(w.doc["sessions"])


def test_answer_overwrites_and_adds_a_claim(w: World) -> None:
    first = w.act("answer", {"id": LONG_ID, "qid": "q-answered1", "text": "Invented forwarders with 4 pilots"})
    w.doc = first.doc
    second = w.act("answer", {"id": LONG_ID, "qid": "q-answered1", "text": "Invented shippers"})
    s = second.doc["sessions"][LONG_ID]
    assert next(q for q in s["questions"] if q["id"] == "q-answered1")["answer"] == "Invented shippers"
    texts = [c["text"] for c in s["ledger"]]
    assert "Invented forwarders with 4 pilots" in texts and "Invented shippers" in texts


def test_end_writes_the_founder_call_and_the_conviction_record_once(w: World) -> None:
    o = w.act("end", {"id": LONG_ID, "call_type": "followup"})
    assert o.changed == [LONG_ID]
    assert o.founder_calls is not None and o.founder_calls.status == 200
    call_id = o.body["ended"]["call_id"]
    assert o.founder_calls.changed["calls"] == [call_id] and call_id in o.founder_calls.doc["calls"]
    assert o.founder_calls.doc["calls"][call_id]["objective"] == f"Active Evaluator session {LONG_ID}"
    assert [(c.index, c.slug) for c in o.conviction] == [(0, "invented-lattice-freight")]
    rec = o.conviction[0].record
    assert rec["evaluator_last"]["session"] == LONG_ID and "evaluator_provisional" in rec
    assert list(rec)[: len(w.conviction[0])] == list(w.conviction[0])  # keys added last
    assert rec["verify_list"][0] == "Check the seed round"
    w.doc = o.doc
    again = w.act("end", {"id": LONG_ID})
    assert again.body["ended"]["already"] is True
    assert again.doc is w.doc and again.changed == [] and again.founder_calls is None and again.conviction == ()


def test_end_without_an_answer_saves_no_call(w: World) -> None:
    o = w.act("start", {"subject": {"slug": "invented-orbit-tools"}})
    w.doc = o.doc
    ended = w.act("end", {"id": o.body["id"]})
    assert ended.founder_calls is None and ended.body["ended"]["call_error"].startswith("no founder answer")
    assert [c.index for c in ended.conviction] == [2]
    external = w.act("end", {"id": SHORT_ID})
    assert external.founder_calls is None and external.conviction == () and external.changed == [SHORT_ID]


def test_imq_trigger_changes_the_record_only_on_success(w: World) -> None:
    body = {"slug": "invented-lattice-freight", "kind": "fundraising", "date": "2026-11-01", "url": URL,
            "fact": "Series A opened", "confirm": True}  # fmt: skip
    before = frozen(w.conviction)
    for bad in ({"confirm": False}, {"kind": "x"}, {"date": "2026-11-13"}, {"slug": "nobody"}, {"fact": " "}):
        t = evaluator.imq_trigger({**body, **bad}, conviction=w.conviction, today=TODAY, now=NOW)
        assert t.body["ok"] is False and t.conviction == ()
    t = evaluator.imq_trigger(body, conviction=w.conviction, today=TODAY, now=NOW)
    assert frozen(w.conviction) == before
    assert t.body["ok"] is True and [(c.index, c.slug) for c in t.conviction] == [(0, "invented-lattice-freight")]
    assert t.conviction[0].record["imq_trigger"] == dict(t.body["trigger"]) | {"recorded": "2026-11-12 10:00"}


def test_record_trigger_refusals_leave_the_entry_unchanged() -> None:
    entry: dict[str, Any] = {"company": "Invented Co"}
    kw: dict[str, Any] = {"now": NOW, "today": TODAY}
    assert imq.record_trigger(entry, "trigger", "2026-11-01", URL, "x", False, **kw)["error"] == (
        "explicit confirmation required"
    )
    assert imq.record_trigger(entry, "nope", "2026-11-01", URL, "x", True, **kw)["error"].startswith("trigger kind")
    assert "not in the future" in imq.record_trigger(entry, "trigger", "2026-11-13", URL, "x", True, **kw)["error"]
    assert "required" in imq.record_trigger(entry, "trigger", "2026-11-01", "", "x", True, **kw)["error"]
    assert entry == {"company": "Invented Co"}
    ok = imq.record_trigger(entry, "window", "2026-11-12", URL, "Fact", True, **kw)
    assert ok == {"ok": True, "trigger": entry["imq_trigger"]}
    assert entry["imq_trigger"] == {"kind": "window", "label": "documented perishable sourcing window",
                                    "date": "2026-11-12", "url": URL, "fact": "Fact", "by": "operator",
                                    "recorded": "2026-11-12 10:00"}  # fmt: skip


@pytest.mark.parametrize(
    ("url", "label", "claim", "error"),
    [
        ("", "x", "c", "source URL, source label and the supported claim are all required"),
        ("ftp://x", "x", "c", "source URL, source label and the supported claim are all required"),
        (URL, " ", "c", "source URL, source label and the supported claim are all required"),
        (URL, "x", None, "source URL, source label and the supported claim are all required"),
        ("https://www.LinkedIn.com/in/x", "x", "c", "LinkedIn pages are a contact route"),
        ("https://www.google.com/search?q=x", "x", "c", "search results are not evidence"),
        ("https://duckduckgo.com/?q=x", "x", "c", "search results are not evidence"),
    ],
)
def test_add_evidence_refusals(url: str, label: str, claim: Any, error: str) -> None:
    r = add_evidence("operator", url, label, claim, now=NOW, today=TODAY)
    assert r["ok"] is False and r["error"].startswith(error)


def test_add_evidence_rows_and_activity_dates() -> None:
    r = add_evidence("", f" {URL} ", "Page", "Claim", field="funding", now=NOW, today=TODAY)
    assert r == {"ok": True, "row": {"category": "operator", "claim": "Claim",
                                     "source": "Operator-supplied public evidence — Page", "source_url": URL,
                                     "field": "funding", "retrieved": "2026-11-12 10:00", "by": "operator"}}  # fmt: skip
    assert add_evidence("trajectory", URL, "x", "c", now=NOW, today=TODAY)["ok"] is False
    assert (
        add_evidence("trajectory", URL, "x", "c", activity_date=" 2026-11-12 ", now=NOW, today=TODAY)["row"][
            "activity_date"
        ]
        == "2026-11-12"
    )
    assert valid_activity_date("2026-11-12", TODAY) == TODAY
    assert valid_activity_date("2026-11-13", TODAY) is None and valid_activity_date("2026-02-30", TODAY) is None
    assert valid_activity_date("12.11.2026", TODAY) is None and valid_activity_date(None, TODAY) is None
    assert is_recent("2026-05-16", TODAY, 180) and not is_recent("2026-05-15", TODAY, 180)
    assert is_recent("2026-08-14", TODAY) and not is_recent("2026-08-13", TODAY) and not is_recent("x", TODAY)


def test_the_session_documents_are_never_shared_with_the_input(w: World) -> None:
    o = w.act("answer", {"id": LONG_ID, "qid": "q-answered1", "text": "Invented answer"})
    o.doc["sessions"][LONG_ID]["ledger"].append({"x": 1})
    assert {"x": 1} not in w.doc["sessions"][LONG_ID]["ledger"]
    assert copy.deepcopy(w.doc) == corpus()["evaluations.json"]
