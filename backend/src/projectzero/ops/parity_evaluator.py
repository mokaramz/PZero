# ruff: noqa: E501
# (the synthetic corpus and the write script: one case per line)
"""Active Evaluator parity: the pure port against the OLD code as oracle, with a FIXED clock (review 024).

    python -m projectzero.ops.parity_evaluator goldens   # (re)generates golden_v1/oracle_evaluator.json
    python -m projectzero.ops.parity_evaluator real      # the real snapshot, imported, through the API routes

The oracle (``scripts/oracle/evaluator_oracle.py``) runs the old route functions of ``api/routers/evaluator.py`` over a
scratch data folder: ``GET evaluations``, every session view, and a write script (``eval_<act>``, ``imq_trigger``)
with the answer, the whole ``GET evaluations`` body, the stored evaluations.json (body + session key ORDER), the
stored founder_calls.json (body + key order) and the stored real_data.json ``signals`` after each step. The old
``uuid4`` is a counter on both sides (the n-th hex is ``f"{n:06x}" + "0" * 26``). The new side is the PURE port
(``evaluator.routes``): each write's ``Outcome.doc`` is the next step's evaluations document, ``Outcome.founder_calls``
its founder_calls document and ``Outcome.conviction`` / ``TriggerOutcome.conviction`` replace the Conviction records.

The synthetic data folders hold INVENTED names only. ``main``: an evaluations.json whose sessions INSERTION order
differs from the JSONB order (a long id first, a short id last), two of them sharing the same ``created``, an ended
session, a session with a skipped question (``GET evaluation`` ``next`` includes it); three Conviction records (a
fresh round from research within 180 days, an old research round with the verified-funding fallback, a conflict
"unclear" record), people, radar companies (confirmed / unconfirmed / foreign facts) and a founder_calls.json. Its
write script: starts (by slug, by name, external, empty subject, linked and tied on ``created``), a deck with numeric
and count claims (and a negated count), next, skip (twice, unknown, already answered), answers (a revenue figure
against the deck, a round "in 6 months" against a fresh round, UNKNOWN, an empty answer, an overwrite, an unknown id,
the "unknown" follow-up), public and operator evidence (twice on one claim, no label, every refusal), resolve (twice,
unknown, not a contradiction), an unknown action and session, ``imq_trigger`` (each refusal and a success), ends
(with and without answers, linked and external, a repeat), actions on an ended session and a final read at a later
day. ``empty``: no files at all. Identical recorded values are stored once (``{"same_as": step}`` /
``{"same_record": step}``). Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import itertools
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.evaluator import routes
from projectzero.network.view import berlin_today
from projectzero.ops.parity_founder_calls import company, founder, utc_instant
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "evaluator_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_evaluator.json"
CLOCK = "2026-11-12T10:00:00"
LATER = "2026-11-20T08:00:00"
FC_OBJECTS = ("companies", "founders", "calls")
RECORDED = ("view", "calls", "signals")

# ------------------------------------------------------------------ the synthetic data folder (invented names only)
# fmt: off
LATTICE, QUARRY, ORBIT = "Invented Lattice Freight GmbH", "Invented Quarry Health", "Invented Orbit Tools"
LONG_ID, MID_ID, SHORT_ID = "ev-20261001093000-longaa", "ev-20261005100000-mid002", "e9"


def signals() -> list[dict[str, Any]]:
    return [
        {"company": LATTICE, "status": "new", "one_liner": "AI quoting for freight forwarders with supplier negotiation",
         "founders": [{"name": "Ada Inventa"}, {"name": "Bo Fictiv"}],
         "scores": {"founder": 22, "venture_scale": 15, "why_now": 12, "taste": 12, "insight": 6},
         "verified": {"founders": True, "traction": False, "funding": True}, "conflict": "none",
         "twin": "Invented Twin Labs", "why_now_text": "", "funding_status": "Raised a seed round in 2026",
         "earliness": "seed", "fundraising_timing": "unknown", "verify_list": ["Check the seed round"],
         "sources": ["https://invented.example/lattice"], "discovery_date": "2026-10-01"},
        {"company": QUARRY, "status": "contacted", "one_liner": "Clinical documentation for invented clinics",
         "founders": [{"name": "Cy Nowhere"}], "scores": {"founder": 8, "venture_scale": 8, "why_now": 6},
         "verified": {"founders": False, "funding": True}, "conflict": "unclear", "why_now_text": "EU MDR deadline",
         "funding_status": "Closed a pre-seed round", "earliness": "pre_seed"},
        {"company": ORBIT, "founders": ["Di Hidden"], "scores": {}, "verified": {}},
    ]


def people() -> list[dict[str, Any]]:
    return [
        {"id": "p-ada", "name": "Ada Inventa", "identity_status": "verified by operator"},
        {"id": "p-bo", "name": "Bo Fictiv", "provenance": "user_provided"},
        {"id": "p-cy", "name": "Cy Nowhere"},
    ]


def radar_companies() -> dict[str, Any]:
    def fact(fld: str, claim: str, day: str = "", confirmed: bool = True, url: str = "https://invented.example/f") -> dict[str, Any]:
        return {"field": fld, "claim": claim, "confirmed": confirmed, "source_url": url, "activity_date": day}
    return {"companies": {
        "rc-lattice": {"name": "Invented Lattice Freight GmbH", "facts": [
            fact("funding", "Seed round of €2.5m closed", "2026-09-01"), fact("founded", "Founded in 2024"),
            fact("recent_activity", "Launched the quoting API", "2026-10-20", confirmed=False),
            fact("headcount", "40 people"), fact("stage", "Seed", url="not-a-url")]},
        "rc-quarry": {"name": "invented quarry health", "facts": [
            fact("funding", "Pre-seed of €600k", "2025-01-10"),
            fact("recent_activity", "Pilot with an invented clinic", "2026-10-20")]},
    }}


def ctx(name: str, slug: str = "", **kw: Any) -> dict[str, Any]:
    return {"kind": "company" if slug else "external", "name": name, "founder": "", "slug": slug, "person_id": "",
            "adjacent": [], **kw}


def claim(cid: str, family: str, text: str, state: str, **kw: Any) -> dict[str, Any]:
    return {"id": cid, "family": family, "text": text, "state": state, "source": "pitch deck",
            "created": "2026-10-01 09:31", "resolved": False, "evidence": [], "related": [], **kw}


def session(sid: str, created: str, subject: dict[str, Any], context: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return {"id": sid, "created": created, "updated": created, "status": "open", "subject": subject,
            "context": context, "deck": {"text": "", "imported_at": "", "claims": []}, "ledger": [],
            "questions": [], "queue": [], "covered": [], "provisional": {}, "tasks": [], "memo_deltas": [],
            "ended": {}, "plan": [], **kw}


def evaluations() -> dict[str, Any]:
    tie = "2026-10-01 09:30"
    skipped_q = {"family": "traction", "text": "What traction is real today?", "kind": "opening", "reason": "x",
                 "verification_hint": "y", "id": "q-skipped01", "asked_at": tie, "answer": None, "skipped": tie}
    answered_q = {"family": "problem", "text": "Whose problem is this?", "kind": "opening", "reason": "x",
                  "verification_hint": "y", "id": "q-answered1", "asked_at": tie, "answer": "Forwarders",
                  "answered_at": tie}
    sessions = {
        LONG_ID: session(LONG_ID, tie, {"kind": "company", "slug": "invented-lattice-freight", "name": LATTICE},
                         ctx(LATTICE, "invented-lattice-freight", scores={"founder": 22}, verified={"founders": True}),
                         questions=[skipped_q, answered_q], covered=["problem"], skipped_families=["traction"],
                         ledger=[claim("cl-oldcontra1", "traction", "Traction: deck vs founder", "CONTRADICTION",
                                       source="evaluator", against=["a", "b"]),
                                 claim("cl-oldunknown", "market", "Not sure about the market", "UNKNOWN")]),
        MID_ID: session(MID_ID, "2026-10-05 10:00", {"kind": "external", "name": "Invented Past Co"},
                        ctx("Invented Past Co"), status="ended",
                        questions=[dict(answered_q, id="q-midanswer")],
                        ended={"on": "2026-10-05 11:00", "call_id": "", "answers": 1}),
        SHORT_ID: session(SHORT_ID, tie, {"kind": "external", "name": "Invented Tie Co"}, ctx("Invented Tie Co"),
                          ledger=[claim("cl-tieclaim01", "traction", "ARR of €1m with 9 paying customers",
                                        "DECK CLAIM", label="DECK CLAIM — UNVERIFIED")]),
    }
    return {"version": 1, "sessions": sessions}


def founder_calls_doc() -> dict[str, Any]:
    co = "fc-co-existinglattice1"
    return {"version": 1, "label": "Founder-reported — unverified",
            "companies": {co: company(co, LATTICE, linked_pipeline_slug="invented-lattice-freight", external=False)},
            "founders": {"fc-f-existingada0001": founder("fc-f-existingada0001", "Ada Inventa", co)},
            "calls": {}}


def corpus() -> dict[str, Any]:
    return {"evaluations.json": evaluations(),
            "real_data.json": {"week": "2026-W46", "_note": "invented corpus", "signals": signals()},
            "people.json": {"people": people()}, "radar_companies.json": radar_companies(),
            "founder_calls.json": founder_calls_doc()}


DECK = ("Invented Lattice Freight — seed deck\n"
        "- ARR of €1.2m with 18 paying customers across Europe.\n"
        "- We raised €2.5m seed and plan to raise again soon.\n"
        "- There is no competition in AI quoting for forwarders.\n"
        "• Team of 12 engineers, ex-Invented Corp founders. Six pilots running with large forwarders.\n"
        "Gross margin 70% on platform revenue.\n"
        "short\n"
        "Our pipeline is not 20 paying customers yet, but 3 signed contracts.\n"
        "We have 2 patents filed.")
URL = "https://invented.example/evidence"
TRIGGER = {"slug": "invented-lattice-freight", "kind": "fundraising", "date": "2026-11-01",
           "url": "https://invented.example/round", "fact": "Series A process opened", "confirm": True}
STEPS: list[dict[str, Any]] = [
    {"op": "read_all"},
    {"op": "start", "body": {"subject": {"kind": "company", "slug": "invented-lattice-freight", "founder": ""}}},
    {"op": "start", "at": "2026-11-12T10:05:00",
     "body": {"subject": {"kind": "external", "name": "Invented Nimbus Analytics", "founder": "Eve Outside"}}},
    {"op": "start", "at": "2026-11-12T10:06:00",
     "body": {"subject": {"name": "Invented Quarry Health", "founder": "Cy Nowhere", "person_id": "p-cy"}}},
    {"op": "start", "at": "2026-11-12T10:06:30", "body": {}},  # an empty subject; ties S2 on created
    {"op": "start", "body": {"subject": {"kind": "company", "slug": "invented-orbit-tools"}}},
    {"op": "deck", "at": "2026-11-12T10:10:00", "body": {"id": "@S0", "text": DECK}},
    {"op": "next", "body": {"id": "@S0"}},  # the open question: nothing changes
    {"op": "skip", "body": {"id": "@S0", "qid": "@QO0"}},
    {"op": "skip", "body": {"id": "@S0", "qid": "@Q0:0"}},  # skipped again: still unanswered, so accepted
    {"op": "skip", "body": {"id": "@S0", "qid": "q-nope"}},
    {"op": "answer", "at": "2026-11-12T10:15:00",
     "body": {"id": "@S0", "qid": "@QO0", "text": "We have 12 paying customers and ARR is €800k; we are raising a next round in 6 months."}},
    {"op": "skip", "body": {"id": "@S0", "qid": "@Q0:1"}},  # already answered
    {"op": "answer", "body": {"id": "@S0", "qid": "@QO0", "text": "Not sure, we haven't measured that."}},
    {"op": "next", "body": {"id": "@S0"}},
    {"op": "answer", "body": {"id": "@S0", "qid": "@Q0:1", "text": "Customers love it; 14 paying customers now and six pilots."}},
    {"op": "answer", "body": {"id": "@S0", "qid": "q-nope", "text": "x"}},
    {"op": "answer", "body": {"id": "@S0", "qid": "@QO0", "text": ""}},
    {"op": "answer", "body": {"id": "@S0", "qid": "@QO0", "text": "unknown"}},
    {"op": "answer", "body": {"id": "@S0", "qid": "@QO0", "text": "There is no competition, nobody else does this."}},
    {"op": "answer", "body": {"id": "@S0", "qid": "@QO0", "text": "We have a patent pending and 3 granted patents."}},
    {"op": "answer", "body": {"id": "@S0", "qid": "@QO0", "text": "I don't know yet."}},
    {"op": "answer", "body": {"id": "@S0", "qid": "@QO0", "text": "No idea."}},
    {"op": "evidence", "at": "2026-11-12T10:20:00",
     "body": {"id": "@S0", "claim_id": "@C0:ARR of €1.2m", "url": URL, "label": "Invoices", "note": "Checked"}},
    {"op": "evidence", "body": {"id": "@S0", "claim_id": "@C0:ARR of €1.2m", "url": URL + "/2", "label": "Bank"}},
    {"op": "evidence", "body": {"id": "@S0", "claim_id": "@C0:Gross margin", "url": URL, "kind": "public"}},
    {"op": "evidence", "body": {"id": "@S0", "claim_id": "@C0:Team of 12", "kind": "operator", "note": "Met them"}},
    {"op": "evidence", "body": {"id": "@S0", "claim_id": "@C0:Team of 12", "kind": "operator", "note": "Met them",
                                "confirm": True}},
    {"op": "evidence", "body": {"id": "@S0", "claim_id": "@C0:patents", "url": "https://www.linkedin.com/in/x",
                                "label": "LI"}},
    {"op": "evidence", "body": {"id": "@S0", "claim_id": "@C0:patents", "url": "https://www.google.com/search?q=x",
                                "label": "G"}},
    {"op": "evidence", "body": {"id": "@S0", "claim_id": "@C0:patents", "url": "", "label": "none"}},
    {"op": "evidence", "body": {"id": "@S0", "claim_id": "@C0:patents", "url": "ftp://invented.example"}},
    {"op": "evidence", "body": {"id": "@S0", "claim_id": "cl-nope", "url": URL, "label": "x"}},
    {"op": "resolve", "body": {"id": "@S0", "claim_id": "@X0:0", "note": "Checked the invoices"}},
    {"op": "resolve", "at": "2026-11-12T10:25:00", "body": {"id": "@S0", "claim_id": "@X0:0", "note": "Re-checked"}},
    {"op": "resolve", "body": {"id": "@S0", "claim_id": "cl-nope"}},
    {"op": "resolve", "body": {"id": "@S0", "claim_id": "@C0:Team of 12"}},
    {"op": "frobnicate", "body": {"id": "@S0"}},
    {"op": "deck", "body": {"id": "ev-nope", "text": "x"}},
    {"op": "frobnicate", "body": {"id": "ev-nope"}},
    {"op": "evaluation", "id": "@S0"},
    {"op": "evaluation", "id": "ev-nope"},
    {"op": "evaluation", "id": LONG_ID},  # GET next = the skipped question
    {"op": "imq_trigger", "body": dict(TRIGGER, slug="invented-nobody")},
    {"op": "imq_trigger", "body": dict(TRIGGER, confirm=False)},
    {"op": "imq_trigger", "body": dict(TRIGGER, kind="vibes")},
    {"op": "imq_trigger", "body": dict(TRIGGER, date="2026-12-01")},
    {"op": "imq_trigger", "body": dict(TRIGGER, date="2026-02-30")},
    {"op": "imq_trigger", "body": dict(TRIGGER, url="https://linkedin.com/company/x")},
    {"op": "imq_trigger", "body": dict(TRIGGER, fact="")},
    {"op": "imq_trigger", "body": TRIGGER},
    {"op": "end", "at": "2026-11-12T11:00:00", "body": {"id": "@S0", "call_type": "followup", "channel": "phone"}},
    {"op": "end", "body": {"id": "@S0"}},  # already ended: no second side effect
    {"op": "next", "body": {"id": "@S0"}},
    {"op": "skip", "body": {"id": "@S0", "qid": "@Q0:0"}},
    {"op": "answer", "body": {"id": "@S1", "qid": "@QO1", "text": "We sell to CFOs at invented manufacturers; budget sits with procurement."}},
    {"op": "end", "body": {"id": "@S1", "call_type": "bogus"}},
    {"op": "answer", "body": {"id": "@S2", "qid": "@QO2", "text": "We are raising within two months, runway is 9 months."}},
    {"op": "end", "body": {"id": "@S2"}},
    {"op": "end", "body": {"id": "@S3"}},  # external, no answer: no founder call
    {"op": "end", "body": {"id": "@S4", "channel": "in-person"}},  # linked, no answer: Conviction fields only
    {"op": "end", "body": {"id": "@S1"}},
    {"op": "deck", "body": {"id": "@S3", "text": "We raised €1m from invented angels."}},  # an ended session imports
    {"op": "end", "body": {"id": LONG_ID}},  # an imported session, linked, one answer
    {"op": "read_all", "at": LATER},
]
EMPTY_STEPS: list[dict[str, Any]] = [
    {"op": "read_all"},
    {"op": "next", "body": {"id": "ev-x"}},
    {"op": "imq_trigger", "body": {"slug": "x", "confirm": True}},
    {"op": "start", "body": {"subject": {"name": "Invented First Co", "founder": "Una First"}}},
    {"op": "answer", "body": {"id": "@S0", "qid": "@QO0", "text": "Five paying customers, €200k ARR."}},
    {"op": "end", "body": {"id": "@S0"}},
    {"op": "read_all"},
]
# fmt: on
SETS: dict[str, Any] = {
    "main": {"docs": corpus, "steps": STEPS},
    "empty": {"docs": dict, "steps": EMPTY_STEPS},
}


def _files(docs: dict[str, Any]) -> dict[str, bytes]:
    return {k: json.dumps(v, ensure_ascii=False, indent=2).encode("utf-8") for k, v in docs.items()}


def run_oracle(inp: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-evaluator-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir(parents=True)
        for rel, raw in files.items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        srcf, dst = Path(tmp) / "io" / "in.json", Path(tmp) / "io" / "out.json"
        srcf.parent.mkdir(parents=True, exist_ok=True)
        srcf.write_text(json.dumps(inp, ensure_ascii=False), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(data), "PZ_TESTING": "1", "PZ_CASE_PREP": "0",
               "PYTHONPATH": str(OLD_REPO / "backend" / "src")}  # fmt: skip
        env.pop("SUPABASE_DB_URL", None)
        run = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


# ------------------------------------------------------------------ the new side
def counter_hex() -> Callable[[], str]:
    """The oracle's ``uuid4`` counter: the n-th hex is ``f"{n:06x}" + "0" * 26``."""
    n = itertools.count(1)
    return lambda: f"{next(n):06x}" + "0" * 26


def resolve(value: Any, sessions: dict[str, Any], started: list[str]) -> Any:
    """The oracle's placeholders, the same rules (``scripts/oracle/evaluator_oracle.py``)."""
    import re

    if isinstance(value, dict):
        return {k: resolve(v, sessions, started) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, sessions, started) for v in value]
    if not isinstance(value, str) or not value.startswith("@"):
        return value
    m = re.fullmatch(r"@(S|QO|Q|C|X)(\d+)(?::(.*))?", value, re.S)
    if not m or int(m.group(2)) >= len(started):
        return "@missing"
    sid = started[int(m.group(2))]
    s = sessions.get(sid) or {}
    kind, arg = m.group(1), m.group(3)
    try:
        if kind == "S":
            return sid
        if kind == "Q":
            return s["questions"][int(arg or "0")]["id"]
        if kind == "QO":
            return next(q["id"] for q in s["questions"] if q.get("answer") is None and not q.get("skipped"))
        if kind == "C":
            return next(c["id"] for c in s["ledger"] if (arg or "") in c["text"])
        return [c for c in s["ledger"] if c["state"] == "CONTRADICTION"][int(arg or "0")]["id"]
    except (IndexError, KeyError, StopIteration, ValueError, TypeError):
        return "@missing"


def store_snapshot(doc: Any) -> dict[str, Any]:
    if doc is None:
        return {"body": None, "order": None}
    body = js(doc)
    sessions = body.get("sessions") if isinstance(body, dict) else None
    return {"body": body, "order": list(sessions.keys()) if isinstance(sessions, dict) else None}


def calls_snapshot(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict):
        return {"body": js(doc), "order": None}
    body = js(doc)
    order: dict[str, Any] = {"top": list(body)}
    for k in FC_OBJECTS:
        obj = body.get(k)
        if isinstance(obj, dict):
            order[k] = list(obj.keys())
            order[k + "_fields"] = [[i, list(r.keys())] for i, r in obj.items() if isinstance(r, dict)]
    return {"body": body, "order": order}


def _try(fn: Callable[[], tuple[int, Any]]) -> dict[str, Any]:
    try:
        code, body = fn()
    except Exception as exc:
        return {"raises": type(exc).__name__}
    return {"code": code, "body": js(body)}


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False)


@dataclass
class Store:
    """The new side's state between steps: the three documents the DB layer would hold, and the read inputs."""

    doc: Any
    conviction: list[Any]
    people: list[dict[str, Any]]
    radar_companies: Any
    founder_calls: Any
    new_hex: Callable[[], str] = field(default_factory=counter_hex)
    started: list[str] = field(default_factory=list)

    def sessions(self) -> dict[str, Any]:
        return routes.loaded(self.doc)["sessions"]  # type: ignore[no-any-return]

    def view(self) -> dict[str, Any]:
        return _try(lambda: (200, routes.workspace(self.doc)))

    def session(self, sid: Any, today: date) -> dict[str, Any]:
        def run() -> tuple[int, Any]:
            v = routes.session_view(self.doc, sid, conviction=self.conviction, people=self.people, today=today)
            return (404, {"error": routes.UNKNOWN_SESSION}) if v is None else (200, v)

        return _try(run)

    def write(self, op: str, body: dict[str, Any], today: date, now: datetime) -> tuple[dict[str, Any], list[str]]:
        before = (copy.deepcopy(self.doc), copy.deepcopy(self.conviction), copy.deepcopy(self.founder_calls))
        given = (self.doc, self.conviction, self.founder_calls)
        problems: list[str] = []
        try:
            if op == "imq_trigger":
                t = routes.imq_trigger(body, conviction=self.conviction, today=today, now=now)
                problems += self._inputs_kept(before, given)
                self._apply(t.conviction)
                return {"code": t.status, "body": js(t.body)}, problems
            o = routes.action(op, self.doc, body, conviction=self.conviction, people=self.people,
                              radar_companies=self.radar_companies, founder_calls=self.founder_calls, today=today,
                              now=now, new_hex=self.new_hex)  # fmt: skip
        except Exception as exc:
            return {"raises": type(exc).__name__}, problems
        answer = {"code": o.status, "body": js(o.body)}  # serialized before anything else can touch it
        problems += self._inputs_kept(before, given) + check_outcome(before[0], self.doc, o)
        if op == "start" and o.status == 200:
            self.started.append(o.body["id"])
        self.doc = o.doc
        if o.founder_calls is not None:
            self.founder_calls = o.founder_calls.doc
        self._apply(o.conviction)
        return answer, problems

    @staticmethod
    def _inputs_kept(before: tuple[Any, ...], given: tuple[Any, ...]) -> list[str]:
        names = ("evaluations", "conviction", "founder_calls")
        return [f"the input {n} was mutated" for n, a, b in zip(names, before, given, strict=True) if not _same(a, b)]

    def _apply(self, changes: tuple[Any, ...]) -> None:
        if changes:
            self.conviction = list(self.conviction)
            for ch in changes:
                self.conviction[ch.index] = ch.record


def check_outcome(before: Any, given: Any, o: routes.Outcome) -> list[str]:
    """``changed`` lists exactly the new or modified sessions, in document order; an outcome without changes returns
    the input object; the existing sessions keep their order (a new one is appended)."""
    problems = []
    base = routes.loaded(before)["sessions"]
    after = routes.loaded(o.doc)["sessions"]
    want = [i for i, s in after.items() if i not in base or not _same(base[i], s)]
    if o.changed != want:
        problems.append(f"changed {o.changed} != {want}")
    if not o.changed and o.doc is not given:
        problems.append("an outcome without changes did not return the input")
    if list(after)[: len(base)] != list(base):
        problems.append("the existing sessions were reordered")
    return problems


def new_side(docs: dict[str, Any], clock: str, steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """(the rows, the invariant problems)."""
    st = Store(doc=copy.deepcopy(docs.get("evaluations.json")),
               conviction=copy.deepcopy((docs.get("real_data.json") or {"week": "", "signals": []})["signals"]),
               people=(docs.get("people.json") or {"people": []})["people"],
               radar_companies=docs.get("radar_companies.json"),
               founder_calls=copy.deepcopy(docs.get("founder_calls.json")))  # fmt: skip
    signals_file = docs.get("real_data.json")
    wall = clock
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    for i, step in enumerate(steps):
        wall = step.get("at") or wall
        now = utc_instant(wall)
        today = berlin_today(now)
        op = step["op"]
        sessions = st.sessions()
        body = resolve(step.get("body") or {}, sessions, st.started)
        row: dict[str, Any] = {}
        if op == "evaluations":
            row["answer"] = st.view()
        elif op == "evaluation":
            row["answer"] = st.session(resolve(step.get("id"), sessions, st.started), today)
        elif op == "read_all":
            row["view"] = st.view()
            row["session"] = {s: st.session(s, today) for s in [*sessions, "ev-unknown"]}
        else:
            row["answer"], found = st.write(op, body, today, now)
            problems += [f"/steps[{i}]: {p}" for p in found]
            row["view"] = st.view()
            row["store"] = store_snapshot(st.doc)
            row["calls"] = calls_snapshot(st.founder_calls)
            row["signals"] = js(st.conviction) if signals_file is not None else None
        out.append(row)
    return out, problems


# ------------------------------------------------------------------ the golden (repeated values stored once)
# A recorded ``view`` / ``calls`` / ``signals`` equal to the last full one is ``{"same_as": step}``; a stored session
# equal to the same id's last full record is ``{"same_record": step}``. Equality is order-sensitive (the serialized
# JSON), so expanding restores every key order exactly.
def _key(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def compact(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last: dict[str, tuple[str, int]] = {}
    recs: dict[str, tuple[str, int]] = {}
    out = []
    for i, st in enumerate(steps):
        row = dict(st)
        for k in RECORDED:
            if k in st:
                j = _key(st[k])
                if k in last and last[k][0] == j:
                    row[k] = {"same_as": last[k][1]}
                else:
                    last[k] = (j, i)
        store = st.get("store") or {}
        sessions = (store.get("body") or {}).get("sessions") if isinstance(store.get("body"), dict) else None
        if isinstance(sessions, dict):
            packed: dict[str, Any] = {}
            for sid, s in sessions.items():
                j = _key(s)
                if sid in recs and recs[sid][0] == j:
                    packed[sid] = {"same_record": recs[sid][1]}
                else:
                    packed[sid] = s
                    recs[sid] = (j, i)
            row["store"] = {**store, "body": {**store["body"], "sessions": packed}}
        out.append(row)
    return out


def expand(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for st in steps:
        row = dict(st)
        for k in RECORDED:
            v = st.get(k)
            if isinstance(v, dict) and set(v) == {"same_as"}:
                row[k] = out[v["same_as"]][k]
        store = st.get("store") or {}
        sessions = (store.get("body") or {}).get("sessions") if isinstance(store.get("body"), dict) else None
        if isinstance(sessions, dict):
            full = {sid: (out[s["same_record"]]["store"]["body"]["sessions"][sid]
                          if isinstance(s, dict) and set(s) == {"same_record"} else s)
                    for sid, s in sessions.items()}  # fmt: skip
            row["store"] = {**store, "body": {**store["body"], "sessions": full}}
        out.append(row)
    return out


def compare_goldens(golden: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, s in golden["sets"].items():
        expected = expand(s["expected"])
        got, invariants = new_side(s["docs"], golden["clock"], s["steps"])
        problems += [f"/{name}{p}" for p in diff({"steps": js(expected)}, {"steps": js(got)})]
        problems += [f"/{name}{p}" for p in invariants]
        for i, (a, b) in enumerate(zip(expected, got, strict=False)):  # key order, explicitly (dict == ignores it)
            for k in ("store", "calls"):
                if k in a and a[k]["order"] != (b.get(k) or {}).get("order"):
                    problems.append(f"/{name}/steps[{i}]/{k}/order: the key order differs")
                if k in a and _key(a[k]["body"]) != _key((b.get(k) or {}).get("body")):
                    problems.append(f"/{name}/steps[{i}]/{k}/body: the serialized document differs")
            if "signals" in a and _key(a["signals"]) != _key(b.get("signals")):
                problems.append(f"/{name}/steps[{i}]/signals: the serialized records differ")
            if "answer" in a and _key(a["answer"]) != _key(b.get("answer")):
                problems.append(f"/{name}/steps[{i}]/answer: the serialized answer differs")
    return problems


def write_goldens() -> int:
    sets: dict[str, Any] = {}
    meta: dict[str, Any] = {}
    for name, spec in SETS.items():
        docs = spec["docs"]()
        oracle = run_oracle({"clock": CLOCK, "steps": spec["steps"]}, _files(docs))
        meta = oracle.pop("meta")
        sets[name] = {"docs": docs, "steps": spec["steps"], "ids_made": meta.pop("ids_made"),
                      "expected": compact(oracle["steps"])}  # fmt: skip
    golden = {"provenance": meta, "clock": CLOCK, "sets": sets}
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    # NOT sort_keys: the documents' insertion order is part of the input (and of what the oracle recorded)
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=None) + "\n", encoding="utf-8", newline="\n")
    problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
    print(json.dumps({"golden": str(GOLDEN), "bytes": GOLDEN.stat().st_size, "old": meta,
                      "summary": summary(golden)}, indent=1, ensure_ascii=False))  # fmt: skip
    for p in problems[:60]:
        print("  DIFF", p)
    print("EVALUATOR GOLDENS MATCH" if not problems else f"EVALUATOR GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, s in golden["sets"].items():
        steps = expand(s["expected"])
        answers = []
        for st in steps:
            a = st.get("answer")
            if a is not None:
                b = a.get("body") or {}
                answers.append(
                    a.get("raises") or (b.get("error") if isinstance(b, dict) and b.get("error") else a["code"])
                )
        out[name] = {"steps": len(steps), "answers": answers, "ids_made": s["ids_made"]}
    return out


REAL_CLOCK = "2026-11-12T09:00:00"
REAL_ANSWER = "We have 12 paying customers and ARR is €800k; we are raising a next round in 6 months."


def real_steps(snapshot_signals: list[Any], sessions: dict[str, Any]) -> list[dict[str, Any]]:
    """A full read, a session on the first real Conviction company (an invented deck, an answer, public evidence, a
    resolve, refusals), the why-now trigger (a refusal and a success), the end, a repeat end of an imported ended
    session, and a full read at a later day."""
    from projectzero.dealflow.ranking.names import slug as radar_slug

    first = next((s for s in snapshot_signals if isinstance(s, dict) and s.get("company")), None)
    slug = radar_slug(first["company"]) if first else "invented-nobody"
    ended = next((k for k, v in sessions.items() if isinstance(v, dict) and v.get("status") == "ended"), "ev-unknown")
    trigger = dict(TRIGGER, slug=slug)
    return [
        {"op": "read_all"},
        {"op": "start", "body": {"subject": {"kind": "company", "slug": slug}}},
        {"op": "deck", "at": "2026-11-12T09:05:00", "body": {"id": "@S0", "text": DECK}},
        {"op": "next", "body": {"id": "@S0"}},
        {"op": "skip", "body": {"id": "@S0", "qid": "q-nope"}},
        {"op": "answer", "at": "2026-11-12T09:10:00", "body": {"id": "@S0", "qid": "@QO0", "text": REAL_ANSWER}},
        {
            "op": "evidence",
            "body": {"id": "@S0", "claim_id": "@C0:ARR of €1.2m", "url": URL, "label": "Invoices", "note": "Checked"},
        },
        {"op": "resolve", "body": {"id": "@S0", "claim_id": "@X0:0", "note": "Checked the invoices"}},
        {"op": "imq_trigger", "body": dict(trigger, confirm=False)},
        {"op": "imq_trigger", "body": trigger},
        {"op": "end", "at": "2026-11-12T09:30:00", "body": {"id": "@S0", "call_type": "followup", "channel": "phone"}},
        {"op": "end", "body": {"id": ended}},
        {"op": "read_all", "at": LATER},
    ]


def _no_fields(snapshot: dict[str, Any]) -> dict[str, Any]:
    order = snapshot.get("order")
    if isinstance(order, dict):
        order = {k: v for k, v in order.items() if not k.endswith("_fields")}
    return {**snapshot, "order": order}


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    """The real snapshot imported by the production importer into a throw-away schema, through the API routes, against
    the OLD routes over a byte-exact copy, with the same clock and id counter. Every answer, the workspace, every
    session view, the stored evaluations (body + session order), the stored founder calls (body + key order) and the
    stored Conviction records are compared after each step; aggregates only are printed."""
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.conviction.store import ConvictionStore, record_of
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.evaluator.store import EvaluationsStore
    from projectzero.founder_calls.store import FounderCallsStore
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot_ = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot_.files()}
    evals = snapshot_.json("evaluations.json", {}) or {}
    signals_doc = snapshot_.json("real_data.json", {}) or {}
    steps = real_steps(signals_doc.get("signals") or [], evals.get("sessions") or {})
    old = run_oracle({"clock": REAL_CLOCK, "steps": steps}, files)
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    report: dict[str, Any] = {
        "sessions": len(evals.get("sessions") or {}),
        "signals": len(signals_doc.get("signals") or []),
    }
    problems: list[str] = []
    admin = connect(settings.db_url, autocommit=True)
    clock = [utc_instant(REAL_CLOCK)]
    started: list[str] = []
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot_), schema=schema, conn=conn)
            assert applied.get("applied"), applied
        finally:
            conn.close()
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: clock[0]
        app.state.new_hex = counter_hex()
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:

            def ans(r: Any) -> dict[str, Any]:
                return {"code": r.status_code, "body": r.json()}

            def stored() -> tuple[Any, Any, Any]:
                with transaction(settings.db_url) as c:
                    return (
                        EvaluationsStore(c, schema).load(),
                        FounderCallsStore(c, schema).load(),
                        [record_of(r) for r in ConvictionStore(c, schema).entry_rows()],
                    )

            def check(i: int, key: str, exp: Any, got: Any) -> None:
                problems.extend(f"/step{i}/{key}{p.split(':')[0]}" for p in diff(js(exp), js(got)))

            for i, (step, exp) in enumerate(zip(steps, old["steps"], strict=True)):
                if step.get("at"):
                    clock[0] = utc_instant(step["at"])
                sessions = routes.loaded(stored()[0])["sessions"]
                body = resolve(step.get("body") or {}, sessions, started)
                if step["op"] == "read_all":
                    check(i, "view", exp["view"], ans(client.get("/api/evaluator/sessions")))
                    ids = [*sessions, "ev-unknown"]
                    got = {s: ans(client.get("/api/evaluator/session", params={"id": s})) for s in ids}
                    check(i, "session", exp["session"], got)
                    continue
                op = step["op"]
                path = "/api/conviction/imq_trigger" if op == "imq_trigger" else f"/api/evaluator/{op}"
                answer = ans(client.post(path, json=body))
                if op == "start" and answer["code"] == 200:
                    started.append(answer["body"]["id"])
                check(i, "answer", exp["answer"], answer)
                check(i, "view", exp["view"], ans(client.get("/api/evaluator/sessions")))
                doc, calls, records = stored()
                check(i, "store", exp["store"], store_snapshot(doc))
                # JSONB keeps no field order inside a record (review 023): the ids and their positions are compared
                check(i, "calls", _no_fields(exp["calls"]), _no_fields(calls_snapshot(calls)))
                check(i, "signals", exp["signals"], records)
            report["steps"] = len(steps)
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2, default=str))
    for p in problems[:60]:
        print("  DIFF", p)
    print("EVALUATOR PARITY PASSED" if not problems else "EVALUATOR PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["real"]:
        return real()
    if argv[1:] == ["goldens"]:
        return write_goldens()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
