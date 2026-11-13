# ruff: noqa: E501, RUF003
# (the old expressions are kept verbatim, long lines included)
"""MOHAMED — TODAY (review 030a): at most 7 human actions, chosen deterministically from existing Project Zero state.
The old ``services/today.py`` (:28-606, plus ``_triage_summary`` / ``_machine_working``) at revision 6c739b9, ported
line for line as a pure function of ``TodayInputs`` and ONE Berlin clock (decision b).

Every signal used here already exists: the Conviction pipeline and the frozen ``compose_radar`` (Radar slots, research
queue, conflict gate), ``imq.evaluate``, the Founder Calls follow-ups, the Events listing, the Deal Flow triage view
and the Triage Queue Compressor's routes, the WATCH triggers and the prepared cases. Every title the page parses is
kept byte for byte (the event title, ``(\\d+) human decision``, ``Recommended next action:``, ``^Ask Manager about``
after the page's role mapping, ``^Triage:``), and so is the old "1 possible portfolio conflict for Omars" (h).

Changes, all declared in ``ops/parity_today.py``:

* (a) reads never write: the pipeline is read ONCE (``inputs.signals``), its IMQ snapshot is never saved;
* (c) the two retired Scout sections (SCOUT00_CYCLE, NATIVE_INTEL) are dropped with their ``considered`` keys;
* (d) exceptions: the ``jobs`` row is omitted until the background-jobs port, the ``source`` row is 0 until the
  source-network port (both were the old fallbacks), with a logged deferral;
* (e) no Claim Index yet: ``_ready_proposals`` is ``[]`` (the research-queue card is always ``Verify X (missing)``,
  rank 3), with a logged deferral;
* (f) the triage routes and prepared cases are the imported snapshot until their runs are ported: one more payload
  key at the END, ``snapshot`` (the Machine details' note and the original run timestamps).
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from projectzero.conviction import imq
from projectzero.conviction.operator import AWAITING, calls_for, contact_state, human_signals, watch_triggers
from projectzero.conviction.radar import compose_radar
from projectzero.dealflow.triage import portfolio_check
from projectzero.events import engine as events
from projectzero.events.view import _listing
from projectzero.founder_calls.core import due_followups, loaded
from projectzero.today import cases as case_prep
from projectzero.today import compressor
from projectzero.today.catalog import _CLEAR_CONFLICT, MAX_ACTIONS
from projectzero.today.inputs_model import UNREADABLE, TodayInputs

log = logging.getLogger(__name__)

# decision (c): the old sections run in this order; SCOUT00_CYCLE and NATIVE_INTEL are not evaluated
SECTIONS = ("pipeline", "calls", "events", "triage", "watch", "cases")
# decisions (d), (e) and (f): the visible note and the logged deferrals
SNAPSHOT_NOTE = "Triage routes and prepared cases are the imported snapshot until their runs are ported."
VERIFICATION_DEFERRED = (
    "verification proposals deferred until the Claim Index is ported (the research-queue card asks to verify)"
)
SOURCE_DEFERRED = "source-network trust approvals deferred until the source-network port (counted as 0)"
JOBS_DEFERRED = "background-job failures deferred until the background-jobs port (row omitted)"


def _action(
    kind: str,
    rank: float,
    title: str,
    why: str,
    next_step: str,
    link: str,
    *,
    urgency: str = "medium",
    evidence: list[str] | None = None,
    subject: str = "",
    conflict: str = "unknown",
    contact_appropriate: bool = False,
) -> dict[str, Any]:
    return {
        "type": kind,
        "rank": rank,
        "title": title,
        "why": why,
        "next_step": next_step,
        "link": link,
        "urgency": urgency,
        "evidence": evidence or [],
        "subject": subject,
        "conflict": conflict,
        "contact_appropriate": contact_appropriate,
    }


def _ready_proposals(entry: dict[str, Any]) -> list[str]:
    """Founders / funding proposals that deterministic rules already support (not yet ticked). Decision (e): the
    Claim Index is not ported yet, so none is known: always the "Verify" variant."""
    log.info("today: %s (%s)", VERIFICATION_DEFERRED, entry.get("company"))
    return []


def _signals(inputs: TodayInputs) -> list[dict[str, Any]]:
    if inputs.signals is None:  # the old pipeline read raised
        raise ValueError("the Conviction pipeline could not be read")
    return inputs.signals


def _pipeline_actions(signals: list[dict[str, Any]], plist: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    entries = copy.deepcopy(signals)
    radar = compose_radar(entries)
    checker = portfolio_check.Checker()

    def portfolio_block(e: dict[str, Any]) -> str:
        """A known Project A company / Project A relationship is NEVER ordinary outreach, whatever its conflict field."""
        st = checker.check({"name": e.get("company"), "description": e.get("one_liner") or ""})["status"]
        return st if st in ("KNOWN_PORTFOLIO", "PROJECT_A_RELATIONSHIP") else ""

    blocked = [e for e in entries if e.get("status") != "dropped" and portfolio_block(e)]
    for slot in ("high", "emerging", "wildcard"):
        for e in radar[slot]:
            ev = imq.evaluate(e, plist, None, None, today=today)
            if e.get("sent_to_omar") or e.get("conflict") not in _CLEAR_CONFLICT or portfolio_block(e):
                continue
            resolved = (
                all(f.get("resolved") for f in ev.get("founder_identities") or [])
                if ev.get("founder_identities")
                else False
            )
            if not resolved:
                continue
            out.append(
                _action(
                    "CONTACT_FOUNDER",
                    0 - e["_sc"]["verified"] / 1000,
                    f"Reach out to {e['company']}",
                    f"On Radar ({slot}, verified {e['_sc']['verified']}), conflict {e.get('conflict')}, founders resolved.",
                    "Write to the founder yourself — nothing is sent by Project Zero.",
                    f"/conviction?company={e['slug']}",
                    urgency="high",
                    subject=e["company"],
                    conflict=str(e.get("conflict")),
                    contact_appropriate=True,
                    evidence=[f"IMQ state: {ev['state']}", *ev.get("blockers", [])[:2]],
                )
            )
    gated = [e for e in radar["gated"]] + [
        e for e in entries if e.get("conflict") == "unclear" and e.get("status") != "dropped"
    ]
    gated += [e for e in blocked if all(e is not g for g in gated)]
    if gated:
        names = [e["company"] for e in gated]
        # urgency: what the company would score once Omar clears it (the frozen −25 potential-conflict penalty removed)
        top = max(
            (
                e["_sc"]["provisional"] + (25 if e.get("conflict") == "potential_conflict" else 0)
                for e in gated
                if e.get("_sc")
            ),
            default=0,
        )
        out.append(
            _action(
                "ASK_OMAR_CONFLICT",
                1 if top >= 65 else 5.5,
                f"Ask Omar about {len(gated)} possible portfolio conflict(s)",
                "These companies cannot move until Omar / Project A confirms whether they are investable"
                + (" (some are, or are linked to, Project A portfolio companies)." if blocked else "."),
                "One message to Omar listing them; record his answer on each company (Conviction → conflict).",
                "/conviction",
                urgency="high" if top >= 65 else "medium",
                subject=", ".join(names[:6]),
                conflict="potential_conflict / unclear",
                evidence=[
                    f"{e['company']}: "
                    + (
                        portfolio_block(e).replace("_", " ").lower()
                        if portfolio_block(e)
                        else f"conflict = {e.get('conflict')}"
                    )
                    for e in gated[:6]
                ],
            )
        )
    for e in radar["research_queue"]:
        missing = e["_sc"]["missing"]
        if missing == ["traction"]:
            out.append(
                _action(
                    "PREPARE_FOUNDER_CALL",
                    2.5,
                    f"Prepare a founder call: {e['company']}",
                    f"Provisional {e['_sc']['provisional']}; founders and funding are verified — only traction is open, and "
                    "traction is founder-answerable.",
                    "Prepare the traction questions (customers, pilots, paid?) for your call.",
                    f"/conviction?company={e['slug']}",
                    subject=e["company"],
                    conflict=str(e.get("conflict")),
                    contact_appropriate=e.get("conflict") in _CLEAR_CONFLICT and not portfolio_block(e),
                    evidence=[f"missing: {', '.join(missing)}"],
                )
            )
        else:
            ready = _ready_proposals(e)
            out.append(
                _action(
                    "REVIEW_VERIFICATION",
                    (2.8 if ready else 3) - e["_sc"]["provisional"] / 1000,
                    f"1-click verification ready: {e['company']} ({', '.join(ready)})"
                    if ready
                    else f"Verify {e['company']} ({', '.join(missing)})",
                    f"Provisional {e['_sc']['provisional']} ≥ 65 — it enters Radar only once verified (frozen rule)."
                    + (" Deterministic evidence rules already support: " + ", ".join(ready) + "." if ready else ""),
                    "Open Verification: accept or reject each proposal with its evidence; traction stays your judgment.",
                    f"/conviction?company={e['slug']}",
                    subject=e["company"],
                    conflict=str(e.get("conflict")),
                    evidence=[f"missing: {', '.join(missing)}"],
                )
            )
    return out


def _call_actions(inputs: TodayInputs, today: date) -> list[dict[str, Any]]:
    if inputs.founder_calls is UNREADABLE:  # the old ``founder_calls.load()`` raised on a damaged store
        raise ValueError("founder_calls.json could not be read")
    out = []
    for r in due_followups(loaded(inputs.founder_calls), inputs.operator.evaluations, today)[:3]:
        if r.get("due_state") not in ("overdue", "due"):
            continue
        na = r.get("next_action") or {}
        who = r.get("founder_name") or r.get("company_name") or "founder"
        out.append(
            _action(
                "PREPARE_FOUNDER_CALL",
                2,
                f"Follow up: {who}",
                f"Founder-call next action is {r['due_state']}: {na.get('text') or ''}",
                "Do the follow-up you committed to (owner: you).",
                "/founder-calls",
                urgency="high" if r["due_state"] == "overdue" else "medium",
                subject=who,
                evidence=[f"due {na.get('due') or '—'}"],
            )
        )
    return out


def _event_actions(inputs: TodayInputs, today: date) -> list[dict[str, Any]]:
    evs = _listing(inputs.events, today)
    soon = []
    for e in evs:
        if e.get("past") or (e.get("eligibility") or {}).get("tier") != "HIGH-SIGNAL":
            continue  # past / cancelled (REJECTED) / unreviewed events are no attendance decision
        if (e.get("status") or "new") != "new":
            continue  # Mohamed decided: GO (planned), SKIP (skipped) or attended — canonical event status, no copy
        if events.actionable(e)["state"] in ("sold_out", "waitlist"):
            continue  # sold out: nothing to decide, even if not skipped yet
        try:
            start = date.fromisoformat(str(e.get("start") or "")[:10])
        except ValueError:
            continue
        if today <= start <= today + timedelta(days=14):
            soon.append((start, e))
    out = []
    for start, e in sorted(soon, key=lambda x: (x[0], -((x[1].get("sc") or {}).get("total") or 0)))[:2]:
        days = (start - today).days
        out.append(
            _action(
                "EVENT_ACTION",
                4 if days <= 7 else 6,
                f"Decide on {e.get('name')} ({start.isoformat()}, {e.get('city') or '—'})",
                f"High-signal event in {days} day(s). {str((e.get('sc') or {}).get('why') or '')[:160]}",
                "Decide whether to attend; registration is yours — Project Zero never registers.",
                "/events",
                urgency="high" if days <= 3 else "medium",
                subject=str(e.get("name")),
            )
        )
    return out


def _summary(inputs: TodayInputs) -> dict[str, Any]:
    """The old ``compressor.summary()`` over this request's inputs (the old code computed it up to three times)."""
    return compressor.summary(inputs.queue_routing, inputs.live_ids, inputs.operator.config)


def _triage_actions(inputs: TodayInputs) -> list[dict[str, Any]]:
    if inputs.triage is None:  # the old ``triage_review.view()`` raised
        raise ValueError("the triage view could not be computed")
    tri = inputs.triage
    live = [(cid, t) for cid, t in tri.items() if cid in inputs.live_ids and t["routing"]["queue"] == "operating"]
    out = []
    flagged = [(cid, t) for cid, t in live if t["display_proposal"] in ("KNOWN_PORTFOLIO", "ASK_OMAR_CONFLICT")]
    if flagged:
        names = [t["entity"]["display_name"] for _, t in flagged]
        out.append(
            _action(
                "ASK_OMAR_CONFLICT",
                5.5,
                f"{len(flagged)} new candidate(s) touch the Project A portfolio",
                "Machine proposed them, but they are portfolio companies / related / resemble one — Omar decides, not the machine.",
                "Do not contact; mention them to Omar, then accept or override in Deal Flow.",
                "/deal-flow?filter=triage",
                subject=", ".join(names[:5]),
                conflict="portfolio relationship",
                evidence=[f"{t['entity']['display_name']}: {t['portfolio']['status']}" for _, t in flagged[:5]],
            )
        )
    out += _compressed_review(inputs)
    return out


def _compressed_review(inputs: TodayInputs) -> list[dict[str, Any]]:
    """ONE card for the machine-proposal backlog: only what the compressor routed to Mohamed (a prepared case, a
    sparse case the machine cannot move, a weekly calibration sample), capped by the human attention budget."""
    s = _summary(inputs)
    picks = s["today"]
    if not picks:
        return []
    n_need, n_cal = s["needs_mohamed"], s["calibration"]
    parts = [f"{n_need} need your judgment"] if n_need else []
    if n_cal:
        parts.append(f"{n_cal} calibration sample{'s' if n_cal != 1 else ''}")
    c = s["counts"]
    return [
        _action(
            "TRIAGE_REVIEW",
            5 if n_need else 8,  # exceptional judgments before routine; calibration after verification gates
            f"Triage: review {len(picks)} — " + ", ".join(parts),
            f"{s['total']} machine proposals handled: {c['CASE_PREPARING']} queued for case preparation, "
            f"{c['BACKGROUND_RESEARCH']} in the machine research queue (waiting for more evidence), {c['MACHINE_WATCH'] + c['DEFERRED_LOW_PRIORITY']} "
            f"watched / deferred, {c['CONFLICT_GATED']} conflict-gated."
            + (
                f" {s['queued_beyond_budget']} more wait beyond today's budget of {s['limit']}."
                if s["queued_beyond_budget"]
                else ""
            ),
            "Open the list and decide KEEP / RESEARCH / WATCH / DROP for each — your decision, through the usual path."
            + (
                " Calibration samples are companies the machine set aside: your verdict tells it whether that was right."
                if n_cal
                else ""
            ),
            "/deal-flow?filter=triage&route=NEEDS_MOHAMED",
            urgency="medium" if n_need else "low",
            subject=", ".join(p["name"] or "" for p in picks[:4]),
            evidence=[f"{p['name']}: {str(p['reason'])[:110]}" for p in picks[:3]],
        )
    ]


def open_triggers(events_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The old ``watch.open_triggers()`` (:508-509) over the ported ``watch.triggers()``."""
    return [t for t in watch_triggers(events_log) if t["status"] == "new"]


def _watch_actions(inputs: TodayInputs) -> list[dict[str, Any]]:
    """WATCH companies whose reality changed: one action per company with OPEN (unacknowledged) triggers.
    Fired once per distinct evidence (deduplicated in the watch ledger) - identical content never re-alerts."""
    by_co: dict[str, list[dict[str, Any]]] = {}
    for t in open_triggers(inputs.operator.watch_events):
        by_co.setdefault(t["entity_key"], []).append(t)
    out = []
    for trig in by_co.values():
        trig.sort(key=lambda t: (not t["high_value"], t["first_observed"]))
        top = trig[0]
        name = top["name"]
        cid = top.get("candidate_id") or ""
        out.append(
            _action(
                "WATCH_TRIGGER",
                3 if top["high_value"] else 8,
                f"{name}: {top['label'].lower()} — a watched company changed",
                f"You put {name} on WATCH. A sensor found new evidence ({top['source_kind'].replace('_', ' ')}): "
                f"{top['evidence'][:140]}",
                "Open it and decide: move to Research / Keep if this changes the picture, or dismiss the trigger.",
                f"/deal-flow?candidate={cid}" if cid else "/watchlist",
                urgency="high" if top["high_value"] else "low",
                subject=name,
                evidence=[f"{t['label']}: {t['evidence'][:110]} ({t['url'] or t['source']})" for t in trig[:4]],
            )
        )
    return out


def _case_actions(inputs: TodayInputs, now: datetime) -> list[dict[str, Any]]:
    """Prepared cases: ONE exception card per company ("case prepared — N human decisions remain") instead of a list
    of research chores. Machine work in progress is not an action."""
    out = []
    for r in case_prep.summary(_signals(inputs), inputs.operator, now):
        if r["state"] not in ("READY FOR MOHAMED", "WAITING FOR HUMAN") or not r.get("next_action"):
            continue
        n, na = len(r["decisions"]), r["next_action"]
        weak = na.get("code") == "DECIDE_WATCH_OR_DROP"
        fresh = r["state"] == "READY FOR MOHAMED"
        out.append(
            _action(
                "CASE_READY",
                9 if weak else (2.2 if fresh else 4.5),
                f"{r['company']} — case prepared. {n} human decision{'s' if n != 1 else ''} remain{'s' if n == 1 else ''}."
                if n
                else f"{r['company']} — case prepared. Next: {na['label'].lower()}.",
                f"Recommended next action: {na['label']} — {na.get('why', '')}",
                na["label"] + " (the evidence, unknowns and contradictions are on the case).",
                f"/conviction?company={r['slug']}",
                urgency="low" if weak else ("high" if fresh else "medium"),
                subject=r["company"],
                evidence=r["decisions"][:3],
                contact_appropriate=False,
            )
        )
    return out


def _exceptions(actions: list[dict[str, Any]], inputs: TodayInputs) -> list[dict[str, Any]]:
    """WHAT ACTUALLY NEEDS MOHAMED — counts of human-only exceptions (machine work is not counted)."""
    rows: list[tuple[str, int, str]] = []
    cases = [a for a in actions if a["type"] == "CASE_READY" and a["urgency"] != "low"]
    rows.append(("judgment", len(cases), "compan{} need{} your judgment"))
    calls = sum(1 for a in actions if a["type"] == "PREPARE_FOUNDER_CALL") + sum(
        1 for a in cases if a["next_step"].startswith("Prepare a founder call")
    )
    rows.append(("founder_call", calls, "founder call{} worth preparing"))
    omar = sum(len(a["evidence"]) or 1 for a in actions if a["type"] == "ASK_OMAR_CONFLICT")
    rows.append(("omar", omar, "possible portfolio conflict{} for Omar{}"))
    rows.append(
        (
            "watch",
            sum(1 for a in actions if a["type"] == "WATCH_TRIGGER" and a["urgency"] == "high"),
            "Watch trigger{} materially changed",
        )
    )
    rows.append(("event", sum(1 for a in actions if a["type"] == "EVENT_ACTION"), "event{} worth deciding on"))
    if any(a["type"] == "TRIAGE_REVIEW" for a in actions):
        s = _summary(inputs)
        rows.append(("triage", min(s["needs_mohamed"], s["limit"]), "machine proposal{} need{} your judgment"))
    # decision (d): the source-network eligibility is not ported yet: the old fallback (``src = 0``), logged
    log.info("today: %s", SOURCE_DEFERRED)
    src = 0
    rows.append(("source", src, "source{} need{} your trust approval"))
    # decision (d): no scheduler yet: the old fallback when its state was unavailable (the ``jobs`` row is omitted)
    log.info("today: %s", JOBS_DEFERRED)
    out = []
    for key, n, tpl in rows:
        if n:
            one = n == 1
            text = tpl.format(
                "y" if one and "compan" in tpl else "ies" if "compan" in tpl else "" if one else "s", "s" if one else ""
            )
            out.append({"key": key, "n": n, "text": f"{n} {text}"})
    return out


def view(inputs: TodayInputs, today: date, now: datetime) -> dict[str, Any]:
    """The old ``GET /api/today`` body. ``now``: the request instant as naive Berlin wall time; ``today``: its date
    (decision b: one clock for the date, the event window, the contact-state days and the case freshness). Pure:
    ``inputs`` is never modified."""
    plist = inputs.people
    actions: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}
    section: tuple[tuple[str, Callable[[], list[dict[str, Any]]]], ...] = (
        ("pipeline", lambda: _pipeline_actions(_signals(inputs), plist, today)),
        ("calls", lambda: _call_actions(inputs, today)),
        ("events", lambda: _event_actions(inputs, today)),
        ("triage", lambda: _triage_actions(inputs)),
        ("watch", lambda: _watch_actions(inputs)),
        ("cases", lambda: _case_actions(inputs, now)),
    )
    for name, fn in section:
        try:
            got = fn()
            sources[name] = len(got)
            actions += got
        except Exception:  # one broken store must not hide the rest of the day (technical detail: logs / System health)
            log.warning("today: section %s unavailable", name, exc_info=True)
            sources[name] = "temporarily unavailable — the rest of Today is complete"
    # human outcome first: a company Mohamed / Omar judged not worth active work (founder call, Omar −) gets no
    # routine chores on Today until material new evidence re-opens it (it stays in Conviction / WATCH)
    try:
        sig = _signals(inputs)
        op = inputs.operator
        held = {e["company"] for e in sig if human_signals(e, None, op, today)["hold"]}
        contact = {e["company"]: contact_state(e, calls_for(e, op), today, op.config)["state"] for e in sig}
        # a founder call is realistic only once the founder engaged (replied / call booked); first contact only once
        contacted = {c for c, st in contact.items() if st != "NOT_CONTACTED"}
        held |= {c for c, st in contact.items() if st in AWAITING}  # the founder has the ball: no chores
    except Exception:
        log.warning("today: human-outcome hold unavailable", exc_info=True)
        held, contact, contacted = set(), {}, set()

    def founder_step(a: dict[str, Any]) -> dict[str, Any] | None:
        """A founder call is suggested only once the founder engaged; otherwise the step follows the RECORDED contact
        state — contact (you send), follow up once, or nothing while the next move is the founder's."""
        if a["type"] != "PREPARE_FOUNDER_CALL" or not a["link"].startswith("/conviction"):
            return a
        st, who = contact.get(a["subject"], "NOT_CONTACTED"), a["subject"]
        if st in ("REPLIED", "CALL_SCHEDULED"):
            return a
        if st == "NOT_CONTACTED":
            return {**a, "title": f"Contact the founders: {who}",
                    "next_step": "Decide whether to reach out — you send, Project Zero never does; record the outreach "
                    "once sent (the traction questions are prepared)."}  # fmt: skip
        if st == "FOLLOW_UP_DUE":
            return {**a, "title": f"Follow up once: {who}",
                    "next_step": "One follow-up (you send); with still no reply the company returns to Watch."}  # fmt: skip
        return None  # awaiting a reply, no response (Watch) or call already done: nothing for Mohamed today

    actions = [
        a
        for a in actions
        if not (
            a["subject"] in held
            and a["type"] in ("REVIEW_VERIFICATION", "PREPARE_FOUNDER_CALL", "CONTACT_FOUNDER", "CASE_READY")
        )
        and not (a["subject"] in contacted and a["type"] == "CONTACT_FOUNDER")
    ]
    actions = [x for x in (founder_step(a) for a in actions) if x]
    # one company, one card: a prepared case replaces that company's separate verification / call-prep chores
    case_subjects = {a["subject"] for a in actions if a["type"] == "CASE_READY"}
    actions = [
        a
        for a in actions
        if not (
            a["type"] in ("REVIEW_VERIFICATION", "PREPARE_FOUNDER_CALL")
            and a["link"].startswith("/conviction")
            and a["subject"] in case_subjects
        )
    ]
    exceptions = _exceptions(actions, inputs)
    actions.sort(key=lambda a: (a["rank"], {"high": 0, "medium": 1, "low": 2}[a["urgency"]]))
    shown = actions[:MAX_ACTIONS]
    for a in shown:
        a.pop("rank", None)
    return {
        "date": today.isoformat(),
        "actions": shown,
        "more": max(0, len(actions) - MAX_ACTIONS),
        "considered": sources,
        "exceptions": exceptions,
        "machine_working": _machine_working(),
        "triage": _triage_summary(inputs),
        "rules": "Deterministic ranking over existing state; nothing is sent, registered, scored or forwarded.",
        "snapshot": snapshot(inputs),
    }


def _triage_summary(inputs: TodayInputs) -> dict[str, Any] | None:
    """TRIAGE INTELLIGENCE: real derived counts from the last compression run (never computed on this request)."""
    try:
        s = _summary(inputs)
    except Exception:  # Today always loads
        log.warning("today: triage compression summary unavailable", exc_info=True)
        return None
    if not s["at"]:
        return None
    return {k: s[k] for k in ("at", "total", "counts", "needs_mohamed", "calibration", "limit", "queued_beyond_budget", "resurfaced", "labels")}  # fmt: skip


def _machine_working() -> str:
    """No case is ever being prepared (Conviction 011, decision b): the old job and queue are always empty."""
    j: dict[str, Any] = {"current": None, "queued": []}
    n = (1 if j.get("current") else 0) + len(j.get("queued") or [])
    return f"Project Zero is preparing {n} case{'s' if n != 1 else ''} in the background." if n else ""


def snapshot(inputs: TodayInputs) -> dict[str, Any]:
    """Decision (f), the Machine details' note: the triage routes and the prepared cases are the imported snapshot,
    with their original run timestamps (the routes' ``at``, the newest case's ``prepared_at``). New key, declared."""
    q = inputs.queue_routing
    return {
        "note": SNAPSHOT_NOTE,
        "triage_at": q.get("at") if isinstance(q, dict) else None,
        "cases_prepared_at": case_prep.newest_prepared_at(inputs.operator),
    }
