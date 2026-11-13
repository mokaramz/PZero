# ruff: noqa: E501
# (the invented world: one record per line)
"""Machine triage parity, part 2 (review 035b): the NEW cascade, runner and automatic triage against the OLD
``shadow_triage.run`` / ``auto_triage.start`` / ``run_retry`` / the Retry now route as oracle, over the SAME invented
world, the SAME recorded model replies and script, at a FIXED clock and uuid. No network, no real model.

    python -m projectzero.ops.parity_triage_cascade goldens   # (re)generates golden_v1/oracle_triage_cascade.json
    python -m projectzero.ops.parity_triage_cascade check     # the pure parts against the stored golden (no database)
    python -m projectzero.ops.parity_triage_cascade hosted    # the whole new side in a throw-away pz_itest_* schema
    python -m projectzero.ops.parity_triage_cascade real      # PZ_LEGACY_DATA (read only), paid OFF, pz_rehearse_*

The world (``world_docs``, invented names only): three candidates of a scan made while paid calls were off (Stage 0
junk before and after the first non-junk one), the cascade's cases in the next scan (Stage 0, a Flash KEEP with an
unknown theme and an unknown founder, a supported REJECT confirmed by the veto, a REJECT vetoed to WATCH, a veto that
is unavailable (timeout), a malformed reply then a valid one, two broken replies (``needs_human``), a timeout
(``error``), an unsupported REJECT downgraded, the veto's formatting repair), imported proposals (unchanged: skipped
with no call; stale; an older prompt version: ``previous``), a backlog candidate and a decided one (never selected),
then a scan whose run reaches the run cap part-way (the old ``AUTO_RUN_CAP_USD``: real on the new side, the gateway's
budget store), the hourly job with paid off, Retry now with paid off, the job with paid on, Retry now with nothing
waiting, the job with nothing due and a scan with nothing to do.

``check``: the hand-ported validator against the old pydantic model over ``validator_corpus`` (valid, repairable,
malformed and unsupported-REJECT replies), the system prompt's sha (pinned), each proposal the old runs wrote
re-derived by the new ``cascade.triage_one`` over the same recorded replies, and ``auto_rules.plain`` / ``summary`` over
the old records. ``hosted``: the world through the PRODUCTION importer into a scratch schema, then the script on the
new side: ``auto.after_scan`` / ``auto.run_retry`` / ``POST /api/deal-flow/triage_retry`` over the REAL gateway with a
``FakeProvider`` (paid, its reported cost) and the Postgres budget store; compared after each step: the answer, the
calls (role, purpose, model, ``use_cache``, entity, run id, cap, extra body, the messages' sha256), every proposal,
the runner runs, the automatic runs, the retry state (in its key order), the pending map, ``GET triage_auto`` and the
triage view. Every call's ledger rows carry its run id. ``real``: the real snapshot, paid OFF: a post-scan triage over
the imported candidates makes no provider call and writes no proposal; the view, Health and Today read back unchanged
(aggregates only are printed).

Declared differences, ALL applied by ``normalise`` (the ONE place):

* **(b) per-candidate commits / (g) the lock:** invisible on this path (the hosted tests force crashes and races).
* **(c) the paid switch's name:** the old "(kill switch)" texts read "(PZ_AI_PAID is not 'on')".
* **(d) the hourly job while paid is off:** the old job started a run that stopped at once; the new one writes no run
  and notes "Paid AI is off — N candidate(s) waiting for machine triage." The expected state after that step is the
  state before it, and the old run's record and runner summary are dropped from every later step.
* **storage:** an ``error`` proposal is stored as ``UNKNOWN`` (the old ``None``); a proposal record carries every
  promoted column (``None`` where the old record lacked the key).
* **ids and wall time:** ``call_id`` (each side's own) and ``latency_ms`` (measured) are not compared.

Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.core.inference import config as icfg
from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.triage import auto_rules, card, cascade
from projectzero.dealflow.triage import cascade_rules as rules
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js
from projectzero.ops.scratch_import import files_of

ORACLE = REPO_ROOT / "scripts" / "oracle" / "triage_cascade_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_triage_cascade.json"
RUN0, RUN1, RUN2, RUN3 = "2026-11-13 08:00:00", "2026-11-13 08:10:00", "2026-11-13 08:30:00", "2026-11-13 10:10:00"
OLD_RUN = "2026-10-01 08:00:00"
HEX = ["a0a0", "a1a1", "a2a2", "a3a3", "a4a4", "a5a5", "a6a6", "a7a7"]
PAID_OFF_TEXT = (auto_rules.PAID_OFF_OLD, auto_rules.PAID_OFF_NEW)
CHEAP, VETO = card.CHEAP_MODEL, card.VETO_MODEL
PAID_OFF_NOTE = "Paid AI is off — {n} candidate(s) waiting for machine triage."


# ------------------------------------------------------------------ the world (invented names only)
def _c(n: int, name: str, description: str, run: str, **extra: Any) -> dict[str, Any]:
    cid = f"c{n:02d}"
    base = {"id": cid, "name": name, "description": description, "source": "Invented Feed", "source_id": "fx-feed",
            "discovery_tier": "announcement", "decision": "new", "notes": "", "geo": ["DE"], "sectors": ["ai_sw"],
            "first_seen": f"2026-10-{n:02d}", "source_date": "2026-10-09", "location": "Berlin, Germany", "country": "DE",
            "source_url": f"https://feed.invented.example/news/{cid}", "first_seen_run": run, "last_observed": run,
            "run_id": run}  # fmt: skip
    return base | extra


def world_candidates() -> list[dict[str, Any]]:
    return [
        _c(1, "12.11.2026 18:00", "", RUN0),
        _c(2, "Quillon Robotics", "Quillon Robotics builds autonomous forklifts for small warehouses.", RUN0),
        _c(3, "[vc_row]", "", RUN0),
        _c(4, "Corvane Analytics", "Corvane Analytics models soil moisture from radar data.", OLD_RUN),
        _c(5, "Dellmar Sensing", "Dellmar Sensing makes lidar for tunnels.", OLD_RUN),
        _c(6, "Elstree Motion", "Elstree Motion builds exoskeletons for warehouse staff.", OLD_RUN, last_observed=RUN1),
        _c(7, "Farrowdale Labs", "Farrowdale Labs is an old backlog record.", OLD_RUN),
        _c(8, "Garnet Holdings", "Garnet Holdings manages rental flats.", RUN1, decision="rejected"),
        _c(11, "Thursday, November 12, 2026 ·", "", RUN1),
        _c(
            12,
            "Arvo Freight AI",
            "Arvo Freight AI was founded by Ada Quill and builds autonomous cranes for ports.",
            RUN1,
        ),
        _c(13, "Bramwell Consulting", "Bramwell Consulting is a management consultancy for regional banks.", RUN1),
        _c(14, "Cindral Games", "Cindral Games makes a consumer photo app for teenagers.", RUN1),
        _c(15, "Darrow Events", "Darrow Events organises a yearly founders' breakfast in Hamburg.", RUN1),
        _c(16, "Eskerfield Bio", "Eskerfield Bio engineers enzymes for textile recycling.", RUN1),
        _c(17, "Fenwick Orbital", "Fenwick Orbital develops docking hardware for small satellites.", RUN1),
        _c(18, "Galloway Thermal", "Galloway Thermal stores heat in volcanic rock for factories.", RUN1),
        _c(19, "Harrow Drives", "Harrow Drives builds robots for vineyards.", RUN1),
        _c(20, "Ilford Calendar", "Ilford Calendar lists networking events in Munich every week.", RUN1),
        _c(31, "Juniper Hydraulics", "Juniper Hydraulics builds hydraulic grippers for recycling robots.", RUN2),
        _c(32, "Kelvedon Optics", "Kelvedon Optics grinds lenses for laser welding heads.", RUN2),
        _c(33, "Larkspur Grid", "Larkspur Grid balances microgrids for farms.", RUN2),
        _c(34, "Marlow Rail", "Marlow Rail inspects railway tracks with drones.", RUN2),
        _c(35, "(406)", "", RUN2),
    ]


def _prop(c: Mapping[str, Any], proposal: str, **extra: Any) -> dict[str, Any]:
    p = {"candidate_id": c["id"], "name": c["name"], "tier": c.get("discovery_tier"), "source_id": c.get("source_id"),
         "proposal": proposal, "status": "proposed", "prompt_version": card.PROMPT_VERSION,
         "input_sha": card.card_sha(c), "run_id": "triage-20261001-080000-0f0f", "proposed_at": "2026-10-01T08:00:00",
         "attention_gate": None, "stage": "stage1", "model": CHEAP, "veto_model": VETO, "veto_mode": "no_thinking",
         "provider": "deepinfra", "usd": 0.0001, "cached": False, "latency_ms": 900, "call_id": "ic-0f0f0f0f0f0f",
         "schema_retry": False, "entity_type": "VENTURE", "capital_stage": "UNKNOWN", "sector": "robotics",
         "themes": [], "founders": [], "reasons": ["an invented reason"], "missing": [], "confidence": "medium",
         "reject_basis": None, "reject_evidence": "", "model_proposal": proposal, "flags": [], "path": "stage1"}  # fmt: skip
    return p | extra


def world_proposals() -> dict[str, dict[str, Any]]:
    by = {c["id"]: c for c in world_candidates()}
    return {
        "c04": _prop(by["c04"], "WATCH", prompt_version="triage-v2", input_sha="00000000000000aa"),
        "c05": _prop(by["c05"], "KEEP", input_sha="0123456789abcdef"),
        "c06": _prop(by["c06"], "RESEARCH"),
        "c08": _prop(by["c08"], "REJECT", reject_basis="NON_VENTURE", reject_evidence="manages rental flats"),
    }


def world_docs() -> dict[str, Any]:
    return {
        "inbox.json": {"candidates": world_candidates(), "last_run": RUN0, "reprocess_v": 3},
        "triage_proposals.json": {"version": 1, "proposals": world_proposals()},
        "shadow_triage/acceptance.json": {"status": "ACCEPTED — shadow only", "holdout": {"n": 10}},
    }


def _reply(proposal: str, **extra: Any) -> str:
    base = {"proposal": proposal, "reject_basis": None, "reject_evidence": "", "entity_type": "VENTURE",
            "capital_stage": "PRE_COMPANY", "sector": "industrial robotics", "themes": [], "founders": [],
            "reasons": ["an invented reason grounded in the text"], "missing": ["the funding round"],
            "confidence": "medium"}  # fmt: skip
    return json.dumps(base | extra, ensure_ascii=False)


def _ok(text: str, usd: float = 0.0001) -> dict[str, Any]:
    return {"text": text, "usd": usd}


def _timeout(seconds: int) -> dict[str, Any]:
    return {"error_kind": "timeout", "error": f"timed out after {seconds}s"}


def replies() -> dict[str, dict[str, list[dict[str, Any]]]]:
    rej_nv = _reply("REJECT", reject_basis="NON_VENTURE", reject_evidence="a management consultancy for regional banks",
                    entity_type="NON_VENTURE")  # fmt: skip
    return {
        "c02": {"CHEAP": [_ok(_reply("RESEARCH"))]},
        "c04": {"CHEAP": [_ok(_reply("WATCH", themes=["frontier"]))]},
        "c05": {"CHEAP": [_ok(_reply("KEEP", themes=["physical_world"]))]},
        "c12": {
            "CHEAP": [
                _ok(
                    _reply(
                        "KEEP",
                        themes=["industrial_autonomy", "space_tech"],
                        founders=["Ada Quill", "Nobody Here"],
                        confidence="High ",
                    )
                )
            ]
        },
        "c13": {"CHEAP": [_ok(rej_nv)], "STANDARD": [_ok(rej_nv)]},
        "c14": {
            "CHEAP": [
                _ok(_reply("REJECT", reject_basis="off thesis", reject_evidence="a consumer photo app for teenagers"))
            ],
            "STANDARD": [_ok(_reply("WATCH"))],
        },
        "c15": {
            "CHEAP": [
                _ok(
                    _reply(
                        "REJECT",
                        reject_basis="NON_VENTURE",
                        reject_evidence="organises a yearly founders' breakfast",
                        entity_type="NON_VENTURE",
                    )
                )
            ],
            "STANDARD": [_timeout(120)],
        },
        "c16": {"CHEAP": [_ok("Sorry, I cannot answer that."), _ok(_reply("RESEARCH"))]},
        "c17": {"CHEAP": [_ok("garbage"), _ok(_reply("MAYBE"))]},
        "c18": {"CHEAP": [_timeout(60), _ok(_reply("WATCH"))]},
        "c19": {
            "CHEAP": [_ok(_reply("REJECT", reject_basis="LATE_STAGE", reject_evidence="builds robots for vineyards"))]
        },
        "c20": {
            "CHEAP": [
                _ok(
                    _reply(
                        "REJECT",
                        reject_basis="NOT_AN_ENTITY",
                        reject_evidence="lists networking events in Munich",
                        entity_type="NOT_AN_ENTITY",
                    )
                )
            ],
            "STANDARD": [
                _ok(
                    json.dumps(
                        {
                            "proposal": "NOT_AN_ENTITY",
                            "entity_type": "NOT_AN_ENTITY",
                            "capital_stage": "UNKNOWN",
                            "reject_basis": "NOT_AN_ENTITY",
                            "confidence": "high",
                            "reject_evidence": "lists networking events in Munich",
                            "reasons": ["an event listing, not a company"],
                        }
                    )
                )
            ],
        },
        "c31": {"CHEAP": [_ok(_reply("RESEARCH"), 0.2)]},
        "c32": {"CHEAP": [_ok(_reply("RESEARCH"), 0.2)]},
        "c33": {"CHEAP": [_ok(_reply("WATCH"), 0.2)]},
        "c34": {"CHEAP": [{"stop": "budget_blocked"}, _ok(_reply("RESEARCH"))]},
    }


def script() -> list[dict[str, Any]]:
    return [
        {"clock": "2026-11-13T08:05:00", "op": "scan", "scan_run_id": RUN0, "paid": False},
        {"clock": "2026-11-13T08:10:00", "op": "scan", "scan_run_id": RUN1, "paid": True},
        {"clock": "2026-11-13T08:30:00", "op": "scan", "scan_run_id": RUN2, "paid": True},
        {"clock": "2026-11-13T08:50:00", "op": "job", "paid": False},
        {"clock": "2026-11-13T08:55:00", "op": "retry_now", "paid": False},
        {"clock": "2026-11-13T10:00:00", "op": "job", "paid": True},
        {"clock": "2026-11-13T10:05:00", "op": "retry_now", "paid": True},
        {"clock": "2026-11-13T10:07:00", "op": "job", "paid": True},
        {"clock": "2026-11-13T10:10:00", "op": "scan", "scan_run_id": RUN3, "paid": True},
    ]


def estimate_config() -> dict[str, Any]:
    cfg = icfg.load()
    return {
        "prices": cfg["prices"],
        "max_out": {r: cfg["roles"][r]["max_output_tokens"] for r in ("CHEAP", "STANDARD")},
    }


def validator_corpus() -> list[dict[str, Any]]:
    """Valid, repairable, malformed and unsupported-REJECT replies for the hand-ported validator."""
    card_a = "name: Robo Labs\ndescription: Robo Labs raised a Series C of €120M and employs 300 people\nlocation: Boston USA geo=US"
    card_b = "name: Thursday, November 26, 2026 · BayWa Co-Working Space\nsectors: space"
    us, eu = {"geo": ["US"], "country": "USA"}, {"geo": ["DACH"]}
    good = json.loads(_reply("KEEP"))
    obs = {"proposal": "NOT_AN_ENTITY", "entity_type": "NOT_AN_ENTITY", "capital_stage": "UNKNOWN", "reject_basis": "NOT_AN_ENTITY",
           "confidence": "high", "reject_evidence": "Thursday, November 26, 2026 · BayWa Co-Working Space", "reasons": ["an event listing"]}  # fmt: skip
    datas: list[tuple[str, Any, Any]] = [
        (card_a, None, good),
        (card_a, None, {**good, "proposal": " keep ", "entity_type": "pre company team", "confidence": " HIGH"}),
        (card_a, None, {**good, "themes": ["defence", "x", 3]}),
        (
            card_a,
            None,
            {**good, "themes": ["defence", "made_up"], "founders": ["Robo Labs", "Nobody"], "sector": "s" * 100},
        ),
        (card_a, None, {**good, "reasons": ["a" * 300, "b", "c", "d"], "missing": ["m"] * 5}),
        (card_a, None, {}),
        (card_a, None, "NOT_AN_ENTITY"),
        (card_a, None, [good]),
        (card_a, None, {**good, "proposal": "MAYBE"}),
        (card_a, None, {**good, "proposal": 3, "sector": None, "confidence": "absolute", "reasons": []}),
        (
            card_a,
            None,
            {**good, "themes": "defence", "founders": {"a": 1}, "missing": [None], "reasons": ["a", 2, None]},
        ),
        (card_a, None, {**good, "reject_basis": "WHATEVER", "reject_evidence": 4}),
        (card_a, None, {**good, "reject_basis": "n/a", "reject_evidence": None}),
        (
            card_a,
            None,
            {**good, "proposal": "REJECT", "reject_basis": "late-stage", "reject_evidence": "a Series C of €120M"},
        ),
        (card_a, None, {**good, "proposal": "REJECT", "reject_basis": "LATE_STAGE", "reject_evidence": "Robo Labs"}),
        (
            card_a,
            None,
            {**good, "proposal": "REJECT", "reject_basis": "OFF_THESIS", "reject_evidence": "not in the text"},
        ),
        (card_a, None, {**good, "proposal": "REJECT", "reject_basis": None, "reject_evidence": "Robo Labs"}),
        (card_a, None, {**good, "proposal": "REJECT", "reject_basis": "OFF_THESIS", "reject_evidence": "ab"}),
        (
            card_a,
            us,
            {**good, "proposal": "REJECT", "reject_basis": "OUTSIDE_GEOGRAPHY", "reject_evidence": "Boston USA"},
        ),
        (
            card_a,
            eu,
            {**good, "proposal": "REJECT", "reject_basis": "OUTSIDE_GEOGRAPHY", "reject_evidence": "Boston USA"},
        ),
        (
            card_a,
            None,
            {**good, "proposal": "REJECT", "reject_basis": "OUTSIDE_GEOGRAPHY", "reject_evidence": "Boston USA"},
        ),
        (card_b, None, obs),
        (card_b, None, {**obs, "reject_evidence": "a quote that is not in the candidate text"}),
        (card_b, None, {**obs, "reject_basis": "LATE_STAGE"}),
        (card_b, None, {**obs, "entity_type": "VENTURE"}),
        (card_b, None, {**obs, "proposal": "late stage", "reject_basis": None, "entity_type": "VENTURE"}),
        (card_b, None, {**obs, "proposal": None}),
        (card_b, None, {**obs, "proposal": "", "confidence": None}),
        (card_b, None, {"proposal": "NOT_AN_ENTITY"}),
        (card_b, None, {**good, "proposal": "WATCH", "reject_basis": "NON_VENTURE", "reject_evidence": "anything"}),
    ]
    return [{"card": c, "cand": cand, "data": d} for c, cand, d in datas]


def world_input() -> dict[str, Any]:
    return {"docs": world_docs(), "steps": script(), "replies": replies(), "hex": HEX, "estimate": estimate_config(),
            "corpus": validator_corpus()}  # fmt: skip


# ------------------------------------------------------------------ the oracle
def oracle(inp: Mapping[str, Any]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-triage-cascade-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        for rel, raw in files_of(dict(inp["docs"])).items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        srcf.write_bytes(json.dumps({k: v for k, v in inp.items() if k != "docs"}, ensure_ascii=False).encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL" and not k.endswith(("_API_KEY", "_TOKEN"))}
        env.update({"PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")})
        res = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if res.returncode != 0:
            raise SystemExit(f"oracle failed:\n{res.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_bytes().decode("utf-8"))
        return out


# ------------------------------------------------------------------ the declared differences (ONE place)
_PROMOTED = ("candidate_id", "run_id", "prompt_version", "input_sha", "proposal", "status", "model", "veto_model", "usd",
             "proposed_at")  # fmt: skip


def _texts(value: Any) -> Any:
    """(c): the old kill switch's name -> the new paid switch's, in every string."""
    if isinstance(value, str):
        return value.replace(*PAID_OFF_TEXT)
    if isinstance(value, list):
        return [_texts(v) for v in value]
    if isinstance(value, dict):
        return {k: _texts(v) for k, v in value.items()}
    return value


def _wall(p: Any) -> Any:
    """ids and wall time: ``call_id`` / ``latency_ms`` (here and in the veto) are not compared."""
    if not isinstance(p, dict):
        return p
    out = {k: v for k, v in p.items() if k not in ("call_id", "latency_ms")}
    if isinstance(out.get("veto"), dict):
        out["veto"] = {k: v for k, v in out["veto"].items() if k != "latency_ms"}
    return out


def proposal_old(p: Mapping[str, Any]) -> dict[str, Any]:
    """storage: the old record as the new one reads back (every promoted column; an error as ``UNKNOWN``)."""
    out = {**{k: None for k in _PROMOTED}, **dict(p)}
    if out.get("proposal") is None:
        out["proposal"] = "UNKNOWN"
    shown: dict[str, Any] = _wall(out)
    return shown


def dropped_runs(golden: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    """(d): the old job runs the new side never starts (paid off): their ``scan_run_id`` and runner ``run_id``."""
    scans: set[str] = set()
    runs: set[str] = set()
    for step, old in zip(golden["input"]["steps"], golden["expected"]["steps"], strict=True):
        last = old["auto_runs"][-1] if old["auto_runs"] else {}
        if step["op"] == "job" and not step["paid"] and last.get("scan_run_id") == f"retry {step['clock']}":
            scans.add(str(last["scan_run_id"]))
            if last.get("triage_run_id"):
                runs.add(str(last["triage_run_id"]))
    return scans, runs


def normalise(golden: Mapping[str, Any], i: int) -> dict[str, Any]:
    """The old step ``i`` -> the expected new one."""
    steps, olds = golden["input"]["steps"], golden["expected"]["steps"]
    step, old = steps[i], olds[i]
    scans, run_ids = dropped_runs(golden)
    last = old["auto_runs"][-1] if old["auto_runs"] else {}
    if i and step["op"] == "job" and last.get("scan_run_id") in scans:  # (d): no run; the state stays as it was
        base = normalise(golden, i - 1)
        return {**base, "answer": {"note": PAID_OFF_NOTE.format(n=last["selected"])}, "calls": []}
    s = _texts(copy.deepcopy(dict(old)))
    s["proposals"] = {k: proposal_old(p) for k, p in s["proposals"].items()}
    s["runs"] = [r for r in s["runs"] if r.get("run_id") not in run_ids]
    s["auto_runs"] = [r for r in s["auto_runs"] if r.get("scan_run_id") not in scans]
    for c in s["calls"]:
        c.pop("call_id", None)
    s["view"]["proposals"] = {
        k: {kk: vv for kk, vv in v.items() if kk != "queue"} for k, v in s["view"]["proposals"].items()
    }
    if s["status"].get("last") and s["status"]["last"].get("scan_run_id") in scans:
        s["status"]["last"] = auto_rules.plain(s["auto_runs"][-1]) if s["auto_runs"] else None
    return {
        k: s[k]
        for k in ("answer", "calls", "proposals", "runs", "auto_runs", "retry_state", "pending_map", "status", "view")
    }


# ------------------------------------------------------------------ check: the pure parts
def compare_pure(golden: Mapping[str, Any]) -> list[str]:
    inp, exp = golden["input"], golden["expected"]
    problems: list[str] = []
    if (
        exp["meta"]["system_prompt_sha256"] != rules.LOCKED_PROMPT_SHA
        or rules.system_prompt_sha() != rules.LOCKED_PROMPT_SHA
    ):
        problems.append("/prompt: the system prompt's sha256 is not the locked one")
    for k, (item, want) in enumerate(zip(inp["corpus"], exp["corpus"], strict=True)):
        try:
            got: dict[str, Any] = {
                "ok": cascade.validator_for(item["card"], item.get("cand"))(copy.deepcopy(item["data"]))
            }
        except ValueError as e:
            got = {"error": str(e)}
        problems += diff(js(want), js(got), f"/corpus[{k}]")
    # each proposal an old run wrote, re-derived from the same replies by the new cascade (one candidate at a time)
    queues = copy.deepcopy(inp["replies"])
    cards = {c["id"]: c for c in inp["docs"]["inbox.json"]["candidates"]}
    before = {k: v for k, v in inp["docs"]["triage_proposals.json"]["proposals"].items()}
    for i, (step, old) in enumerate(zip(inp["steps"], exp["steps"], strict=True)):
        written = {cid: p for cid, p in old["proposals"].items() if before.get(cid) != p}
        for cid, p in written.items():
            got_entry = _replay(cards[cid], before.get(cid), p, queues, step)
            problems += diff(js(proposal_old(p)), js(proposal_old(got_entry)), f"/step{i}/replay/{cid}")
        before = old["proposals"]
        for r in old["auto_runs"]:
            if r.get("summary") and r.get("state") != "running" and auto_rules.summary(r) != r["summary"]:
                problems.append(f"/step{i}/summary/{r.get('scan_run_id')}: the cut summary differs")
        if old["status"]["last"] is not None and old["auto_runs"]:
            problems += diff(js(old["status"]["last"]), js(auto_rules.plain(old["auto_runs"][-1])), f"/step{i}/plain")
    return problems


def _replay(
    c: Mapping[str, Any], prev: Any, want: Mapping[str, Any], queues: dict[str, Any], step: Mapping[str, Any]
) -> dict[str, Any]:
    from projectzero.core.inference.gateway import Result, extract_json

    cfg = icfg.load()

    def call(role: str, messages: list[dict[str, str]], *, purpose: str, entity_id: str, validate: Any, model: str | None,
             extra_body: Any, use_cache: bool) -> Result:  # fmt: skip
        res = Result(ok=False, role=role, provider="deepinfra", model=str(model or cfg["roles"][role]["model"]))
        q = queues[str(c["id"])][role]
        while "stop" in q[0]:  # a refusal writes no proposal: the proposal came from the next reply
            q.pop(0)
        o = q.pop(0)
        if "error_kind" in o:
            res.error_kind, res.error = o["error_kind"], o["error"]
            return res
        res.usd, res.text = float(o["usd"]), o["text"]
        data = extract_json(o["text"])
        if data is None:
            res.error_kind, res.error = "malformed", "reply contained no parseable JSON"
            return res
        try:
            res.data, res.ok = validate(data), True
        except ValueError as e:
            res.error_kind, res.error = "invalid", str(e)[:500]
        return res

    counts: Counter[str] = Counter()
    out = cascade.triage_one(c, prev, call=call, mdl=CHEAP, run_id=str(want.get("run_id")),
                             proposed_at=str(want.get("proposed_at")), counts=counts)  # fmt: skip
    assert isinstance(out, dict), (c["id"], out)
    return out


# ------------------------------------------------------------------ hosted: the whole new side
class Recorder:
    """The new side's calls as the oracle records them, through the REAL gateway (``auto.Deps.complete``)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.results: list[tuple[str, str | None]] = []

    def __call__(self, role: str, messages: list[dict[str, str]], **kw: Any) -> Any:
        from projectzero.core.inference import gateway

        cfg = kw.get("config") or icfg.load()
        self.calls.append({"role": role, "purpose": kw.get("purpose"), "model": kw.get("model") or cfg["roles"][role]["model"],
                           "use_cache": kw.get("use_cache", True), "entity_id": kw.get("entity_id"),
                           "run_id": kw.get("run_id"), "run_cap_usd": kw.get("run_cap_usd"),
                           "extra_body": kw.get("extra_body"), "override_reason": kw.get("override_reason"),
                           "messages_sha": hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest()})  # fmt: skip
        res = gateway.complete(role, messages, **kw)
        self.results.append((res.call_id, kw.get("run_id")))
        return res


def fake_provider(queues: dict[str, Any]) -> Any:
    """A paid ``FakeProvider`` answering from the recorded replies (the candidate from its card's source url; a
    timeout raises on each of the gateway's three attempts; a ``stop`` is the gateway's own refusal, never sent)."""
    from projectzero.core.inference.providers import FakeProvider, ProviderError, Reply

    tries: Counter[str] = Counter()

    def responder(messages: list[dict[str, str]], model: str) -> Any:
        m = re.search(r"/news/(c\d+)", messages[-1]["content"])
        assert m, "no candidate in the message"
        cid, role = m.group(1), ("STANDARD" if model == VETO else "CHEAP")
        q = [o for o in queues[cid][role] if "stop" not in o]
        queues[cid][role] = q
        o = q[0]
        if "error_kind" in o:
            tries[cid + role] += 1
            if tries[cid + role] >= 3:
                q.pop(0)
                tries[cid + role] = 0
            raise ProviderError(o["error_kind"], o["error"], dispatched=False)
        q.pop(0)
        usd = float(o["usd"])
        return Reply(text=o["text"], usage={"prompt_tokens": 100, "completion_tokens": 50, "estimated_cost": usd},
                     reported_usd=usd, model=model)  # fmt: skip

    return FakeProvider(responder, paid=True, name="deepinfra")


def new_state(client: Any, conn: Any, schema: str) -> dict[str, Any]:
    from projectzero.dealflow.triage import records

    amap = records.aliases(conn, schema)
    view = client.get("/api/deal-flow/triage").json()
    return {
        "proposals": {k: _wall(p) for k, p in records.current_proposals(conn, schema).items()},
        "runs": records.proposal_runs(conn, schema),
        "auto_runs": records.auto_runs(conn, schema)["runs"],
        "retry_state": [[k, v] for k, v in records.retry_state(conn, schema, amap).items()],
        "pending_map": view["pending"],
        "status": client.get("/api/deal-flow/triage_auto").json(),
        "view": {
            "proposals": {k: {kk: vv for kk, vv in v.items() if kk != "queue"} for k, v in view["proposals"].items()},
            "counts": view["counts"],
            "pending": view["pending"],
        },
    }


def hosted(golden: Mapping[str, Any] | None = None) -> int:  # pragma: no cover - needs the hosted database
    from fastapi.testclient import TestClient

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import transaction
    from projectzero.dealflow.triage import auto
    from projectzero.network.view import BERLIN
    from projectzero.ops.scratch_import import drop_schema, import_world

    load_dotenv()
    settings = Settings.from_env()
    golden = golden or json.loads(GOLDEN.read_text(encoding="utf-8"))
    inp = golden["input"]
    schema = import_world(settings.db_url, copy.deepcopy(inp["docs"]))
    problems: list[str] = []
    queues = copy.deepcopy(inp["replies"])
    provider = fake_provider(queues)
    _scans, dropped = dropped_runs(golden)
    hexes = iter(h for h in HEX if not any(r.endswith("-" + h) for r in dropped))  # (d): that run took no id
    ids = iter(f"ic-{n:012d}" for n in range(1, 10_000))
    try:
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for i, step in enumerate(inp["steps"]):
                clock_t = datetime.fromisoformat(step["clock"]).replace(tzinfo=BERLIN)
                clock = functools.partial(lambda c: c, clock_t)
                env = {"PZ_AI_PAID": "on"} if step["paid"] else {}
                rec = Recorder()
                gw = {"env": env, "providers": {"deepinfra": provider}, "clock": clock, "sleep": lambda s: None,
                      "new_id": lambda: next(ids)}  # fmt: skip
                deps = auto.Deps(gateway_kw=gw, clock=clock, new_hex=lambda: next(hexes), env={}, complete=rec)
                app.state.clock = clock
                app.state.triage_env = {}
                if step["op"] == "scan":
                    out = auto.after_scan(settings.db_url, schema, step["scan_run_id"], deps)
                    answer: Any = {"started": True} if "state" in out else out
                elif step["op"] == "job":
                    answer = {"note": auto.retry_note(auto.run_retry(settings.db_url, schema, deps=deps))}
                else:
                    answer = auto.retry_now(settings.db_url, schema, deps, wait=True)
                with transaction(settings.db_url) as conn:
                    new = {"answer": answer, "calls": rec.calls, **new_state(client, conn, schema)}
                    for call_id, run_id in rec.results:
                        rows = conn.execute(
                            f"select run_id, purpose from {schema}.model_ledger where call_id = %s".encode(), (call_id,)
                        ).fetchall()
                        if not rows or any(r[0] != run_id for r in rows):
                            problems.append(f"/step{i}/ledger/{call_id}: a ledger row without the run id")
                want = normalise(golden, i)
                problems += diff(js(want), js(new), f"/step{i}")
                print(json.dumps({"step": i, "op": step["op"], "paid": step["paid"], "calls": len(rec.calls),
                                  "answer": {k: v for k, v in answer.items() if k in ("started", "reason", "note")}},
                                 ensure_ascii=False))  # fmt: skip
    finally:
        drop_schema(settings.db_url, schema)
    for p in problems[:80]:
        print("  DIFF", p)
    print(
        "TRIAGE CASCADE HOSTED PARITY PASSED"
        if not problems
        else f"TRIAGE CASCADE HOSTED PARITY FAILED ({len(problems)})"
    )
    return 1 if problems else 0


# ------------------------------------------------------------------ the real snapshot (paid OFF)
REAL_CLOCK = datetime(2026, 11, 13, 12, 0, 0)
REAL_RUN = "2026-11-13 12:00:00"


def real() -> int:  # pragma: no cover - for the main session: needs the hosted database and the real data folder
    """The plan's "Real snapshot" check: the real data folder (READ ONLY: captured once, bytes only) imported by the
    PRODUCTION importer into a throw-away ``pz_rehearse_*`` schema; then a post-scan triage with paid calls OFF over the
    imported candidates (a scan run id no imported record carries). Expected: no provider call, no proposal written for
    an imported candidate, and the triage view, System health and Today read back unchanged. Aggregates only."""
    import secrets as _secrets

    from fastapi.testclient import TestClient

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.core.inference.providers import FakeProvider
    from projectzero.dealflow.triage import auto
    from projectzero.network.view import BERLIN
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot
    from projectzero.ops.parity_validation import _fingerprint
    from projectzero.ops.scratch_import import drop_schema

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))  # reads the bytes; never writes there
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    problems: list[str] = []
    report: dict[str, Any] = {}
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot), schema=schema, conn=conn)
            assert applied.get("applied"), "the importer refused the snapshot"
        finally:
            conn.close()
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        clock_t = REAL_CLOCK.replace(tzinfo=BERLIN)
        app.state.clock = lambda: clock_t
        provider = FakeProvider(
            lambda m, model: (_ for _ in ()).throw(AssertionError("a provider call")), paid=True, name="deepinfra"
        )
        gw = {"env": {}, "providers": {"deepinfra": provider}, "clock": lambda: clock_t, "sleep": lambda s: None}

        def reads(client: Any) -> dict[str, Any]:
            return {"triage": client.get("/api/deal-flow/triage").json(), "health": client.get("/api/system_health").json(),
                    "today": client.get("/api/today").json()}  # fmt: skip

        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            before = reads(client)
            with transaction(settings.db_url) as c2:
                tables_before = _fingerprint(c2, schema)
                props_before = c2.execute(f"select count(*) from {schema}.triage_proposals".encode()).fetchone()
                st = auto.load_state(c2, schema)
            selected = auto.select(st, REAL_RUN, REAL_CLOCK)
            report["undecided"] = len(st.new)
            report["selected"] = len(selected)
            report["stale_selected"] = sum(
                1 for cid in selected if (st.proposals.get(cid) or {}).get("status") == "proposed"
            )
            out = auto.after_scan(
                settings.db_url, schema, REAL_RUN, auto.Deps(gateway_kw=gw, clock=lambda: clock_t, env={})
            )
            report["record"] = {
                k: out.get(k) for k in ("state", "selected", "triaged", "unchanged_skipped") if k in out
            }
            report["record_pending"] = len(out.get("pending") or [])
            report["provider_calls"] = len(provider.calls)
            after = reads(client)
            with transaction(settings.db_url) as c2:
                tables_after = _fingerprint(c2, schema)
                props_after = c2.execute(f"select count(*) from {schema}.triage_proposals".encode()).fetchone()
                ledger_rows = c2.execute(
                    f"select count(*) from {schema}.model_ledger where run_id like 'triage-2026111%%'".encode()
                ).fetchone()
        report["proposals_written"] = int(props_after[0]) - int(props_before[0])  # type: ignore[index]
        report["ledger_rows_of_this_run"] = int(ledger_rows[0])  # type: ignore[index]
        report["tables_changed"] = sorted(
            k for k in set(tables_before) | set(tables_after) if tables_before.get(k) != tables_after.get(k)
        )
        if report["provider_calls"]:
            problems.append("/provider: a call was made with paid calls off")
        if report["proposals_written"] and report["stale_selected"] == 0:
            problems.append("/proposals: a proposal was written for an imported candidate")
        for k in ("triage", "health", "today"):
            for d in diff(js(before[k]), js(after[k]), f"/{k}"):
                problems.append(d)
    finally:
        admin.close()
        drop_schema(settings.db_url, schema)
    print(json.dumps(report, ensure_ascii=False))
    shapes = Counter(
        re.sub(r"/(proposals|pending|candidates|items)/[^/:\[]+", r"/\1/<id>", d.split(":")[0]) for d in problems
    )
    for shape, n in shapes.most_common(40):
        print(f"  DIFF {shape} x{n}")  # path shapes only: never a real id, name or value
    print(
        "TRIAGE CASCADE REAL PARITY PASSED" if not problems else f"TRIAGE CASCADE REAL PARITY FAILED ({len(problems)})"
    )
    return 1 if problems else 0


# ------------------------------------------------------------------ goldens / check
def write_goldens() -> int:
    inp = world_input()
    out = oracle(inp)
    meta = out.pop("meta")
    golden = {"provenance": meta, "input": inp, "expected": {"meta": meta, **out}}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    if out.get("blocked"):
        print("BLOCKED WRITES in the oracle:", out["blocked"])
        return 1
    for step, old in zip(inp["steps"], out["steps"], strict=True):
        last = old["auto_runs"][-1] if old["auto_runs"] else {}
        print(json.dumps({"op": step["op"], "paid": step["paid"], "calls": len(old["calls"]), "state": last.get("state"),
                          "selected": last.get("selected"), "pending": len(last.get("pending") or []),
                          "answer": old["answer"] if step["op"] != "scan" else None}, ensure_ascii=False))  # fmt: skip
    problems = compare_pure(golden)
    for p in problems[:60]:
        print("  DIFF", p)
    print("TRIAGE CASCADE GOLDENS MATCH" if not problems else f"TRIAGE CASCADE GOLDENS DIFFER ({len(problems)})")
    return 1 if problems else 0


def check() -> int:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    problems = compare_pure(golden)
    if golden["expected"].get("blocked"):
        problems.append(f"/blocked: the oracle wrote outside its folder: {golden['expected']['blocked']}")
    if golden["input"] != js(world_input()):
        problems.append("/input: the stored world differs from world_input() (regenerate the goldens)")
    for p in problems[:60]:
        print("  DIFF", p)
    print("TRIAGE CASCADE CHECK PASSED" if not problems else f"TRIAGE CASCADE CHECK FAILED ({len(problems)})")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    mode = argv[1:]
    if mode == ["goldens"]:
        return write_goldens()
    if mode == ["check"]:
        return check()
    if mode == ["hosted"]:
        return hosted()
    if mode == ["real"]:
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
