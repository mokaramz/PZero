"""Founder Calls parity: the pure port against the OLD code as oracle, with a FIXED clock (review 023).

    python -m projectzero.ops.parity_founder_calls goldens   # (re)generates golden_v1/oracle_founder_calls.json

The oracle (``scripts/oracle/founder_calls_oracle.py``) runs the old route functions of ``api/routers/calls.py`` over a
scratch data folder: ``GET calls``, every call view, memo and briefing, and a write script (``call_save``,
``call_followup``, ``call_link``) with the answer, the whole ``GET calls`` body and the stored file (its parsed body
and its key ORDER) after each step. The old random ids are a counter on both sides (``prefix + f"{n:012x}"``). The new
side is the PURE port (``founder_calls.routes``): each write's ``Outcome.doc`` is the next step's document.

The synthetic data folders hold INVENTED names only. ``main``: every due state (overdue / due / upcoming / scheduled /
open / done / none, an unparseable due), external / pipeline / radar companies, aliases, merged companies and founders
(a chain, a cycle, a founder pointing at a merged company), the Active Evaluator filter (an empty ended session, an
answered one, an unknown one), two calls TIED on date / time / created, two founders and two companies tied on the
sort name, and a document whose companies / founders / calls INSERTION order differs from the JSONB order (long ids
first, a short id last). Its write script: a new call creating its company and founder, an edit, an unchanged save,
each coercion, missing fields keeping their values, an unknown id creating that call, two refused saves (one burns an
id, as the old code did), the follow-up done / reopened / unchanged / unknown, founder links (a merge into the
person's record, an unknown person, a person without a name, an unknown founder, a duplicate person id), company links
(a pipeline slug, an unknown slug, a merge by slug and one by radar key, an unknown company, an idempotent repeat),
neither id, saves through merged ids, the briefing refusals, and a final read at a later day. ``empty``: no file at
all; ``partial``: a file missing two of its objects and no other documents. Identical ``GET calls`` keys are stored
once (``{"same_as": index}``). Exit 1 on any difference.

Declared (review 036a): a briefing whose ``confirm`` is supplied but is not a JSON boolean (the script's ``1``) is a
400 ``{error: "confirm must be true or false"}`` with no briefing generated; the new side checks that answer, then
replays the step with the old truthiness (``bool(confirm)``) and compares it with the recorded one.
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
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from projectzero.core.body import CONFIRM_REFUSAL
from projectzero.core.paths import REPO_ROOT
from projectzero.events.when import BERLIN
from projectzero.founder_calls import core, routes
from projectzero.network.view import berlin_today
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "founder_calls_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_founder_calls.json"
CLOCK = "2026-11-12T10:00:00"
LATER = "2026-11-20T08:00:00"
OBJECTS = ("companies", "founders", "calls")


def utc_instant(berlin_wall_clock: str) -> datetime:
    return datetime.fromisoformat(berlin_wall_clock).replace(tzinfo=BERLIN).astimezone(UTC)


# ------------------------------------------------------------------ the synthetic data folder (invented names only)
# fmt: off
T0 = "2026-10-20 09:00:00"


def company(cid: str, name: str, **kw: Any) -> dict[str, Any]:
    return {"id": cid, "name": name, "linked_pipeline_slug": "", "linked_radar_key": "", "external": True,
            "aliases": [], "created": T0, "updated": T0} | kw


def founder(fid: str, name: str, cid: str, **kw: Any) -> dict[str, Any]:
    return {"id": fid, "name": name, "company_id": cid, "linked_person_id": "", "external": True, "aliases": [],
            "created": T0, "updated": T0} | kw


def asm(**kw: str) -> dict[str, str]:
    return {"why_exceptional": "", "founder_market_insight": "", "speed_resourcefulness": "",
            "product_differentiation": "", "customer_pull": "", "venture_scale": "", "project_a_relevance": "",
            "red_flags": "", "verify_facts": "", "recommendation": "", "confidence": "", "next_action": ""} | kw


def call(cid: str, fid: str, coid: str, day: str, tm: str, **kw: Any) -> dict[str, Any]:
    created = kw.pop("created", f"{day} 09:30:00")
    return {"id": cid, "created": created, "founder_id": fid, "company_id": coid, "call_type": "first", "date": day,
            "time": tm, "channel": "video", "discovery_origin": "Invented meetup", "intro_path": "", "objective": "",
            "observations": "", "participants": ["Mohamed"],
            "answers": core._normalize_answers(kw.get("call_type", "first"), kw.pop("raw_answers", {})),
            "claims": [], "risks": [], "open_questions": [],
            "next_action": {"text": "", "owner": "Mohamed", "due": "", "done": False}, "assessment": asm(),
            "label": "Founder-reported — unverified", "updated": kw.pop("updated", created)} | kw


def na(text: str, due: str = "", done: bool = False, **kw: Any) -> dict[str, Any]:
    return {"text": text, "owner": "Mohamed", "due": due, "done": done, **kw}


CO1, CO2, CO3, CO4, CO5, CO9 = ("fc-co-longinventedaaa01", "fc-co-pipelinelinked02", "fc-co-radarlinkedco003",
                                "fc-co-mergedawayco0004", "fc-co-tiedname0000005", "c9")
F1, F2, F3, F4, F5 = ("fc-f-longfounderaaaa01", "fc-f-mergedfounder0002", "fc-f-personlinked00003",
                      "fc-f-orphan0000000004", "fc-f-pointsmerged00005")
F6A, F6B, F7, F8, F9 = ("fc-f-tiedname00000006", "fc-f-tiedname00000007", "f7", "fc-f-legacynoaliases08",
                        "fc-f-nocalls000000009")


def main_doc() -> dict[str, Any]:
    companies = {
        CO1: company(CO1, "Invented Quill Robotics", aliases=["Quill"]),
        CO2: company(CO2, "Invented Harbor Grid", linked_pipeline_slug="invented-harbor-grid", external=False),
        CO3: company(CO3, "invented loom labs", linked_radar_key="radar:loom", external=False),
        CO4: company(CO4, "Quill Robotics Old", merged_into=CO1),
        CO5: company(CO5, "Invented quill robotics"),  # ties CO1 on the sort name; name-matching finds CO1 first
        "fc-co-cycleaaaa000006": company("fc-co-cycleaaaa000006", "Cycle A", merged_into="fc-co-cyclebbbb000007"),
        "fc-co-cyclebbbb000007": company("fc-co-cyclebbbb000007", "Cycle B", merged_into="fc-co-cycleaaaa000006"),
        CO9: company(CO9, "Aardvark Invented"),  # the short id last
    }
    founders = {
        F1: founder(F1, "Ada Inventa", CO1, aliases=["A. Inventa"]),
        F2: founder(F2, "Ada I.", CO1, merged_into=F1),
        F3: founder(F3, "Bo Fictiv", CO2, linked_person_id="p-bo", external=False),
        F4: founder(F4, "Cy Nowhere", ""),  # an orphan
        F5: founder(F5, "Di Hidden", CO4),  # points at a merged company: neither listed nor an orphan
        F6A: founder(F6A, "eve Loom", CO3),
        F6B: founder(F6B, "Eve loom", CO3),  # ties F6A on the sort name
        "fc-f-cycleaaaa0000010": founder("fc-f-cycleaaaa0000010", "Cyc A", CO3, merged_into="fc-f-cyclebbbb0000011"),
        "fc-f-cyclebbbb0000011": founder("fc-f-cyclebbbb0000011", "Cyc B", CO3, merged_into="fc-f-cycleaaaa0000010"),
        F8: {"id": F8, "name": "Gus Legacy", "company_id": CO5, "linked_person_id": "", "external": True,
             "created": T0},  # a legacy record: no aliases, no updated
        F9: founder(F9, "Hal Silent", CO3),  # no calls
        F7: founder(F7, "Fay Shortid", CO9),  # the short id last
    }
    full = {"why": "Robots for labs.", "who": {"a": "Lab managers", "followups": {"0": "Pipetting got cheap"}},
            "built": {"a": "", "unknown": True}, "pull": {"a": "Two pilots", "unknown": True}}
    prep = {"pitch": "Robotic looms", "founder_case": {"a": "Built two looms", "followups": {"0": "Ex-Invented Corp"}},
            "fit": "Industrial AI", "round": "1.5M pre-seed", "permission": "yes, explicitly"}
    calls = {
        "fc-call-longcallaaaaa01": call("fc-call-longcallaaaaa01", F1, CO1, "2026-11-01", "10:00", raw_answers=full,
                                        objective="First look.", participants=["Mohamed", "Ada Inventa"],
                                        claims=[{"text": "ARR 200k", "label": "Founder-reported — unverified"}],
                                        risks=["hardware margins"], open_questions=["Who pays?"],
                                        next_action=na("Send the deck", "2026-11-05"),
                                        assessment=asm(why_exceptional="Ships weekly", recommendation="Follow up",
                                                       confidence="Medium")),
        "fc-call-tiedsecond0002": call("fc-call-tiedsecond0002", F3, CO2, "2026-11-03", "09:00",
                                       next_action=na("Ask for metrics")),
        "fc-call-tiedfirst00003": call("fc-call-tiedfirst00003", F3, CO2, "2026-11-03", "09:00",
                                       next_action=na("Ask for references")),  # tied with the call before
        "fc-call-merged-founder4": call("fc-call-merged-founder4", F2, CO4, "2026-11-08", "",
                                        next_action=na("Check the patent", "2026-11-12", owner="")),
        "fc-call-upcoming000005": call("fc-call-upcoming000005", F6A, CO3, "2026-11-09", "16:30",
                                       call_type="intro_prep", raw_answers=prep, channel="in-person",
                                       claims=[{"text": "Signed LOI with an invented mill", "label": "x"}],
                                       next_action=na("Intro to Omar", "2026-11-19", owner="Omar"),
                                       assessment=asm(red_flags="none seen", recommendation="Consider for Omar",
                                                      confidence="High", next_action="Write the briefing")),
        "fc-call-scheduled00006": call("fc-call-scheduled00006", F6B, CO3, "2026-11-10", "11:00",
                                       next_action=na("Quarterly check-in", "2026-12-30")),
        "fc-call-done0000000007": call("fc-call-done0000000007", F7, CO9, "2026-10-01", "08:00",
                                       next_action=na("Send notes", "2026-10-02", True, done_on="2026-10-02")),
        "fc-call-evaluatorempty8": call("fc-call-evaluatorempty8", F1, CO1, "2026-11-11", "",
                                        objective="Active Evaluator session ev-empty",
                                        next_action=na("Prepare questions", "2026-11-01")),
        "fc-call-evaluatoranswr9": call("fc-call-evaluatoranswr9", F1, CO1, "2026-11-11", "",
                                        objective="Active Evaluator session ev-answered",
                                        next_action=na("Review answers")),
        "fc-call-evaluatorunkn10": call("fc-call-evaluatorunkn10", F6B, CO3, "2026-11-11", "",
                                        objective="Active Evaluator session ev-unknown",
                                        next_action=na("", "2026-11-13")),
        "fc-call-baddue00000011": call("fc-call-baddue00000011", F6A, CO3, "2026-11-04", "",
                                       next_action=na("Odd date", "2026-13-45")),
        "fc-call-nonextaction12": {k: v for k, v in call("fc-call-nonextaction12", F7, CO9, "2026-09-01",
                                                         "").items() if k != "next_action"},
        "fc-call-followuptype13": call("fc-call-followuptype13", F8, CO5, "2026-11-02", "13:00", call_type="followup",
                                       raw_answers={"metrics": {"a": "MRR 10k", "followups": {"0": "burn 50k",
                                                                                              "2": "weekly"}}},
                                       channel="phone"),
        "fc-call-ghostfounder14": call("fc-call-ghostfounder14", "fc-f-ghost", "fc-co-ghost", "2026-11-05", "",
                                       next_action=na("", "")),
        "fc-call-cyclefounder15": call("fc-call-cyclefounder15", "fc-f-cycleaaaa0000010", "fc-co-cycleaaaa000006",
                                       "2026-11-06", ""),
        "k1": call("k1", F4, "", "2026-11-07", "", call_type="weird"),  # the short id last; an unknown call type
    }
    return {"version": 1, "label": "Founder-reported — unverified", "companies": companies, "founders": founders,
            "calls": calls}


def people() -> list[Any]:
    return [
        {"id": "p-bo", "name": "Bo Fictiv", "company": "Invented Harbor Grid", "role": "CEO",
         "last_interaction": "2026-11-01"},
        {"id": "p-ada", "name": "Ada Inventa-Smith", "company": "Invented Quill Robotics", "role": "CTO",
         "next_action": "call", "next_action_date": "2026-11-01"},
        {"id": "p-noname", "company": "Invented Nameless"},
        {"id": "p-eve", "name": "Eve Loom"},
        {"name": "No Id Person"},
        {"id": "p-dup", "name": "Dup One", "last_interaction": "2026-10-01"},
        {"id": "p-dup", "name": "Dup Two", "next_action": "x", "next_action_date": "2026-11-02"},  # due: listed first
        "not a record",
    ]


def signals() -> list[Any]:
    return [
        {"company": "Invented Harbor Grid GmbH", "founders": [{"name": "Bo Fictiv"}, "string founder", {"role": "x"}]},
        {"company": "Invented Quill Robotics", "founders": None},
        {"company": "Invented Löom Labs AG"},
        {"company": ""},
        {"company": None, "founders": [{"name": "Nobody"}]},
        "not a record",
        {"company": "Invented Brand New Co", "founders": [{"name": "Hal New"}]},
    ]


def evaluations() -> dict[str, Any]:
    return {"sessions": {"ev-empty": {"ended": {"answers": {}}}, "ev-answered": {"ended": {"answers": {"q1": "yes"}}},
                         "ev-open": {"started": "2026-11-10"}}}


def corpus() -> dict[str, Any]:
    return {"founder_calls.json": main_doc(), "people.json": {"people": people()},
            "real_data.json": {"week": "2026-W46", "signals": signals()}, "evaluations.json": evaluations()}


NEW_CALL = "fc-call-000000000003"
STEPS: list[dict[str, Any]] = [
    {"op": "read_all"},
    {"op": "save", "body": {"company": "Invented Novel Optics", "founder": "Ivy Newman", "date": "2026-11-12",
                            "time": " 14:00 ", "channel": "video", "objective": "First look",
                            "participants": "Mohamed; Ivy Newman\nOmar;;", "claims": "ARR 1M;\n20 pilots",
                            "answers": {"why": "Because now.", "who": {"a": "", "followups": {"0": "Labs", "1": ""}},
                                        "built": {"a": "Demo", "unknown": True}, "pull": {"a": " ", "followups": {}}},
                            "risks": ["  hardware ", "", 7], "open_questions": "Pricing?",
                            "next_action": {"text": "Send data room", "due": "2026-11-14T09:00", "owner": ""},
                            "assessment": {"why_exceptional": "Fast", "recommendation": "Follow up",
                                           "confidence": "Very high"}}},
    {"op": "save", "at": "2026-11-12T11:00:00",
     "body": {"id": NEW_CALL, "observations": "Sharp.", "channel": "carrier pigeon", "call_type": "followup",
              "next_action": "Call back"}},
    {"op": "save", "at": "2026-11-12T12:00:00",
     "body": {"id": NEW_CALL, "observations": "Sharp.", "channel": "carrier pigeon", "call_type": "followup",
              "next_action": "Call back"}},  # unchanged: changed false, nothing written
    {"op": "save", "body": {"id": NEW_CALL, "assessment": {"confidence": "High", "red_flags": None},
                            "call_type": "nonsense"}},  # missing fields keep their values
    {"op": "save", "body": {"id": "fc-call-longcallaaaaa01", "date": None, "time": 930, "objective": None,
                            "next_action": {"text": " Follow ", "due": None, "done": 1}, "claims": None,
                            "participants": None, "answers": "not a dict", "assessment": "not a dict"}},
    {"op": "save", "body": {"id": "fc-call-custom-id", "company": "invented  quill   robotics!",
                            "founder": "ADA INVENTA", "person_id": "p-ada", "next_action": {"done": True}}},
    {"op": "save", "body": {"company": "Invented Harbor Grid", "pipeline_slug": "invented-harbor-grid",
                            "name": "Bo Fictiv", "call_type": "intro_prep", "answers": {"permission": "yes"},
                            "date": "2026-11-12", "time": "09:00"}},
    {"op": "save", "body": {"company": "Aardvark Invented", "pipeline_slug": "aardvark-invented",
                            "founder": "New Person Q", "radar_key": "radar:aardvark"}},
    {"op": "save", "body": {"company": "", "founder": "Nobody"}},  # refused, no id made
    {"op": "save", "body": {"company": "Invented Lonely Co"}},  # refused after its company id was made
    {"op": "save", "body": {"company": "Invented Zeta", "founder": "Zed Person", "person_id": "p-eve",
                            "channel": "phone"}},
    {"op": "followup", "body": {"id": "fc-call-tiedsecond0002"}},
    {"op": "followup", "at": "2026-11-13T09:00:00", "body": {"id": "fc-call-tiedsecond0002", "done": False}},
    {"op": "followup", "body": {"id": "fc-call-nonextaction12", "done": False}},  # unchanged, default shown
    {"op": "followup", "body": {"id": "nope"}},
    {"op": "followup", "body": {"id": "fc-call-nonextaction12", "done": True}},
    {"op": "link", "body": {"founder_id": F4, "person_id": "p-bo", "company_id": CO4}},  # merges into Bo
    {"op": "link", "body": {"founder_id": F1, "person_id": "p-ghost"}},
    {"op": "link", "body": {"founder_id": F1, "person_id": "p-noname"}},
    {"op": "link", "body": {"founder_id": "fc-f-nobody"}},
    {"op": "link", "body": {"founder_id": F2, "person_id": "p-dup"}},  # the merged id resolves; "Dup Two"
    {"op": "link", "body": {"founder_id": F7, "company_id": CO3}},
    {"op": "link", "body": {"company_id": CO1, "pipeline_slug": "invented-quill-robotics"}},
    {"op": "link", "body": {"company_id": CO1, "pipeline_slug": "invented-quill-robotics"}},  # idempotent
    {"op": "link", "body": {"company_id": CO1, "pipeline_slug": "no-such-company"}},
    {"op": "link", "body": {"company_id": CO5, "pipeline_slug": "invented-harbor-grid"}},  # merge by slug
    {"op": "link", "body": {"company_id": CO9, "radar_key": "radar:loom"}},  # merge by radar key
    {"op": "link", "body": {"company_id": "fc-co-nope"}},
    {"op": "link", "body": {}},
    {"op": "link", "body": {"person_id": "p-bo", "pipeline_slug": "invented-harbor-grid"}},
    {"op": "save", "body": {"id": "k1", "objective": "Follow the merge"}},
    {"op": "save", "body": {"company_id": CO5, "founder_id": F4, "date": "2026-11-11"}},  # merged ids resolve
    {"op": "briefing", "body": {"founder_id": F1}},
    {"op": "briefing", "body": {"founder_id": F9, "confirm": True}},
    {"op": "briefing", "body": {"founder_id": F2, "confirm": 1}},
    {"op": "call", "id": "fc-call-custom-id"},
    {"op": "memo", "id": "nope"},
    {"op": "read_all", "at": LATER},
]
EMPTY_STEPS: list[dict[str, Any]] = [
    {"op": "read_all"},
    {"op": "followup", "body": {"id": "fc-call-x"}},
    {"op": "save", "body": {"company": "Invented First Co", "founder": "Una First"}},
    {"op": "read_all"},
]
PARTIAL_STEPS: list[dict[str, Any]] = [
    {"op": "calls"},
    {"op": "link", "body": {"founder_id": "fc-f-x", "person_id": "p-1"}},
    {"op": "save", "body": {"company": "Invented Partial Co", "founder": "Pia Partial", "radar_key": "radar:p"}},
    {"op": "read_all"},
]


def partial() -> dict[str, Any]:
    return {"founder_calls.json": {"version": 1, "calls": {}}}


SETS: dict[str, Any] = {
    "main": {"docs": corpus, "steps": STEPS},
    "empty": {"docs": dict, "steps": EMPTY_STEPS},
    "partial": {"docs": partial, "steps": PARTIAL_STEPS},
}
# fmt: on


# ------------------------------------------------------------------ the oracle
def _files(docs: dict[str, Any]) -> dict[str, bytes]:
    return {k: json.dumps(v, ensure_ascii=False, indent=1).encode("utf-8") for k, v in docs.items()}


def run_oracle(inp: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-founder-calls-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        for rel, raw in files.items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        srcf.write_text(json.dumps(inp), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(data), "PZ_TESTING": "1", "PZ_CASE_PREP": "0",
               "PYTHONPATH": str(OLD_REPO / "backend" / "src")}  # fmt: skip
        env.pop("SUPABASE_DB_URL", None)
        run = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


# ------------------------------------------------------------------ the new side
def counter_ids() -> Callable[[str], str]:
    """The oracle's id counter: the n-th id made is ``prefix + f"{n:012x}"`` (the old ``uuid4().hex[:12]``)."""
    n = itertools.count(1)
    return lambda prefix: f"{prefix}{next(n):012x}"


def snapshot(doc: Any) -> dict[str, Any]:
    """The stored document and its key order, as the oracle records the file (``None`` when never written)."""
    if doc is None:
        return {"body": None, "order": None}
    body = js(doc)
    order: dict[str, Any] = {"top": list(body)}
    for k in OBJECTS:
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


def _found(v: dict[str, Any] | None) -> tuple[int, Any]:
    return (404, {"error": routes.UNKNOWN_CALL}) if v is None else (200, v)


@dataclass
class Store:
    """The new side's state between steps: the document (``Outcome.doc`` of the last write) and the read inputs."""

    doc: Any
    people: Any
    signals: Any
    evaluations: Any
    new_id: Callable[[str], str] = field(default_factory=counter_ids)

    def view(self, today: date) -> dict[str, Any]:
        return _try(lambda: (200, routes.workspace(self.doc, people=self.people, pipeline=self.signals,
                                                   evaluations=self.evaluations, today=today)))  # fmt: skip

    def call(self, call_id: Any, today: date) -> dict[str, Any]:
        return _try(lambda: _found(routes.call_view(self.doc, call_id, today=today)))

    def memo(self, call_id: Any, today: date) -> dict[str, Any]:
        return _try(lambda: _found(routes.memo(self.doc, call_id, today=today)))

    def briefing(self, body: dict[str, Any], today: date) -> dict[str, Any]:
        return _try(lambda: routes.briefing(self.doc, body, today=today))

    def write(self, op: str, body: dict[str, Any], today: date, now: datetime) -> tuple[dict[str, Any], list[str]]:
        before = copy.deepcopy(self.doc)
        try:
            if op == "save":
                o = routes.save(self.doc, body, today=today, now=now, new_id=self.new_id)
            elif op == "followup":
                o = routes.followup(self.doc, body, today=today, now=now)
            else:
                o = routes.link(self.doc, body, people=self.people, pipeline=self.signals, today=today, now=now)
        except Exception as exc:
            return {"raises": type(exc).__name__}, []
        problems = check_outcome(before, self.doc, o)
        self.doc = o.doc
        return {"code": o.status, "body": js(o.body)}, problems


def new_side(docs: dict[str, Any], clock: str, steps: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """(the rows, the invariant problems: an input document mutated, or a ``changed`` list that is wrong)."""
    st = Store(doc=copy.deepcopy(docs.get("founder_calls.json")),
               people=(docs.get("people.json") or {"people": []}).get("people"),
               signals=(docs.get("real_data.json") or {"week": "", "signals": []})["signals"],
               evaluations=docs.get("evaluations.json") or {})  # fmt: skip
    wall = clock
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    for i, step in enumerate(steps):
        wall = step.get("at") or wall
        now = utc_instant(wall)
        today = berlin_today(now)
        op = step["op"]
        row: dict[str, Any] = {}
        if op == "calls":
            row["answer"] = st.view(today)
        elif op == "call":
            row["answer"] = st.call(step["id"], today)
        elif op == "memo":
            row["answer"] = st.memo(step["id"], today)
        elif op == "briefing":
            body = step["body"]
            if "confirm" in body and not isinstance(body["confirm"], bool):  # declared (review 036a), see the docstring
                strict = st.briefing(body, today)
                if strict != {"code": 400, "body": {"error": CONFIRM_REFUSAL}}:
                    problems.append(f"/steps[{i}]/briefing: confirm {body['confirm']!r} answered {strict}")
                body = {**body, "confirm": bool(body["confirm"])}
            row["answer"] = st.briefing(body, today)
        elif op == "read_all":
            d = core.loaded(st.doc)
            row["view"] = st.view(today)
            row["call"] = {c: st.call(c, today) for c in [*d["calls"], "fc-call-unknown"]}
            row["memo"] = {c: st.memo(c, today) for c in [*d["calls"], "fc-call-unknown"]}
            row["briefing"] = {f: st.briefing({"founder_id": f, "confirm": True}, today)
                               for f in [*d["founders"], "fc-f-unknown"]}  # fmt: skip
        else:
            row["answer"], found = st.write(op, step["body"], today, now)
            problems += [f"/steps[{i}]: {p}" for p in found]
            row["view"] = st.view(today)
            row["doc"] = snapshot(st.doc)
        out.append(row)
    return out, problems


def check_outcome(before: Any, given: Any, o: routes.Outcome) -> list[str]:
    """The input is never mutated; ``changed`` lists exactly the new or modified records, in document order; an
    outcome without changes returns the input object."""
    problems = []
    if json.dumps(before) != json.dumps(given):
        problems.append("the input document was mutated")
    base = core.loaded(given)
    after = core.loaded(o.doc)
    want = {k: [i for i, r in after[k].items() if i not in base[k] or js(base[k][i]) != js(r)] for k in OBJECTS}
    if o.changed != want:
        problems.append(f"changed {o.changed} != {want}")
    if not any(o.changed.values()) and o.doc is not given:
        problems.append("an outcome without changes did not return the input")
    for k in OBJECTS:  # appended, never reordered
        if list(after[k])[: len(base[k])] != list(base[k]):
            problems.append(f"{k}: the existing records were reordered")
    return problems


# ------------------------------------------------------------------ the golden (repeated values stored once)
# A ``GET calls`` key equal to the same key of an earlier view is ``{"same_as": j}``; a list element (a company, a call
# view, ...) equal to an element of an earlier view's same key is ``{"same_item": [j, index]}``; a stored record equal
# to the same id's record in an earlier stored document is ``{"same_record": j}``. Equality is order-sensitive (the
# serialized JSON), so expanding restores every key order exactly.
def _key(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def compact(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    whole: dict[tuple[str, str], int] = {}
    items: dict[tuple[str, str], list[int]] = {}
    records: dict[tuple[str, str, str], int] = {}
    views = docs = 0
    out = []
    for st in steps:
        row = dict(st)
        body = (st.get("view") or {}).get("body")
        if isinstance(body, dict):
            packed: dict[str, Any] = {}
            for k, v in body.items():
                if (k, _key(v)) in whole:
                    packed[k] = {"same_as": whole[(k, _key(v))]}
                elif isinstance(v, list):
                    packed[k] = [{"same_item": items[(k, _key(e))]} if (k, _key(e)) in items else e for e in v]
                else:
                    packed[k] = v
                whole.setdefault((k, _key(v)), views)
                for idx, e in enumerate(v if isinstance(v, list) else []):
                    items.setdefault((k, _key(e)), [views, idx])
            views += 1
            row["view"] = {**st["view"], "body": packed}
        doc = (st.get("doc") or {}).get("body")
        if isinstance(doc, dict):
            pdoc: dict[str, Any] = {}
            for k, v in doc.items():
                if k in OBJECTS and isinstance(v, dict):
                    pdoc[k] = {i: ({"same_record": records[(k, i, _key(r))]} if (k, i, _key(r)) in records else r)
                               for i, r in v.items()}  # fmt: skip
                    for i, r in v.items():
                        records.setdefault((k, i, _key(r)), docs)
                else:
                    pdoc[k] = v
            docs += 1
            row["doc"] = {**st["doc"], "body": pdoc}
        out.append(row)
    return out


def expand(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []
    out = []
    for st in steps:
        row = dict(st)
        body = (st.get("view") or {}).get("body")
        if isinstance(body, dict):
            full: dict[str, Any] = {}
            for k, v in body.items():
                if isinstance(v, dict) and set(v) == {"same_as"}:
                    full[k] = views[v["same_as"]][k]
                elif isinstance(v, list):
                    full[k] = [views[e["same_item"][0]][k][e["same_item"][1]]
                               if isinstance(e, dict) and set(e) == {"same_item"} else e for e in v]  # fmt: skip
                else:
                    full[k] = v
            views.append(full)
            row["view"] = {**st["view"], "body": full}
        doc = (st.get("doc") or {}).get("body")
        if isinstance(doc, dict):
            fdoc: dict[str, Any] = {}
            for k, v in doc.items():
                if k in OBJECTS and isinstance(v, dict):
                    fdoc[k] = {i: (docs[r["same_record"]][k][i] if isinstance(r, dict) and set(r) == {"same_record"}
                                   else r) for i, r in v.items()}  # fmt: skip
                else:
                    fdoc[k] = v
            docs.append(fdoc)
            row["doc"] = {**st["doc"], "body": fdoc}
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
            if "doc" in a and a["doc"]["order"] != (b.get("doc") or {}).get("order"):
                problems.append(f"/{name}/steps[{i}]/doc/order: the key order differs")
            if "doc" in a and json.dumps(a["doc"]["body"]) != json.dumps((b.get("doc") or {}).get("body")):
                problems.append(f"/{name}/steps[{i}]/doc/body: the serialized document differs")
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
    print("FOUNDER CALLS GOLDENS MATCH" if not problems else f"FOUNDER CALLS GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, s in golden["sets"].items():
        steps = expand(s["expected"])
        answers = [st["answer"].get("code", st["answer"].get("raises")) for st in steps if "answer" in st]
        states: dict[str, int] = {}
        for st in steps:
            for c in ((st.get("view") or {}).get("body") or {}).get("calls", []):
                states[c["due_state"] or "none"] = states.get(c["due_state"] or "none", 0) + 1
        out[name] = {"steps": len(steps), "answers": answers, "due_states": states, "ids_made": s["ids_made"]}
    return out


REAL_CLOCK = "2026-11-12T09:00:00"
REAL_LATER = "2026-11-30T09:00:00"


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    """The real snapshot imported by the production importer into a throw-away schema, against the OLD routes over a
    byte-exact copy: a full read (every call, memo and briefing), an edit of a real call, a follow-up on it, and a full
    read again at a later clock. Codes, bodies and the stored document's key order are compared; aggregates only."""
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.founder_calls.store import FounderCallsStore
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot_ = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot_.files()}
    doc = snapshot_.json("founder_calls.json", {}) or {}
    first = next(iter((doc.get("calls") or {}).keys()), None)
    steps: list[dict[str, Any]] = [{"op": "read_all"}]
    if first:
        steps += [{"op": "save", "body": {"id": first, "observations": "Parity check: an edited observation."}},
                  {"op": "followup", "body": {"id": first, "done": True}},
                  {"op": "read_all", "at": REAL_LATER}]  # fmt: skip
    old = run_oracle({"clock": REAL_CLOCK, "steps": steps}, files)
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    report: dict[str, Any] = {"oracle": old["meta"], "calls": len(doc.get("calls") or {})}
    problems: list[str] = []
    admin = connect(settings.db_url, autocommit=True)
    clock = [utc_instant(REAL_CLOCK)]
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
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:

            def ans(r: Any) -> dict[str, Any]:
                return {"code": r.status_code, "body": r.json()}

            for i, (step, exp) in enumerate(zip(steps, old["steps"], strict=True)):
                if step.get("at"):
                    clock[0] = utc_instant(step["at"])
                if step["op"] == "read_all":
                    got = {"view": ans(client.get("/api/founder-calls/calls"))}
                    got["call"] = {c: ans(client.get("/api/founder-calls/call", params={"id": c})) for c in exp["call"]}
                    got["memo"] = {c: ans(client.get("/api/founder-calls/memo", params={"id": c})) for c in exp["memo"]}
                    got["briefing"] = {f: ans(client.post("/api/founder-calls/briefing", json={"founder_id": f,
                                                                                              "confirm": True}))
                                       for f in exp["briefing"]}  # fmt: skip
                    for k in ("view", "call", "memo", "briefing"):
                        problems += [f"/step{i}/{k}{p.split(':')[0]}" for p in diff(js(exp[k]), js(got[k]))]
                else:
                    r = client.post(f"/api/founder-calls/{step['op']}", json=step["body"])
                    problems += [f"/step{i}/answer{p.split(':')[0]}" for p in diff(js(exp["answer"]), js(ans(r)))]
                    view = ans(client.get("/api/founder-calls/calls"))
                    problems += [f"/step{i}/view{p.split(':')[0]}" for p in diff(js(exp["view"]), js(view))]
                    with transaction(settings.db_url) as c:
                        stored = FounderCallsStore(c, schema).load()
                    order = {"top": list(stored or {})} | {k: list((stored or {}).get(k) or {}) for k in OBJECTS}
                    exp_order = {k: (exp["doc"]["order"] or {}).get(k) for k in ("top", *OBJECTS)}
                    if order != exp_order:
                        problems.append(f"/step{i}/doc order")
                    if js(stored) != js(exp["doc"]["body"]):
                        problems += [f"/step{i}/doc{p.split(':')[0]}" for p in diff(js(exp["doc"]["body"]), js(stored))]
            report["steps"] = len(steps)
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2, default=str))
    for p in problems[:60]:
        print("  DIFF", p)
    print("FOUNDER CALLS PARITY PASSED" if not problems else "FOUNDER CALLS PARITY FAILED")
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
