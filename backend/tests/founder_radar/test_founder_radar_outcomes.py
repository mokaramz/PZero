"""Review 026a: the decisions of the plan on the pure routes — the input is never mutated, reads never write, ids are
deterministic and never reuse a live or reserved (tombstone) id, migrations are idempotent, an unchanged write writes
nothing, an unknown state is a 400, a merged id is absent everywhere, and one Berlin clock."""

from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime
from typing import Any

from projectzero.founder_radar import routes
from projectzero.founder_radar.clock import Clock
from projectzero.founder_radar.companies import companies_queue, research_priority
from projectzero.founder_radar.ingestion import allocate_id, id_suffix, ingest
from projectzero.founder_radar.records import migrate_all
from projectzero.network.view import listing
from projectzero.ops.parity_founder_radar import (
    CUSTOM_CSV,
    ILSA,
    LARK,
    LOGIN,
    QUILL,
    TBD,
    TEODOR,
    WENNA_A,
    WENNA_B,
    ZORVIK,
    corpus,
)

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)  # 10:00 in Berlin
TODAY = date(2026, 11, 12)


def inputs(**kw: Any) -> routes.Inputs:
    docs = corpus()
    base = routes.Inputs(
        people=docs["people.json"]["people"], companies=docs["radar_companies.json"], research=docs["radar_research.json"],
        health=docs["radar_health.json"], regions=docs["radar_regions.json"], metrics=docs["radar_metrics.json"],
        signals=docs["real_data.json"]["signals"],
    )  # fmt: skip
    return routes.Inputs(**(base.__dict__ | kw))


def frozen(inp: routes.Inputs) -> str:
    return json.dumps(
        {k: (sorted(v) if isinstance(v, frozenset) else v) for k, v in inp.__dict__.items()}, ensure_ascii=False
    )


def run(fn: Any, inp: routes.Inputs, body: dict[str, Any]) -> routes.Outcome:
    before = frozen(inp)
    o: routes.Outcome = fn(inp, body, today=TODAY, now=NOW)
    assert frozen(inp) == before, "the input was mutated"
    return o


WRITES = [
    (routes.action, {"id": ILSA, "action": "watch"}),
    (routes.action, {"id": WENNA_A, "action": "merge", "other": WENNA_B, "confirm": True}),
    (routes.action, {"id": ZORVIK, "action": "confirm_identity", "name": "Zorvik Talmadge", "handle": "zorvik", "company": "Larkspur Analytics",
                     "url": "https://github.com/zorvik", "label": "GitHub", "fact": "Zorvik Talmadge (zorvik) is co-founder of Larkspur Analytics",
                     "confirm": True}),
    (routes.import_csv, {"csv": CUSTOM_CSV}),
    (routes.company, {"key": LARK, "notes": "n"}),
    (routes.promote, {"id": ILSA}),
    (routes.boardy_brief, {"id": ILSA}),
    (routes.pair, {"key": LARK, "proposal": "fz", "person": ZORVIK}),
    (routes.review, {"key": LARK, "confirm": ["status-01", "acc"], "reject": ["h"]}),
    (routes.proposals, {"key": LARK}),
]  # fmt: skip


def test_no_route_mutates_its_input_and_the_view_writes_nothing() -> None:
    inp = inputs()
    for fn, body in WRITES:
        run(fn, inp, body)
    before = frozen(inp)
    v = routes.view(inp, today=TODAY, now=NOW)
    assert frozen(inp) == before and isinstance(v, dict)
    assert not routes.proposals(inp, {"key": LARK}, today=TODAY, now=NOW).wrote  # a read
    assert "_dirty" not in json.dumps(v)


def test_the_view_migrates_in_memory_only() -> None:
    inp = inputs()
    v = routes.view(inp, today=TODAY, now=NOW)
    shown = {p["id"]: p for p in v["people"]}
    assert TBD not in shown  # the generated-only placeholder is quarantined in the view
    assert shown[LOGIN]["name_attributed"] is False  # login normalisation
    stored = {p["id"]: p for p in inp.people}
    assert TBD in stored and "name_attributed" not in stored[LOGIN]  # nothing was written back


def test_migrations_are_idempotent() -> None:
    ck = Clock.at(NOW)
    first = migrate_all(corpus()["people.json"]["people"], ck)
    assert first.changed and first.log  # the corpus needs migrating
    second = migrate_all(first.people, ck)
    assert second.changed == []
    # the old quirk, kept: an invalidated placeholder with human work is re-reported (its record is not changed again)
    assert [e["kind"] for e in second.log] == ["people_mvp_to_mvp1"] and second.log[0]["invalidated"] == ["Core Team"]
    assert json.dumps(second.people) == json.dumps(first.people)


def test_founder_references_are_derived_without_dirty_and_never_change_the_input() -> None:
    inp = inputs()
    doc = copy.deepcopy(inp.companies)
    _q, refs = companies_queue(listing(inp.people, TODAY), companies_doc=doc, research_doc=inp.research, signals=inp.signals,
                               now=NOW, today=TODAY)  # fmt: skip
    assert json.dumps(doc) == json.dumps(inp.companies)
    assert refs.changed and "_dirty" not in json.dumps(refs.doc)
    assert any(
        r["created"] == "2026-11-12 10:00"
        for c in refs.doc["companies"].values()
        for r in (c.get("founder_refs") or {}).values()
    )


def test_ids_are_deterministic_and_never_reuse_a_live_or_reserved_id() -> None:
    c = {"name": "Juno Avenhart"}
    base = f"p-juno-avenhart-{id_suffix('Juno Avenhart') % 10000}"
    assert allocate_id(c, set()) == base
    assert allocate_id(c, {base}) == base + "-2"
    assert allocate_id(c, {base, base + "-2"}) == base + "-3"
    assert allocate_id({"name": "Bram Okonkwo", "github_id": 77}, set()).endswith(f"-{id_suffix(77) % 10000}")
    ck = Clock.at(NOW)
    res = ingest([], [c], ck=ck, reserved_ids={base})  # a tombstone holds the derived id
    assert [p["id"] for p in res.people] == [base + "-2"]
    twice = ingest([], [c, dict(c)], ck=ck)  # an unresolvable row imported twice (the old code made a duplicate id)
    assert [p["id"] for p in twice.people] == [base, base + "-2"]
    o = run(
        routes.import_csv,
        inputs(reserved_ids=frozenset({f"p-cassius-wrenfold-{id_suffix('Cassius Wrenfold') % 10000}"})),
        {"csv": CUSTOM_CSV},
    )
    assert any(i.startswith("p-cassius-wrenfold-") and i.endswith("-2") for i in o.people_changed)


def test_an_unchanged_write_writes_nothing() -> None:
    inp = inputs()
    o = run(routes.action, inp, {"id": ILSA, "action": "watch"})
    assert o.people is not None and o.people_changed == [ILSA] and o.metrics is not None
    after = routes.Inputs(**(inp.__dict__ | {"people": o.people, "metrics": o.metrics}))
    o2 = run(routes.action, after, {"id": ILSA, "action": "link_event", "event": ""})
    assert o2.status == 200 and o2.body["ok"] and not o2.wrote
    assert not run(
        routes.company, routes.Inputs(**(inp.__dict__ | {"companies": {"companies": {QUILL: {}}}})), {"key": QUILL}
    ).wrote
    for fn, body in ((routes.action, {"id": "p-nobody", "action": "watch"}), (routes.action, {"id": ILSA, "action": "teleport"}),
                     (routes.company, {"key": LARK, "founded": "2020"}), (routes.review, {"key": "dom:nowhere"}),
                     (routes.pair, {"key": LARK, "proposal": "nope", "person": ZORVIK})):  # fmt: skip
        assert not run(fn, inp, body).wrote  # a refusal writes nothing


def test_an_unknown_state_is_a_400() -> None:
    o = run(routes.action, inputs(), {"id": TEODOR, "action": "state", "state": "nonsense"})
    assert (
        o.status == 400
        and o.body == {"ok": False, "error": routes.STATE_REFUSAL + ", ".join(routes.STATES)}
        and not o.wrote
    )


def test_merge_names_the_tombstone_and_a_merged_id_is_absent_everywhere() -> None:
    inp = inputs()
    o = run(routes.action, inp, {"id": WENNA_A, "action": "merge", "other": WENNA_B, "confirm": True})
    assert o.merged == (WENNA_A, WENNA_B) and o.people is not None
    assert WENNA_B not in [p["id"] for p in o.people] and o.people_changed == [WENNA_A]
    live = routes.Inputs(**(inp.__dict__ | {"people": o.people, "reserved_ids": frozenset({WENNA_B})}))
    unknown = "p-never-existed"
    for fn, body in (
        (routes.action, {"id": "@", "action": "watch"}),
        (routes.promote, {"id": "@"}),
        (routes.boardy_brief, {"id": "@"}),
    ):
        stale = run(fn, live, {**body, "id": WENNA_B})
        never = run(fn, live, {**body, "id": unknown})
        assert (stale.status, stale.body) == (never.status, never.body) and not stale.wrote
    # a founder reference of the tombstone is still stored: pairing or binding it is the not-a-founder-reference refusal
    q = listing(inp.people, TODAY)
    _c, refs = companies_queue(
        q, companies_doc=inp.companies, research_doc=inp.research, signals=inp.signals, now=NOW, today=TODAY
    )
    research = copy.deepcopy(inp.research)
    research["domains"]["name:fernhollow ai"] = {"domain": "", "proposals": {"fw": {"id": "fw", "field": "founder", "value": "Wenna Calloway",
        "status": "pending", "person": {"name": "Wenna Calloway", "role": "founder", "company": "Fernhollow AI"}, "url": "https://fernhollow.example/team",
        "passage": "Wenna Calloway, founder of Fernhollow AI.", "source_label": "team page"}}}  # fmt: skip
    stale_inp = routes.Inputs(**(live.__dict__ | {"companies": refs.doc, "research": research}))
    p = run(routes.pair, stale_inp, {"key": "name:fernhollow ai", "proposal": "fw", "person": WENNA_B})
    assert (
        p.body == {"ok": False, "error": "selected record is not a founder reference of this company"} and not p.wrote
    )
    r = run(routes.review, stale_inp, {"key": "name:fernhollow ai", "confirm": ["fw"], "bindings": {"fw": WENNA_B}})
    assert r.body["still_pending"][0]["reason"] == "selected person is not a founder reference of this company"
    assert r.people is None


def test_a_self_merge_is_refused() -> None:
    o = run(routes.action, inputs(), {"id": WENNA_A, "action": "merge", "other": WENNA_A, "confirm": True})
    assert o.body["ok"] is False and o.body["error"].startswith("merge refused: ") and not o.wrote


def test_verify_identity_evidence_survives_the_identity_evidence_recomputation() -> None:
    o = run(routes.action, inputs(), {"id": TEODOR, "action": "verify_identity", "url": "https://optics.example/t", "label": "lab page",
                                      "fact": "Teodor Vanstrel heads the lab", "confirm": True})  # fmt: skip
    p = o.body["person"]
    assert p["evidence"][-1]["claim"] == "Teodor Vanstrel heads the lab" and p["evidence"][-1]["category"] == "identity"
    assert p["identity_evidence"][-1] == "identity verified by operator action"  # decision d: replaced, as before


def test_one_berlin_clock() -> None:
    o = run(routes.action, inputs(), {"id": ILSA, "action": "watch"})
    assert o.body["person"]["state_history"][-1]["on"] == "2026-11-12 10:00"  # 09:00 UTC is 10:00 in Berlin
    late = datetime(2026, 11, 12, 23, 30, tzinfo=UTC)  # already the 13th in Berlin
    o2 = routes.action(inputs(), {"id": ILSA, "action": "watch"}, today=date(2026, 11, 13), now=late)
    assert o2.body["person"]["updated"] == "2026-11-13" and o2.metrics["latest"]["date"] == "2026-11-13"


def test_the_theme_terms_are_listed_in_one_order() -> None:
    c = {"description": "robotics and energy infrastructure for defence", "founders": [], "claims": {}}
    f = research_priority(c, TODAY)["factors"][0]["factor"]
    assert f == "Project A theme overlap in description (defence, energy, infrastructure)"


def test_two_different_patent_inventor_ids_are_never_merged() -> None:
    """Codex H-213: the old code never compared patent inventor ids, so a merge kept one and lost the other."""
    from projectzero.founder_radar.identity import can_merge

    a = {"name": "Ilka Invented", "company": "Invented Optics", "patent_inventor_id": "INV-A"}
    b = {"name": "Ilka Invented", "company": "Invented Optics", "patent_inventor_id": "INV-B"}
    ok, why = can_merge(a, b)
    assert ok is False and why == "conflicting patent_inventor_id (INV-A vs INV-B) — never merged automatically"
    assert can_merge(a, {**b, "patent_inventor_id": "INV-A"})[0] is True  # the same id: the old employer rule decides
    assert can_merge(a, {k: v for k, v in b.items() if k != "patent_inventor_id"})[0] is True
