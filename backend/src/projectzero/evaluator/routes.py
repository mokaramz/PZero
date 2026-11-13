"""The old ``api/routers/evaluator.py`` (rev 6c739b9) as pure functions over the evaluations document (review 024).

Each function answers what the old route answered (status + body): ``GET evaluation`` with an unknown id is the old
404 ``{"error": "unknown session"}`` (``None`` here); every action refusal is the old HTTP 200 ``{"ok": false,
"error"}``; every session action except ``start`` carries ``session`` / ``panel`` / ``row`` (``start``: ``panel``),
and an unknown session answers without them. The writes never change their input: they work on a copy and return an
``Outcome`` whose ``doc`` is the evaluations document as the old route left ``evaluations.json`` — the INPUT object
itself when the session did not change (decision c: a refusal that changed nothing writes nothing), else a new
document (only the touched session is copied) — with ``changed`` the ids of the new or changed sessions. Review 036a:
an ``evidence`` or ``imq_trigger`` body whose ``confirm`` is supplied but is not a JSON boolean is a 400
``{ok: false, error}`` (without the session), decided before the session lookup: nothing is written.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from projectzero.conviction import imq
from projectzero.core.body import BadConfirm, confirmed
from projectzero.dealflow.ranking.names import slug as radar_slug
from projectzero.evaluator import core
from projectzero.evaluator.core import ConvictionChange
from projectzero.founder_calls import routes as founder_calls_routes
from projectzero.network.view import berlin_now

UNKNOWN_SESSION = "unknown session"
UNKNOWN_ACTION = "unknown evaluator action"
ACTIONS = ("start", "deck", "next", "skip", "answer", "evidence", "resolve", "end")


@dataclass(frozen=True)
class Outcome:
    status: int  # the old HTTP status (200 for the actions; 400 for a malformed evidence `confirm`, review 036a)
    body: dict[str, Any]  # the old answer
    doc: Any  # the evaluations document after the request (the input object when nothing changed)
    changed: list[str] = field(default_factory=list)  # the ids of the new / changed sessions, in document order
    founder_calls: founder_calls_routes.Outcome | None = None  # end: the Founder Calls write (None: no call saved)
    conviction: tuple[ConvictionChange, ...] = ()  # end: the changed Conviction records (linked session)


@dataclass(frozen=True)
class TriggerOutcome:
    status: int  # the old HTTP status (200, also for a refusal; 400 for a malformed `confirm`, review 036a)
    body: dict[str, Any]  # the old answer: {ok, trigger} or {ok: false, error}
    conviction: tuple[ConvictionChange, ...] = ()  # the changed Conviction records (empty: refused, nothing saved)


def loaded(doc: Any) -> dict[str, Any]:
    """The old ``load()`` over a stored body: missing (``None``) or not a dict -> ``{"sessions": {}}``; a missing
    ``sessions`` is appended (a shallow copy, the input is never changed)."""
    d = dict(doc) if isinstance(doc, dict) else {}
    d.setdefault("sessions", {})
    return d


def _same(a: Any, b: Any) -> bool:
    """Equal content AND key order (what a re-serialized file would show)."""
    return bool(a == b) and json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)


# ------------------------------------------------------------------ reads
def workspace(doc: Any) -> dict[str, Any]:
    """``GET /api/evaluations``: the sessions strip (newest ``created`` first; ties keep the document order, the old
    stable sort), the states, the families and the labels."""
    return core.workspace(loaded(doc))


def session_view(
    doc: Any, session_id: Any, *, conviction: Any, people: list[dict[str, Any]], today: date
) -> dict[str, Any] | None:
    """``GET /api/evaluation?id=``: ``{session, panel, next}``; ``None`` -> 404 ``{"error": "unknown session"}``.
    ``next`` is the first question without an answer, a SKIPPED one included (the old quirk, decision b)."""
    sd = loaded(doc).get("sessions", {}).get(session_id)
    if not sd:
        return None
    nxt = None if sd.get("status") == "ended" else next((x for x in sd["questions"] if x.get("answer") is None), None)
    return {"session": sd, "panel": core.panel(sd, conviction, people, today), "next": nxt}


# ------------------------------------------------------------------ writes
def start(
    doc: Any,
    body: dict[str, Any],
    *,
    conviction: Any,
    people: list[dict[str, Any]],
    radar_companies: Any,
    today: date,
    now: datetime,
    new_hex: Callable[[], str] | None = None,
) -> Outcome:
    """``POST eval_start {subject: {kind, name, founder, slug, person_id}}``: a new session, appended last."""
    ck = core.clock(now, today, new_hex)
    d = loaded(doc)
    d["sessions"] = dict(d["sessions"])
    sd = core.start(d, ck, body.get("subject") or {}, conviction, radar_companies)
    nq = core.next_question(sd, ck)
    answer = {"ok": True, "id": sd["id"], "session": sd, "next": nq, "panel": core.panel(sd, conviction, people, today)}
    return Outcome(200, answer, d, [sd["id"]])


def action(
    act: str,
    doc: Any,
    body: dict[str, Any],
    *,
    conviction: Any,
    people: list[dict[str, Any]],
    radar_companies: Any = None,
    founder_calls: Any = None,
    today: date,
    now: datetime,
    new_hex: Callable[[], str] | None = None,
) -> Outcome:
    """The old ``POST /api/eval_{act}``: ``start`` (above), else ``body.id`` names the session (unknown: ``{ok: false,
    error: "unknown session"}``) and ``act`` is ``deck {text}``, ``next``, ``skip {qid}``, ``answer {qid, text}``,
    ``evidence {claim_id, url, label, note, kind, confirm}``, ``resolve {claim_id, note}``, ``end {call_type,
    channel}``, or anything else (``{ok: false, error: "unknown evaluator action"}`` with the session, panel and
    row). ``founder_calls``: the founder_calls document (``end`` only)."""
    if act == "start":
        return start(doc, body, conviction=conviction, people=people, radar_companies=radar_companies, today=today,
                     now=now, new_hex=new_hex)  # fmt: skip
    confirm = False
    if act == "evidence":  # review 036a: only JSON true confirms; a malformed value is a 400 for either kind
        try:
            confirm = confirmed(body)
        except BadConfirm as exc:
            return Outcome(400, {"ok": False, "error": str(exc)}, doc)
    ck = core.clock(now, today, new_hex)
    base = loaded(doc)
    sid = body.get("id") or ""
    original = base["sessions"].get(sid)
    if not original:
        return Outcome(200, {"ok": False, "error": UNKNOWN_SESSION}, doc)
    d = dict(base)
    d["sessions"] = dict(base["sessions"])
    sd = copy.deepcopy(original)
    d["sessions"][sid] = sd
    r: dict[str, Any]
    ended: core.Ended | None = None
    if act == "deck":
        r = core.import_deck(sd, ck, body.get("text", ""))
    elif act == "next":
        r = {"ok": True, "next": core.next_question(sd, ck)}
    elif act == "skip":
        r = core.skip(sd, ck, body.get("qid"))
    elif act == "answer":
        r = core.answer(sd, ck, body.get("qid"), body.get("text", ""))
    elif act == "evidence":
        r = core.attach_evidence(
            sd,
            ck,
            body.get("claim_id"),
            body.get("url", ""),
            body.get("label", ""),
            body.get("note", ""),
            body.get("kind", "public"),
            confirm,
        )
    elif act == "resolve":
        r = core.resolve_contradiction(sd, ck, body.get("claim_id"), body.get("note", ""))
    elif act == "end":
        ended = core.end(sd, ck, body, conviction=conviction, people=people, founder_calls=founder_calls)
        r = {"ok": True, "ended": ended.ended}
    else:
        r = {"ok": False, "error": UNKNOWN_ACTION}
    # Pre-GO: every action returns the fresh session, panel and strip row
    r.setdefault("session", sd)
    r["panel"] = core.panel(sd, conviction, people, today)
    r["row"] = core.session_row(sd)
    fc = ended.founder_calls if ended else None
    changes = ended.conviction if ended else ()
    if _same(sd, original):
        return Outcome(200, r, doc, [], fc, changes)
    return Outcome(200, r, d, [sid], fc, changes)


class SessionAction(Protocol):
    """``deck``, ``next_question``, ``skip``, ``answer``, ``attach_evidence``, ``resolve``: ``action(act, ...)``."""

    def __call__(
        self,
        doc: Any,
        body: dict[str, Any],
        *,
        conviction: Any,
        people: list[dict[str, Any]],
        today: date,
        now: datetime,
        new_hex: Callable[[], str] | None = None,
    ) -> Outcome: ...


def _session_action(act: str) -> SessionAction:
    def run(
        doc: Any,
        body: dict[str, Any],
        *,
        conviction: Any,
        people: list[dict[str, Any]],
        today: date,
        now: datetime,
        new_hex: Callable[[], str] | None = None,
    ) -> Outcome:
        return action(act, doc, body, conviction=conviction, people=people, today=today, now=now, new_hex=new_hex)

    run.__name__ = run.__qualname__ = {"next": "next_question", "evidence": "attach_evidence"}.get(act, act)
    run.__doc__ = f"``POST eval_{act}``: ``action({act!r}, doc, body, ...)``."
    return run


deck = _session_action("deck")
next_question = _session_action("next")
skip = _session_action("skip")
answer = _session_action("answer")
attach_evidence = _session_action("evidence")
resolve = _session_action("resolve")


def end(
    doc: Any,
    body: dict[str, Any],
    *,
    conviction: Any,
    people: list[dict[str, Any]],
    founder_calls: Any,
    today: date,
    now: datetime,
    new_hex: Callable[[], str] | None = None,
) -> Outcome:
    """``POST eval_end {id, call_type?, channel?}``: ``action("end", ...)``. ``founder_calls``: the founder_calls
    document (``None``: none yet). ``Outcome.founder_calls``: the Founder Calls ``save`` outcome (``None`` when no
    founder answer was recorded, or the session had already ended); ``Outcome.conviction``: the linked records."""
    return action("end", doc, body, conviction=conviction, people=people, founder_calls=founder_calls, today=today,
                  now=now, new_hex=new_hex)  # fmt: skip


def imq_trigger(body: dict[str, Any], *, conviction: Any, today: date, now: datetime) -> TriggerOutcome:
    """``POST /api/imq_trigger {slug, kind, date, url, fact, confirm}``: an operator-recorded, sourced, dated why-now
    trigger on every Conviction record whose radar slug is ``slug`` (the old loop; the last answer wins). The records
    change only when the answer is ``ok`` (the old route saved only then). A ``confirm`` that is not a JSON boolean
    is a 400 ``{ok: false, error}`` (review 036a)."""
    try:
        confirm = confirmed(body)
    except BadConfirm as exc:
        return TriggerOutcome(400, {"ok": False, "error": str(exc)})
    r: dict[str, Any] = {"ok": False, "error": "unknown company"}
    changes = []
    for i, e in core._indexed(conviction):
        if radar_slug(e["company"]) == body.get("slug"):
            x = copy.deepcopy(e)
            r = imq.record_trigger(
                x, body.get("kind"), body.get("date"), body.get("url"), body.get("fact"), confirm,
                now=berlin_now(now).replace(tzinfo=None), today=today,
            )  # fmt: skip
            if r.get("ok"):
                changes.append(ConvictionChange(i, radar_slug(e["company"]), x))
    return TriggerOutcome(200, r, tuple(changes) if r.get("ok") else ())
