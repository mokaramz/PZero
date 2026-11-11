"""ONE operator state per company — the READ side of the old ``services/case_prep.py``, ported verbatim (review 011).

``operator_status`` (old :1527) with what it reads: ``state_of`` (:1499), ``human_signals`` / ``contact_state``
(founder contact and calls), ``_material_since`` (re-open evidence), ``fingerprint`` (is the prepared case stale) and
``_expired``. The prepared case's next action comes from the IMPORTED case data (``case_prep/cases.json``); nothing
here prepares a case, fetches a page or calls a model (decision b: ``case_prep.request`` is a no-op until the
case-preparation review). Consequently no case is ever PREPARING: the old job queue is always empty here.

Changes: the clock is a parameter (``now``), and the documents the old code loaded itself (founder calls, Active
Evaluator sessions, WATCH triggers, config) come in through ``OperatorInputs`` (``conviction.inputs`` loads them).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from projectzero.conviction.records import list_, records
from projectzero.dealflow.ranking.names import norm_company
from projectzero.dealflow.ranking.names import slug as radar_slug

log = logging.getLogger(__name__)

OUTREACH_KINDS = ("outreach_sent", "follow_up_sent", "reply_received", "call_scheduled")
AWAITING = ("CONTACTED_AWAITING_RESPONSE", "FOLLOWED_UP_AWAITING_RESPONSE")
CALL_OUTCOME = {"Pass": "NEGATIVE", "Monitor": "MIXED", "Follow up": "POSITIVE", "Consider for Omar": "POSITIVE"}
REOPEN_TRIGGERS = (
    "demonstrated technical proof of the claims (e.g. test or field results)",
    "meaningful customer / commercial validation",
    "a major technical milestone",
    "a materially changed fundraising or evidence picture",
)
FRESH_DAYS = 14  # a prepared case older than this is STALE
STATES = (
    "NOT STARTED", "PREPARING", "READY FOR MOHAMED", "WAITING FOR HUMAN", "AWAITING FOUNDER RESPONSE", "WATCHING",
    "BLOCKED", "STALE",
)  # fmt: skip
_EVALUATOR_ORIGIN = re.compile(r"Active Evaluator session (\S+)$")
_FP_FIELDS = (
    "company", "one_liner", "website", "location", "founders", "funding_status", "sources", "verified", "conflict",
    "archetype", "scores", "status", "earliness", "fundraising_timing", "imq_trigger", "twin", "why_found",
    "sent_to_omar", "omar_outcome", "omar_feedback", "omar_outcome_at", "outreach",
)  # fmt: skip


@dataclass(frozen=True)
class OperatorInputs:
    """The documents the old read side loaded from the data folder, as the import stored them."""

    cases: dict[str, Any] = field(default_factory=dict)  # case_prep/cases.json "cases" (slug -> case)
    founder_calls: Any = field(default_factory=dict)  # founder_calls.json (tolerant: unreadable -> {})
    evaluations: Any = field(default_factory=dict)  # evaluations.json (tolerant: unreadable -> {})
    watch_events: list[dict[str, Any]] = field(default_factory=list)  # watch/triggers.jsonl, one dict per line
    config: Any = field(default_factory=dict)  # config.json (tolerant: unreadable -> {})
    case_actions: list[dict[str, Any]] = field(default_factory=list)  # case_prep/actions.jsonl, one dict per line


# ------------------------------------------------------------------------------------------------- helpers
def _sha(*parts: Any) -> str:
    return hashlib.sha1("|".join(json.dumps(p, sort_keys=True, default=str) for p in parts).encode()).hexdigest()[:16]


def provenance_records(value: Any) -> list[dict[str, Any]]:
    """The old ``scout_intake.provenance_records``: the dict records of a stored ``scout_provenance``."""
    if value is None or value == "" or value == []:
        return []
    items = value if isinstance(value, list) else [value]
    return [x for x in items if isinstance(x, dict)]


def _prov(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return provenance_records(entry.get("scout_provenance"))


def is_conversation(call: dict[str, Any], sessions: Any) -> bool:
    """The old ``founder_calls.is_conversation``: every call record stands for a conversation, except one an Active
    Evaluator session wrote on End although the founder answered nothing and that nobody edited since."""
    m = _EVALUATOR_ORIGIN.match(str(call.get("objective") or ""))
    if not m or call.get("updated") != call.get("created") or (call.get("assessment") or {}).get("recommendation"):
        return True
    s = sessions.get(m.group(1)) if isinstance(sessions, dict) else None
    ended = (s or {}).get("ended") if isinstance(s, dict) else None
    return not isinstance(ended, dict) or bool(ended.get("answers"))  # an unknown session: the record stands


def conversations(d: dict[str, Any], evaluations: Any) -> dict[str, dict[str, Any]]:
    sessions = (evaluations or {}).get("sessions") or {}
    calls: dict[str, Any] = d["calls"] if isinstance(d.get("calls"), dict) else {}
    return {k: c for k, c in calls.items() if isinstance(c, dict) and is_conversation(c, sessions)}


def watch_triggers(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The old ``watch.triggers()``: fired triggers with their CURRENT status (later status lines override)."""
    rows: list[dict[str, Any]] = []
    status: dict[Any, dict[str, Any]] = {}
    for e in records(events):
        if e.get("kind") == "status":
            if e.get("trigger_id"):
                status[e["trigger_id"]] = e
        elif e.get("id"):
            rows.append(dict(e))
    for r in rows:
        s = status.get(r["id"])
        r["status"] = s.get("status", "new") if s else "new"
        r["status_at"] = s.get("at", "") if s else ""
        for k, v in (
            ("entity_key", r.get("name") or r["id"]),
            ("high_value", False),
            ("first_observed", ""),
            ("evidence", ""),
            ("source_kind", ""),
            ("url", ""),
            ("label", r.get("predicate") or "change"),
        ):
            if r.get(k) is None:
                r[k] = v
    return rows


# ------------------------------------------------------------------------------------------------- fingerprints
def fingerprint(entry: dict[str, Any], inp: OperatorInputs) -> str:
    """What the case was prepared from. Any change -> the case is STALE."""
    return _sha(
        {k: entry.get(k) for k in _FP_FIELDS},
        len(_prov(entry)),
        [(f.get("url"), f.get("claim")) for f in entry.get("bridge_findings") or [] if isinstance(f, dict)],
        [(c.get("id"), c.get("updated"), (c.get("assessment") or {}).get("recommendation")) for c in calls_for(entry, inp)],
    )  # fmt: skip


# ------------------------------------------------------------------------------------ human signals (routing only)
def calls_for(entry: dict[str, Any], inp: OperatorInputs) -> list[dict[str, Any]]:
    """Founder calls recorded for this Conviction company, oldest first (old ``case_prep.calls_for``)."""
    fc = inp.founder_calls or {}
    slug, nk = (
        entry.get("slug") or radar_slug(entry.get("company") or ""),
        norm_company(entry.get("company") or ""),
    )
    cos = {
        c.get("id") for c in records(fc.get("companies"), ("id",))
        if c.get("id") and (
            (slug and c.get("linked_pipeline_slug") == slug)
            or (nk and not c.get("linked_pipeline_slug") and norm_company(c.get("name") or "") == nk)
        )
    }  # fmt: skip
    rows = records(fc.get("calls"), ("id",))
    talks = conversations({"calls": {c["id"]: c for c in rows}}, inp.evaluations)
    calls = [c for c in talks.values() if c.get("company_id") and c.get("company_id") in cos]
    return sorted(calls, key=lambda c: (str(c.get("date") or ""), str(c.get("updated") or c.get("created") or "")))


def _material_since(entry: dict[str, Any], since: str, calls: list[dict[str, Any]], inp: OperatorInputs) -> list[str]:
    """Material evidence that arrived AFTER ``since`` (the latest negative human signal)."""
    if not since:
        return []
    out = []
    nk = norm_company(entry.get("company") or "")
    try:
        for t in watch_triggers(inp.watch_events):
            if (
                t.get("high_value")
                and norm_company(t.get("name") or "") == nk
                and str(t.get("first_observed") or "") > since
            ):
                out.append(f"WATCH: {t.get('label') or 'material change'} ({str(t.get('first_observed'))[:10]})")
    except Exception:  # an unreadable WATCH log never blocks routing
        log.warning("case %s: WATCH triggers unavailable for re-open check", entry.get("company"), exc_info=True)
    for p in _prov(entry):
        if str(p.get("recorded") or "") > since:
            out.append(f"new Scout signal ({str(p.get('recorded'))[:10]})")
    t = entry.get("imq_trigger") or {}
    if isinstance(t, dict) and str(t.get("recorded") or "") > since:
        out.append(f"why-now trigger recorded ({str(t.get('recorded'))[:10]})")
    for c in calls:
        when = str(c.get("updated") or c.get("date") or "")
        if when > since and CALL_OUTCOME.get((c.get("assessment") or {}).get("recommendation") or "") == "POSITIVE":
            out.append(
                f"later founder call rated '{(c.get('assessment') or {}).get('recommendation')}' ({str(c.get('date'))[:10]})"
            )
    return out


def outreach_policy(config: Any) -> tuple[int, int]:
    """(days before ONE follow-up is due, days after that follow-up before the company returns to WATCH)."""
    cfg = (config or {}).get("outreach") or {}
    try:
        return max(3, int(cfg.get("follow_up_after_days", 10))), max(7, int(cfg.get("watch_after_days", 21)))
    except (TypeError, ValueError):
        return 10, 21


def contact_state(entry: dict[str, Any], calls: list[dict[str, Any]], today: date, config: Any) -> dict[str, Any]:
    """Founder-contact state from what Mohamed RECORDED (outreach log, Conviction status, founder calls)."""
    ev = sorted(
        (x for x in list_(entry.get("outreach")) if isinstance(x, dict) and x.get("kind") in OUTREACH_KINDS),
        key=lambda x: str(x.get("date") or ""),
    )

    def last(kind: str) -> dict[str, Any] | None:
        return next((x for x in reversed(ev) if x["kind"] == kind), None)

    def days(x: dict[str, Any] | None) -> int | None:
        try:
            return (today - date.fromisoformat(str((x or {}).get("date") or "")[:10])).days
        except ValueError:
            return None

    follow, watch_after = outreach_policy(config)
    hist = [{k: x.get(k) for k in ("kind", "date", "channel", "note")} for x in ev]
    done = [c for c in calls if str(c.get("date") or "")[:10] <= today.isoformat()]
    booked = [c for c in calls if str(c.get("date") or "")[:10] > today.isoformat()]
    sched = last("call_scheduled")

    def out(state: str, label: str, since: str = "") -> dict[str, Any]:
        return {
            "state": state,
            "label": label,
            "since": since,
            "history": hist,
            "policy": {"follow_up_after_days": follow, "watch_after_days": watch_after},
        }

    if done:
        when = str(done[-1].get("date"))[:10]
        return out("CALL_COMPLETED", f"CALL COMPLETED — {when}", when)
    if booked or (sched and (days(sched) or 0) <= 0):
        when = str((booked[0] if booked else sched or {}).get("date"))[:10]
        return out("CALL_SCHEDULED", f"CALL SCHEDULED — {when}", when)
    reply = last("reply_received")
    if reply or entry.get("status") == "replied":
        return out(
            "REPLIED", "REPLIED" + (f" — {reply['date']}" if reply else ""), str((reply or {}).get("date") or "")
        )
    fu, first = last("follow_up_sent"), last("outreach_sent")
    if fu:
        d = days(fu)
        if d is not None and d >= watch_after:
            return out("NO_RESPONSE_WATCH", f"NO RESPONSE — outreach and one follow-up (last {fu['date']})", fu["date"])
        return out("FOLLOWED_UP_AWAITING_RESPONSE", f"AWAITING RESPONSE — follow-up sent {fu['date']}", fu["date"])
    if first:
        d = days(first)
        if d is not None and d >= follow:
            return out(
                "FOLLOW_UP_DUE", f"FOLLOW-UP DUE — outreach sent {first['date']}, no reply in {d} days", first["date"]
            )
        return out("CONTACTED_AWAITING_RESPONSE", f"AWAITING RESPONSE — outreach sent {first['date']}", first["date"])
    if entry.get("status") == "contacted":  # marked contacted without a date: waiting, no follow-up timing claimed
        return out("CONTACTED_AWAITING_RESPONSE", "AWAITING RESPONSE — marked contacted (date not recorded)")
    return out("NOT_CONTACTED", "NOT CONTACTED")


def human_signals(
    entry: dict[str, Any], case: dict[str, Any] | None, inp: OperatorInputs, today: date
) -> dict[str, Any]:
    """What HUMAN interaction says about whether the company is worth active work now. Routing only."""
    calls = calls_for(entry, inp)
    last = calls[-1] if calls else None
    rec = ((last or {}).get("assessment") or {}).get("recommendation") or ""
    outcome = CALL_OUTCOME.get(rec, "NO CONCLUSION") if last else ""
    omar = entry.get("omar_outcome") if entry.get("omar_outcome") in ("positive", "negative") else ""
    omar_at = str(entry.get("omar_outcome_at") or (case or {}).get("omar_seen_at") or "")
    negatives = []
    if omar == "negative":
        negatives.append(("Omar feedback negative", omar_at))
    if outcome in ("NEGATIVE", "MIXED"):
        assert last is not None
        negatives.append((f"your call outcome: {rec}", str(last.get("updated") or last.get("date") or "")))
    contact = contact_state(entry, calls, today, inp.config)
    if contact["state"] == "NO_RESPONSE_WATCH":
        negatives.append(("founder non-response — outreach and one follow-up, no reply", contact["since"]))
    since = max((w for _r, w in negatives if w), default="")
    reopen = _material_since(entry, since, calls, inp) if negatives else []
    hold = bool(negatives) and not reopen
    reasons = [r for r, _w in negatives]
    if last:
        reasons.insert(0, f"founder call completed ({str(last.get('date'))[:10]})")
    note = (
        str(((last or {}).get("next_action") or {}).get("text") or "")
        if isinstance((last or {}).get("next_action"), dict)
        else ""
    )
    triggers = list(REOPEN_TRIGGERS) + [
        f"an answer to: {q}" for q in ((last or {}).get("open_questions") or [])[:2] if isinstance(q, str)
    ]
    if contact["state"] == "NO_RESPONSE_WATCH":
        triggers = [
            "the founder replies",
            "a material company development",
            "a new funding / customer / technical signal",
            "a new warm introduction becomes available",
        ]
    return {
        "calls": [
            {
                "id": c.get("id"),
                "date": str(c.get("date") or "")[:10],
                "type": c.get("call_type") or "",
                "outcome": CALL_OUTCOME.get(((c.get("assessment") or {}).get("recommendation")) or "", "NO CONCLUSION"),
                "recommendation": (c.get("assessment") or {}).get("recommendation") or "",
                "next_action": str((c.get("next_action") or {}).get("text") or "")
                if isinstance(c.get("next_action"), dict)
                else "",
                "observations": str(c.get("observations") or "")[:400],
            }
            for c in calls
        ],
        "last_outcome": outcome,
        "omar": {"outcome": omar, "feedback": str(entry.get("omar_feedback") or "")[:400], "at": omar_at},
        "hold": hold,
        "reasons": reasons,
        "reopen_evidence": reopen,
        "reopen_triggers": triggers if hold else [],
        "your_note": note,
        "contact": contact,
        "label": "HUMAN JUDGMENT — your own notes and Omar's feedback; routing only, never a public fact or a score",
    }


def _expired(case: dict[str, Any], now: datetime) -> bool:
    try:
        at = datetime.fromisoformat(str(case.get("prepared_at") or "")[:19])
    except ValueError:
        return True
    return now - at > timedelta(days=FRESH_DAYS)


# --------------------------------------------------------------------------------------------- read side
def state_of(
    slug: str, case: dict[str, Any] | None, entry: dict[str, Any] | None, inp: OperatorInputs, now: datetime
) -> dict[str, str]:
    try:
        return _state_of(slug, case, entry, inp, now)
    except Exception:  # the case store is derived: an unreadable case is simply prepared again
        log.warning("case %s: stored case could not be read — marked stale", slug, exc_info=True)
        return {"state": "STALE", "why": "the stored case could not be read — it is prepared again automatically"}


def _state_of(
    slug: str, case: dict[str, Any] | None, entry: dict[str, Any] | None, inp: OperatorInputs, now: datetime
) -> dict[str, str]:
    # the old job queue (PREPARING) is always empty here: case preparation is not ported (decision b)
    if not case or not case.get("card"):
        if case and case.get("error"):
            return {"state": "BLOCKED", "why": "preparation could not finish: " + case["error"]}
        return {"state": "NOT STARTED", "why": "not prepared yet"}
    if entry is not None and fingerprint(entry, inp) != case.get("fingerprint"):
        return {"state": "STALE", "why": "the record changed since the case was prepared — refreshed automatically"}
    if case.get("stale_reason"):
        return {"state": "STALE", "why": case["stale_reason"]}
    if _expired(case, now):
        return {"state": "STALE", "why": f"prepared more than {FRESH_DAYS} days ago"}
    card = case["card"]
    if (card.get("next_action") or {}).get("code") == "NO_ACTIVE_WORK":
        return {"state": "WATCHING", "why": "no active work — watching for material change (human outcome)"}
    if (card.get("next_action") or {}).get("code") == "AWAIT_FOUNDER_RESPONSE":
        return {"state": "AWAITING FOUNDER RESPONSE", "why": "outreach sent — the next move is the founder's"}
    if card["conflict"]["gated"]:
        return {"state": "BLOCKED", "why": "a portfolio conflict question is open — Omar decides"}
    if card["decisions"] and str(case.get("seen_at") or "") >= str(case.get("prepared_at") or ""):
        return {"state": "WAITING FOR HUMAN", "why": f"{len(card['decisions'])} decision(s) are yours"}
    return {"state": "READY FOR MOHAMED", "why": f"{len(card['decisions'])} human decision(s) remain"}


def operator_status(entry: dict[str, Any], case: Any, inp: OperatorInputs, now: datetime) -> dict[str, Any]:
    """ONE current operator state per company. Priority: (1) human / case state (a human-outcome hold -> WATCHING),
    (2) active gate (portfolio conflict), (3) the prepared case's current next action, (4) the score band — only when
    nothing else applies. The score band is always returned separately as descriptive context. Read-only."""
    sc = entry.get("sc") or {}
    band = str(sc.get("verdict") or "")
    out: dict[str, Any] = {"score_band": band}
    slug = entry.get("slug") or radar_slug(entry.get("company") or "")
    try:
        if case is None:
            case = inp.cases.get(slug)
        hum = human_signals(entry, case if isinstance(case, dict) else None, inp, now.date())
        if hum["hold"]:
            return {**out, "status": "WATCHING", "action": "No active work — watch for material change",
                    "why": "; ".join(hum["reasons"]), "tone": "neutral", "source": "human outcome"}  # fmt: skip
        if entry.get("conflict") in ("potential_conflict", "unclear"):
            return {**out, "status": "CONFLICT GATED", "action": "Ask Omar about the possible portfolio conflict",
                    "why": f"conflict recorded as {entry.get('conflict')}", "tone": "red", "source": "conflict gate"}  # fmt: skip
        st = state_of(slug, case, entry, inp, now) if case else {"state": "NOT STARTED"}
        card = (case or {}).get("card") if isinstance(case, dict) else None
        na = (card or {}).get("next_action") if isinstance(card, dict) else None
        if isinstance(na, dict) and na.get("label") and st["state"] != "NOT STARTED":
            status = {"STALE": "REFRESHING CASE", "PREPARING": "PREPARING CASE"}.get(st["state"], st["state"])
            gated = na.get("code") == "ASK_OMAR"
            return {**out, "status": "CONFLICT GATED" if gated else status, "action": na["label"],
                    "why": str(na.get("why") or ""), "tone": "red" if gated else ("neutral" if status in ("AWAITING FOUNDER RESPONSE", "WATCHING") else "amber"), "source": "prepared case"}  # fmt: skip
        if hum["contact"]["state"] in AWAITING and not hum["calls"]:
            return {**out, "status": "AWAITING FOUNDER RESPONSE", "action": "No action — the next move is the founder's",
                    "why": hum["contact"]["label"], "tone": "neutral", "source": "founder contact"}  # fmt: skip
    except Exception:  # an unreadable case / call store never hides the company — the score band still shows
        log.warning("operator status for %s fell back to the score band", entry.get("company"), exc_info=True)
    return {**out, "status": band.upper() or "NOT ASSESSED", "action": band, "why": "score band — no prepared case yet",
            "tone": "amber", "source": "score band"}  # fmt: skip


def case_view(slug: str, entry: dict[str, Any] | None, inp: OperatorInputs, now: datetime) -> dict[str, Any]:
    """The old ``case_prep.view`` (:1565), READ-ONLY, from the imported case data: no ``case_seen`` write, no
    preparation. ``entry`` is the enriched pipeline record of ``slug`` (None if there is none), as the old
    ``pipeline.find_signal`` gave it."""
    case = inp.cases.get(slug) or {}
    st = (
        state_of(slug, case, entry, inp, now)
        if entry is not None or not case
        else _state_without_entry(slug, case, inp, now)
    )
    return {
        "slug": slug,
        **st,
        "states": STATES,
        "prepared_at": case.get("prepared_at"),
        "prepared_for": case.get("prepared_for"),
        "card": case.get("card"),
        "steps": case.get("steps") or [],
        "usd": case.get("usd", 0.0),
        "audit": [r for r in inp.case_actions if r.get("slug") == slug][-40:],
    }


def _state_without_entry(slug: str, case: Any, inp: OperatorInputs, now: datetime) -> dict[str, str]:
    """``state_of`` for a case whose company is not in the pipeline (old: no fingerprint check without an entry)."""
    try:
        return _state_of(slug, case, None, inp, now)
    except Exception:
        return {"state": "STALE", "why": "the stored case could not be read — it is prepared again automatically"}
