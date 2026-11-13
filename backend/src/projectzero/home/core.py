"""THE INVESTMENT DESK (review 031a): the old ``GET /api/home`` body, ``domain/ecosys.py`` ``home()`` (:637-720) at
revision 6c739b9, HAND-PORTED line for line as a pure function of ``HomeInputs`` and ONE Berlin clock (decision b).

Not cut by script: every line of the old body calls a loader or the machine clock (``_load_signals()``,
``date.today()``, ``where_should_i_go(21)``, ``ppl.listing()``, ``storage.load_json``, ``evmod.listing()``,
``case_prep.operator_status(entry)``), so each one is replaced by the ported reader over ``inputs`` and the request
clock; the expressions between them are kept verbatim, in the old order. It has no top-level constant to cut (the
cuts ``[:6]``, ``[:3]``, ``[:5]``, the 21-day window and the ``p-omar-hedeya`` exclusion, decision e, are inline as
they were). ``tests/home/test_home_port.py`` checks that every string literal here is the old one.

The ported pieces reused (each checked equal to the old one):

* ``conviction.records.safe_score`` / ``readable``: the old ``services/pipeline._safe_score`` / ``_readable``
  (verbatim; ``safe_score`` flags ``data_warning`` on the record it is given, as the old one did: here a copy);
* ``conviction.operator.operator_status(entry, None, operator, now)``: the old ``case_prep.operator_status(entry)``
  (``case=None``: the prepared case is ``operator.cases[slug]``, as the old ``_load()["cases"].get(slug)``);
* ``dealflow.ranking.names.slug``: the old ``radar.slug`` (the same function Conviction uses);
* ``network.view.listing``: the old ``people.listing()``; ``events.engine.listing``: the old ``events.listing()[0]``;
  ``events.plans.where_should_i_go``: the old ``ecosys.where_should_i_go`` over both.

Reads never write (decision a). ``view`` never mutates ``inputs``: it works on deep copies (the old code set
``e["_sc"]`` and ``data_warning`` on freshly loaded records).
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timedelta
from typing import Any

from projectzero.conviction.operator import operator_status
from projectzero.conviction.records import readable, records, safe_score
from projectzero.dealflow.ranking.names import slug
from projectzero.events import engine as events
from projectzero.events import plans
from projectzero.home.inputs_model import HomeInputs
from projectzero.network import view as people

WSIG_DAYS = 21  # the old ``where_should_i_go(21)``


def view(inputs: HomeInputs, today: date, now: datetime) -> dict[str, Any]:
    """The old ``GET /api/home`` body. ``today``: the Berlin request date (decision b: ``week_ago``, ``weekday``,
    ``date``, the 21-day event window and the people's ``due``); ``now``: the request instant as naive Berlin wall
    time (the operator status: the contact-state days and the prepared case's freshness). Pure."""
    signals = records(copy.deepcopy(inputs.signals), ("company",))  # the old ``_load_signals()``
    live = [e for e in signals if e.get("status") != "dropped"]

    for e in live:
        e["_sc"] = safe_score(e)  # a legacy value is read as neutral on a copy, never stops the Investment Desk
    live = [readable(e) | {"_sc": e["_sc"]} if "data_warning" in e else e for e in live]
    week_ago = (today - timedelta(days=7)).isoformat()

    def rk(e: dict[str, Any]) -> Any:
        return e["_sc"]["verified"] if e["_sc"]["fully_verified"] else e["_sc"]["provisional"]

    op = inputs.operator
    ops = {id(e): operator_status({**e, "sc": e["_sc"], "slug": slug(e["company"])}, None, op, now) for e in live}
    # the best opportunity is one Mohamed should actively work on: never a company on hold (human outcome) or gated
    non_conf = [
        e
        for e in live
        if e.get("conflict") != "potential_conflict" and ops[id(e)]["status"] not in ("WATCHING", "CONFLICT GATED")
    ]
    prio = max(non_conf, key=rk) if non_conf else None
    priority = None
    if prio:
        priority = {
            "slug": slug(prio["company"]),
            "company": prio["company"],
            "score": rk(prio),
            "verified": prio["_sc"]["fully_verified"],
            "verdict": prio["_sc"]["verdict"],  # the score band (context), not the instruction
            "op": ops[id(prio)],
            "next": ops[id(prio)]["action"] if ops[id(prio)]["source"] != "score band" else prio.get("next_action", ""),
            "timing": prio["_sc"]["timing_label"],
        }
    plist = people.listing(copy.deepcopy(inputs.people), today)  # the old ``ppl.listing()`` (read once, decision a)
    evs = events.listing(copy.deepcopy(inputs.events.events), today, inputs.events.source_city(), inputs.events.pins)
    wsig = plans.where_should_i_go(evs, plist, today, WSIG_DAYS)
    best_event = next((w for w in wsig if w.get("weekend")), None) or (
        wsig[0] if wsig else None
    )  # weekend first, else best upcoming (flagged)
    due = [
        {"id": p["id"], "name": p["name"], "action": p.get("next_action", ""), "date": p.get("next_action_date", "")}
        for p in plist
        if p.get("due")
    ][:6]
    new_sig = [c for c in records(copy.deepcopy(inputs.candidates), ("id",)) if c.get("decision") == "new"]
    omar_recent = [
        {"company": e["company"], "sent": e.get("sent_to_omar", ""), "feedback": bool(e.get("omar_feedback"))}
        for e in live
        if e.get("sent_to_omar")
    ]
    omar_recent.sort(key=lambda x: x["sent"], reverse=True)

    def recent(iso: Any) -> Any:
        return (iso or "")[:10] >= week_ago

    progress = {
        "found": sum(1 for e in live if recent(e.get("discovery_date")) or recent(e.get("detected_on", ""))),
        "contacted": sum(1 for e in live if e.get("status") in ("contacted", "replied", "forwarded")),
        "sent_omar": sum(1 for e in live if recent(e.get("sent_to_omar", ""))),
        "people_added": sum(1 for p in plist if recent(p.get("created", "")) and p["id"] != "p-omar-hedeya"),
        "events_planned": sum(1 for e in evs if e.get("status") == "planned"),  # the old ``evmod.listing()[0]``
        "verified": sum(1 for e in live if e["_sc"]["fully_verified"]),
    }
    watch = [{"id": p["id"], "name": p["name"], "last": p.get("last_checked", "")} for p in plist if p.get("watch")][:6]
    return {
        "priority": priority,
        "best_event": best_event,
        "due": due,
        "new_signals": len(new_sig),
        "latest_signals": [{"name": c["name"], "source": c["source"]} for c in new_sig[:3]],
        "omar": omar_recent[:5],
        "progress": progress,
        "watch": watch,
        "weekday": today.strftime("%A"),
        "date": today.isoformat(),
    }
