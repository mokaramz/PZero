"""Investment Desk parity: the pure port against the OLD code as oracle, with a FIXED clock and no write (review 031a).

    python -m projectzero.ops.parity_home goldens   # (re)generates golden_v1/oracle_home.json (needs the old repo)
    python -m projectzero.ops.parity_home check     # the stored golden against the new code (no oracle)
    python -m projectzero.ops.parity_home real      # (not yet: the real snapshot through the route, see ``real``)

The oracle (``scripts/oracle/home_oracle.py``) runs the old ``ecosys.home()`` once per world over a scratch data
folder holding the world's documents, the clock frozen at the world's ``clock`` (naive Berlin wall time) and every
write blocked (the folder is checked unchanged). The new side is the PURE port (``home.inputs_from_docs`` ->
``home.view``) over the same documents at the same clock. Every answer is compared value by value AND as serialized
text (key order); the inputs and the documents are checked unchanged.

Declared differences: none. The payload is the old one key for key (decision b, one clock, is the oracle's frozen
clock; decision a, reads never write, holds on both sides: the old desk wrote nothing either).

The worlds hold INVENTED names only (``p-omar-hedeya`` is the code constant's id; its person is invented):

* ``main`` (Friday 2026-11-13): the best opportunity by PROVISIONAL score (79, not fully verified) with its prepared
  case's action as ``next`` (source "prepared case", not its stored ``next_action``), a tie at 79 stored later (``max``
  keeps the first), a fully verified 78 below it; higher scores excluded: ``potential_conflict``, ``unclear``
  (CONFLICT GATED), an Omar-negative hold (WATCHING), a prepared case asking Omar (CONFLICT GATED), a prepared case
  with no active work (WATCHING), a dropped company; the weekend-first event (a higher-ranked weekday event ranks
  first); ``due`` (8) and ``watch`` (8) cut to 6; 4 new candidates in inbox order (c-205 before c-101) cut to 3, a
  rejected one and one without id left out; the Omar list sorted (a tie keeps the stored order) and cut to 5, a
  dropped company's left out; every ``progress`` count across the 7-day boundary (2026-11-06 in, 11-05 out, a
  timestamp, ``detected_on``, the excluded ``p-omar-hedeya``, a past planned event).
* ``fallback``: the best opportunity by VERIFIED score (fully verified 78 above a provisional 77) from the score band
  (``next`` is its stored ``next_action``); no weekend event: the best upcoming one (``wsig[0]``), an unscorable one
  last.
* ``gated``: every live company excluded (``priority: null``); no recommendable event in 21 days (skipped, too far,
  past, not high-signal): ``best_event: null``; no new candidate.
* ``legacy``: unreadable legacy values (a score as text, ``verified`` a list, ``earliness`` a number) read as neutral
  on a copy (``data_warning``): the best opportunity; a stored ``data_warning`` with a list ``conflict`` (read as
  ``unclear``: gated); records without a company, a non-dict record and a dropped company left out.
* ``empty``: no document at all.

Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.conviction.operator import OperatorInputs, fingerprint
from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.ranking.names import slug
from projectzero.home import UNREADABLE, inputs_from_docs, view
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "home_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_home.json"
CLOCK = "2026-11-13T09:00:00"  # a Friday: the weekend window is 2026-11-14 / 15, ``week_ago`` 2026-11-06

FULL = {"founders": True, "funding": True, "traction": True}
NO_TRACTION = {"founders": True, "funding": True}
STRONG = {"founder": 22, "venture_scale": 17, "why_now": 13, "taste": 12, "insight": 8}
MAX = {"founder": 30, "venture_scale": 25, "why_now": 20, "taste": 15, "insight": 10}
WEAK = {"founder": 8, "venture_scale": 9, "why_now": 6, "taste": 5, "insight": 2}
HIGH = {
    "founder_density": 25,
    "tech_talent": 20,
    "earliness": 15,
    "domain_fit": 15,
    "network_value": 10,
    "accessibility": 10,
    "serendipity": 5,
}
MID = {
    "founder_density": 16,
    "tech_talent": 14,
    "earliness": 11,
    "domain_fit": 10,
    "network_value": 7,
    "accessibility": 7,
    "serendipity": 3,
}
LOW = {
    "founder_density": 8,
    "tech_talent": 7,
    "earliness": 6,
    "domain_fit": 5,
    "network_value": 3,
    "accessibility": 3,
    "serendipity": 1,
}


# ------------------------------------------------------------------ the synthetic worlds (invented names only)
def entry(company: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "company": company,
        "one_liner": f"{company} builds software for industrial operators",
        "status": "new",
        "scores": dict(WEAK),
        "earliness": "pre_seed",
        "conflict": "none",
        "archetype": 5,
        "verified": {},
        "founders": [],
        "discovery_date": "2026-11-01",
    }
    base.update(kw)
    return base


def case(e: dict[str, Any], prepared_at: str, code: str, label: str, decisions: list[str]) -> dict[str, Any]:
    """A prepared case whose fingerprint matches the record as stored (no founder call is recorded in these worlds)."""
    fp = fingerprint({**e, "slug": slug(e["company"])}, OperatorInputs())
    card = {"next_action": {"code": code, "label": label, "why": f"the invented case of {e['company']} says so"},
            "conflict": {"gated": False}, "decisions": [{"text": t} for t in decisions]}  # fmt: skip
    return {"prepared_at": prepared_at, "fingerprint": fp, "card": card}


def person(pid: str, name: str, **kw: Any) -> dict[str, Any]:
    return {"id": pid, "name": name, **kw}


def ev(eid: str, name: str, start: str, parts: dict[str, int] | None, **kw: Any) -> dict[str, Any]:
    out = {"id": eid, "name": name, "start": start, "city": "Berlin", "url": f"https://events.invented.example/{eid}",
           "status": "new", "human_verified": True, "type": "pitch_night"}  # fmt: skip
    if parts is not None:
        out["score_parts"] = parts
    return {**out, **kw}


def cand(cid: str | None, name: str, source: str, decision: str = "new") -> dict[str, Any]:
    """An inbox record as every real Deal Flow record carries it (``decision``, ``discovery_tier``, ``source_id``: the
    importer keeps such a record whole, and the desk reads its ``source`` name from it)."""
    out: dict[str, Any] = {"name": name, "description": f"{name}: invented", "decision": decision, "source": source,
                           "source_id": f"s-{source}", "discovery_tier": "grant"}  # fmt: skip
    return out if cid is None else {"id": cid, **out}


def main_docs() -> dict[str, Any]:
    signals = [
        entry(
            "Invented Arclight Systems", scores=dict(STRONG), verified=FULL, next_action="Invented: send the intro note"
        ),
        entry("Invented Dunmore Analytics", scores=dict(MAX), conflict="potential_conflict"),
        entry("Invented Eskerfield", scores=dict(MAX), conflict="unclear"),
        entry(
            "Invented Kestrel Defence", scores=dict(MAX), omar_outcome="negative", omar_outcome_at="2026-11-05T10:00:00"
        ),
        entry("Invented Selby Optics", scores=dict(MAX)),
        entry("Invented Pellow Farms", scores=dict(MAX)),
        entry(
            "Invented Larch Dynamics",
            scores=dict(MAX),
            verified=FULL,
            status="dropped",
            sent_to_omar="2026-11-13",
            discovery_date="2026-11-12",
        ),
        entry(
            "Invented Juniper Grid",
            scores={**STRONG, "insight": 9},
            verified={"founders": True},
            next_action="Invented: an older note",
            fundraising_timing="0_6m",
        ),
        entry("Invented Quarry Point", scores={**STRONG, "insight": 9}),
        entry("Invented Corvid Labs", scores=dict(STRONG), status="contacted"),
        entry("Invented Brindle Works", status="replied", verified=FULL),
        entry("Invented Carrow Data", status="forwarded"),
        entry("Invented Dalby Air", status="watch"),
        entry(
            "Invented Ovenden Works",
            sent_to_omar="2026-11-12",
            omar_feedback="Invented: worth a call",
            discovery_date="2026-11-06",
        ),
        entry("Invented Ruddock Labs", sent_to_omar="2026-11-01", discovery_date="2026-11-05"),
        entry("Invented Wexcombe", sent_to_omar="2026-11-12", discovery_date="2026-11-13T08:00:00"),
        entry("Invented Yelverton", sent_to_omar="2026-11-07", discovery_date="", detected_on="2026-11-10"),
        entry("Invented Vellacott", sent_to_omar="2026-11-06", discovery_date=None),
        entry("Invented Harrow Metrics", sent_to_omar="2026-11-05", omar_feedback=""),
        entry("Invented Mallow Sensors", sent_to_omar="2026-10-20", omar_feedback="Invented: not now"),
    ]
    by = {e["company"]: e for e in signals}
    cases = {
        slug("Invented Juniper Grid"): case(
            by["Invented Juniper Grid"],
            "2026-11-10T10:00:00",
            "VERIFY_AND_CALL",
            "Verify the founders' prior exit",
            ["Is the pilot paid?"],
        ),
        slug("Invented Selby Optics"): case(
            by["Invented Selby Optics"], "2026-11-10T10:00:00", "ASK_OMAR", "Ask Omar", []
        ),
        slug("Invented Pellow Farms"): case(
            by["Invented Pellow Farms"], "2026-11-09T10:00:00", "NO_ACTIVE_WORK", "No active work", []
        ),
    }
    people = [
        person("p-omar-hedeya", "Invented Manager", created="2026-11-12", watch=True, last_checked="2026-11-11"),
        person(
            "p-1",
            "Invented Ada Brenner",
            next_action="Send the memo",
            next_action_date="2026-11-10",
            created="2026-11-06",
            location="Berlin, Germany",
            last_interaction="2026-10-01",
        ),
        person(
            "p-2",
            "Invented Ben Okafor",
            next_action="Call back",
            created="2026-11-05",
            watch=True,
            last_checked="2026-11-01",
            last_interaction="2026-09-01",
        ),
        person(
            "p-3",
            "Invented Cleo Varga",
            next_action="Intro to the lab",
            next_action_date="2026-11-13",
            created="2026-11-13",
            watch=True,
            last_interaction="2026-11-12",
        ),
        person(
            "p-4",
            "Invented Dov Ames",
            next_action="Coffee",
            next_action_date="2026-11-14",
            watch=True,
            last_checked="2026-11-02",
        ),
        person(
            "p-5",
            "Invented Eda Lund",
            next_action="Ask about the spin-off",
            next_action_date="2026-11-01",
            watch=True,
            last_checked="2026-10-30",
            last_interaction="2026-08-15",
        ),
        person(
            "p-6",
            "Invented Finn Rao",
            next_action="Send the paper",
            next_action_date="2026-11-12",
            created="2026-11-08T12:00:00",
            watch=True,
            last_interaction="2026-10-20",
        ),
        person("p-7", "Invented Gia Holt", next_action="Follow up", watch=True, last_checked="2026-10-01"),
        person(
            "p-8",
            "Invented Hal Brink",
            next_action="Thank you note",
            next_action_date="2026-11-02",
            last_interaction="2026-11-01",
        ),
        person(
            "p-9", "Invented Ivo Senn", next_action="Ask for the deck", next_action_date="2026-11-11", location="Munich"
        ),
        person(
            "p-10",
            "Invented Jae Moss",
            next_action="Lunch",
            next_action_date="soon",
            watch=True,
            last_checked="2026-11-09",
        ),
        {"name": "Invented Nobody", "next_action": "Never listed", "watch": True},
    ]
    events = [
        ev("ev-1", "Invented Founders Forge Night", "2026-11-20", HIGH),
        ev("ev-2", "Invented Founders Build Day", "2026-11-14", MID),
        ev("ev-3", "Invented Founders Robotics Salon", "2026-11-15", LOW, city="Munich"),
        ev("ev-4", "Invented Seed Sprint", "2026-11-25", MID, status="planned"),
        ev("ev-5", "Invented Founders Past Evening", "2026-11-01", LOW, status="planned"),
        ev("ev-6", "Invented Founders Breakfast", "2026-11-18", HIGH, status="skipped"),
        ev("ev-7", "Invented Founders Winter Summit", "2026-12-10", HIGH),
    ]
    inbox = [
        cand("c-205", "Invented Rookwood", "invented-feed-b"),
        cand("c-101", "Invented Quillon", "invented-feed-a"),
        cand("c-150", "Invented Sablewood", "invented-feed-a", decision="rejected"),
        cand(None, "Invented No Id", "invented-feed-a"),
        cand("c-104", "Invented Tamworth Optics", "invented-registry"),
        cand("c-106", "Invented Ashby Motion", "invented-feed-c"),
        cand("c-107", "Invented Brindle Works", "invented-feed-c", decision="kept"),
    ]
    return {
        "real_data.json": {"week": "2026-W46", "signals": signals},
        "people.json": {"people": people},
        "case_prep/cases.json": {"cases": cases},
        "events.json": {"events": events, "leads": []},
        "event_sources.json": {"sources": []},
        "inbox.json": {"candidates": inbox},
    }


def fallback_docs() -> dict[str, Any]:
    return {
        "real_data.json": {
            "signals": [
                entry(
                    "Invented Bramble Robotics",
                    scores={**STRONG, "insight": 7},
                    verified=NO_TRACTION,
                    next_action="Invented: ask about the round",
                ),
                entry(
                    "Invented Arclight Systems",
                    scores=dict(STRONG),
                    verified=FULL,
                    next_action="Invented: book the intro call",
                ),
                entry("Invented Ilford Quantum", verified=FULL),
            ]
        },
        "people.json": {
            "people": [
                person(
                    "p-1",
                    "Invented Oda Brix",
                    next_action="Ask for the deck",
                    next_action_date="2026-11-20",
                    location="Berlin",
                ),
                person("p-2", "Invented Tom Aske", next_action="Call", next_action_date="2026-11-12"),
            ]
        },
        "events.json": {
            "events": [
                ev("ev-1", "Invented Founders Deep Tech Breakfast", "2026-11-17", MID),
                ev("ev-2", "Invented Founders Robotics Salon", "2026-11-19", HIGH),
                ev("ev-3", "Invented Quiet Gathering", "2026-11-18", None),
                ev("ev-4", "Invented Founders Undated Mixer", "", MID),
            ]
        },
        "inbox.json": {
            "candidates": [
                cand("c-1", "Invented Ash Signal", "invented-feed"),
                cand("c-2", "Invented Birch Cloud", "invented-feed"),
            ]
        },
    }


def gated_docs() -> dict[str, Any]:
    return {
        "real_data.json": {
            "signals": [
                entry("Invented Dunmore Analytics", scores=dict(STRONG), verified=FULL, conflict="potential_conflict"),
                entry("Invented Eskerfield", conflict="unclear"),
                entry("Invented Kestrel Defence", omar_outcome="negative", omar_outcome_at="2026-11-01T10:00:00"),
                entry("Invented Larch Dynamics", scores=dict(MAX), status="dropped"),
            ]
        },
        "people.json": {
            "people": [person("p-1", "Invented Oda Brix", next_action="Coffee", next_action_date="2026-11-30")]
        },
        "events.json": {
            "events": [
                ev("ev-1", "Invented Founders Skipped Night", "2026-11-14", HIGH, status="skipped"),
                ev("ev-2", "Invented Founders Far Summit", "2026-12-20", HIGH),
                ev("ev-3", "Invented Founders Past Night", "2026-11-01", HIGH),
                ev("ev-4", "Invented Unreviewed Gathering", "2026-11-16", None, human_verified=False, url="", type=""),
            ]
        },
        "inbox.json": {
            "candidates": [
                cand("c-1", "Invented Ash Signal", "invented-feed", decision="rejected"),
                cand("c-2", "Invented Birch Cloud", "invented-feed", decision="watch"),
            ]
        },
    }


def legacy_docs() -> dict[str, Any]:
    return {
        "real_data.json": {
            "signals": [
                entry(
                    "Invented Umber Fields",
                    scores={"founder": "24", "venture_scale": "eighteen", "why_now": 14, "taste": "12", "insight": 9},
                    verified=["founders"],
                    earliness=7,
                    conflict=None,
                    next_action="Invented: ask for the deck",
                ),
                entry(
                    "Invented Tarn Robotics",
                    scores=dict(MAX),
                    conflict=["similar"],
                    data_warning="an older stored warning",
                ),
                {"one_liner": "a record without a company", "scores": dict(MAX)},
                "a record that is not an object",
                entry("", scores=dict(MAX)),
                entry("Invented Yew Dynamics", scores=dict(MAX), status="dropped"),
                entry("Invented Wold Systems", scores={"founder": "abc"}, verified=FULL, sent_to_omar="2026-11-09"),
            ]
        },
        "people.json": {
            "people": [
                {"name": "Invented No Id", "created": "2026-11-12"},
                person("p-1", "Invented Pia Moor", created="2026-11-06T10:00:00"),
            ]
        },
        "events.json": {"events": []},
        "inbox.json": {
            "candidates": [
                cand(None, "Invented No Id", "invented-feed"),
                cand("", "Invented Empty Id", "invented-feed"),
                cand("c-9", "Invented Vane Instruments", "invented-registry"),
            ]
        },
    }


WORLDS: dict[str, tuple[Any, str]] = {
    "main": (main_docs, CLOCK),
    "fallback": (fallback_docs, CLOCK),
    "gated": (gated_docs, CLOCK),
    "legacy": (legacy_docs, CLOCK),
    "empty": (dict, CLOCK),
}


# ------------------------------------------------------------------ the oracle
def files_of(docs: dict[str, Any]) -> dict[str, bytes]:
    return {
        k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)).encode("utf-8")
        for k, v in docs.items()
    }


def run_oracle(worlds: dict[str, tuple[dict[str, Any], str]]) -> dict[str, Any]:
    return oracle_over({name: (files_of(docs), clock) for name, (docs, clock) in worlds.items()})


def oracle_over(worlds: dict[str, tuple[dict[str, bytes], str]]) -> dict[str, Any]:
    """The old desk once per world, over a scratch data folder holding the world's files byte for byte."""
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-home-oracle-") as tmp:
        data = Path(tmp) / "data"
        for name, (files, _clock) in worlds.items():
            folder = data / name
            folder.mkdir(parents=True)
            for rel, raw in files.items():
                target = (folder / rel).resolve()
                if folder.resolve() not in target.parents:
                    raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        inp = {"worlds": [{"name": n, "clock": c} for n, (_d, c) in worlds.items()]}
        srcf.write_bytes(json.dumps(inp, ensure_ascii=False).encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL" and not k.endswith(("_API_KEY", "_TOKEN"))}
        env.update(
            {
                "PZ_DATA": str(data),
                "PZ_TESTING": "1",
                "PZ_CASE_PREP": "0",
                "PYTHONPATH": str(OLD_REPO / "backend" / "src"),
            }
        )
        run = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_bytes().decode("utf-8"))
        return out


# ------------------------------------------------------------------ the new side
def as_read(docs: dict[str, Any]) -> dict[str, Any]:
    """The documents as the readers see them: a JSON document given as raw TEXT (a file that does not parse) is
    ``UNREADABLE``; the JSONL logs are their text."""
    return {k: UNREADABLE if isinstance(v, str) and not k.endswith(".jsonl") else v for k, v in docs.items()}


def new_side(docs: dict[str, Any], clock: str) -> tuple[dict[str, Any], list[str]]:
    """The new answer (``raises``: where the old route would have answered 500) and the purity invariants."""
    now = datetime.fromisoformat(clock)
    today = now.date()
    docs_before = copy.deepcopy(docs)
    problems: list[str] = []
    try:
        inputs = inputs_from_docs(as_read(docs), today, now)
    except Exception as exc:
        return {"raises": type(exc).__name__}, problems
    inputs_before = copy.deepcopy(inputs)
    try:
        answer: dict[str, Any] = {"ok": js(view(inputs, today, now))}
    except Exception as exc:  # the old route would have answered 500
        answer = {"raises": type(exc).__name__}
    if inputs != inputs_before:
        problems.append("/inputs: the desk changed its inputs")
    if docs != docs_before:
        problems.append("/docs: inputs_from_docs changed the documents")
    return answer, problems


def _text(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def compare_world(name: str, w: dict[str, Any]) -> list[str]:
    expected = w["expected"]
    problems: list[str] = []
    for k in ("changed", "blocked"):
        if expected.get(k):
            problems.append(f"/{name}/{k}: the OLD read wrote {expected[k]}")
    got, invariants = new_side(w["docs"], w["clock"])
    problems += [f"/{name}{p}" for p in invariants]
    old = {k: expected[k] for k in ("ok", "raises") if k in expected}
    problems += [f"/{name}{p}" for p in diff(js(old), js(got))]
    if _text(old) != _text(got):
        problems.append(f"/{name}: the serialized answer differs (key order)")
    return problems


def compare_goldens(golden: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for name, w in golden["worlds"].items():
        problems += compare_world(name, w)
    return problems


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, w in golden["worlds"].items():
        e = w["expected"]
        body = e.get("ok") or {}
        prio = body.get("priority") or {}
        best = body.get("best_event") or {}
        out[name] = {
            "clock": w["clock"],
            "priority": [
                prio.get("company"),
                prio.get("score"),
                prio.get("verified"),
                (prio.get("op") or {}).get("source"),
                prio.get("next"),
            ]
            if prio
            else None,
            "best_event": [best.get("name"), best.get("weekend"), best.get("rank")] if best else None,
            "due": len(body.get("due") or []),
            "watch": len(body.get("watch") or []),
            "new_signals": body.get("new_signals"),
            "latest": [s["name"] for s in body.get("latest_signals") or []],
            "omar": [o["sent"] for o in body.get("omar") or []],
            "progress": body.get("progress"),
            "weekday": body.get("weekday"),
            "skipped": e.get("skipped"),
            "raises": e.get("raises"),
        }
    return out


def read_golden(path: Path = GOLDEN) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(path.read_bytes().decode("utf-8"))
    return out


def write_goldens() -> int:
    worlds = {name: (fn(), clock) for name, (fn, clock) in WORLDS.items()}
    oracle = run_oracle(worlds)
    by_name = {w.pop("name"): w for w in oracle["worlds"]}
    golden = {
        "provenance": oracle["meta"],
        "worlds": {n: {"clock": c, "docs": d, "expected": by_name[n]} for n, (d, c) in worlds.items()},
    }
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    # NOT sort_keys: the documents' insertion order is part of the input (and of what the oracle recorded)
    GOLDEN.write_bytes((json.dumps(golden, ensure_ascii=False, indent=None) + "\n").encode("utf-8"))
    return report(read_golden(), "HOME GOLDENS")


def report(golden: dict[str, Any], label: str) -> int:
    problems = compare_goldens(golden)
    print(json.dumps({"golden": str(GOLDEN), "bytes": GOLDEN.stat().st_size, "old": golden["provenance"],
                      "summary": summary(golden)}, indent=1, ensure_ascii=False))  # fmt: skip
    for p in problems[:60]:
        print("  DIFF", p)
    print(f"{label} MATCH (0 differences)" if not problems else f"{label} DIFFER ({len(problems)})")
    return 1 if problems else 0


SCOUT_ONLY = ("legacy_scout00", "legacy_native")  # the origins of the retired Scout views


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    """The real snapshot imported by the production importer into a throw-away schema, through ``GET /api/home`` at
    the pinned ``CLOCK``, against the OLD ``ecosys.home()`` over a byte-exact copy at the same clock. Every table is
    checked unchanged by the read. Aggregates only are printed.

    Declared (j), and normalised here only: ``new_signals`` counts every candidate awaiting a decision in the MERGED
    Deal Flow, as the desk's own "Candidates to decide" tile (the new inbox) does; the old one counted ``inbox.json``
    only. The difference must be exactly the imported Scout-only candidates (``origins`` within ``SCOUT_ONLY``) whose
    status is ``new``. The golden worlds hold none."""
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot
    from projectzero.ops.parity_founder_calls import utc_instant
    from projectzero.ops.parity_validation import _fingerprint

    load_dotenv()
    settings = Settings.from_env()
    snapshot_ = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot_.files()}
    old = oracle_over({"real": (files, CLOCK)})["worlds"][0]
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    problems = [f"/old/{k}: the OLD read wrote {old[k]}" for k in ("changed", "blocked") if old.get(k)]
    report_: dict[str, Any] = {}
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot_), schema=schema, conn=conn)
            assert applied.get("applied"), applied
        finally:
            conn.close()
        with transaction(settings.db_url) as c:
            before = _fingerprint(c, schema)
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: utc_instant(CLOCK)
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            r = client.get("/api/home")
        got = {"ok": js(r.json())} if r.status_code == 200 else {"raises": r.status_code}
        with transaction(settings.db_url) as c:
            after = _fingerprint(c, schema)
            q = _sql.SQL("select count(*) from {}.candidates where status = 'new' and origins <@ %s::text[]").format(
                _sql.Identifier(schema)
            )
            row = c.execute(q, (list(SCOUT_ONLY),)).fetchone()
        scout_only = int(row[0]) if row else 0
        expected = copy.deepcopy({k: old[k] for k in ("ok", "raises") if k in old})
        if isinstance(expected.get("ok"), dict):  # declared (j): the merge brought the Scout-only items into Deal Flow
            expected["ok"]["new_signals"] += scout_only
        problems += diff(js(expected), js(got))
        if _text(expected) != _text(got):
            problems.append("/: the serialized answer differs (key order)")
        changed = sorted(t for t in before if before[t] != after.get(t))
        if changed:
            problems.append(f"/stored: the desk read changed {changed}")
        body = got.get("ok") or {}
        prio = body.get("priority") or {}
        report_ = {"clock": CLOCK, "priority": bool(prio), "priority_verified": prio.get("verified"),
                   "best_event": bool(body.get("best_event")), "due": len(body.get("due") or []),
                   "new_signals": body.get("new_signals"), "latest_signals": len(body.get("latest_signals") or []),
                   "omar": len(body.get("omar") or []), "progress": body.get("progress"),
                   "watch": len(body.get("watch") or []), "weekday": body.get("weekday"),
                   "old_skipped": old.get("skipped"), "tables_checked": len(before),
                   "declared_scout_only_new": scout_only}  # fmt: skip
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report_["differences"] = len(problems)
    print(json.dumps(report_, indent=2, default=str, ensure_ascii=False))
    for line in problems[:60]:
        print("  DIFF", line)
    print("HOME REAL PARITY PASSED" if not problems else "HOME REAL PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "check"
    if mode == "goldens":
        return write_goldens()
    if mode == "check":
        return report(read_golden(), "HOME CHECK")
    if mode == "real":
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
