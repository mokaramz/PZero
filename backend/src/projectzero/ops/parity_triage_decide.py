# ruff: noqa: E501
# (the invented world: one record per line)
"""Machine triage decisions parity: the NEW decide / batch reject against the OLD ``triage_review.decide`` /
``batch_reject`` / ``view()`` / ``calibration()`` as oracle, over the SAME invented world and script, at a FIXED clock
(review 035a). No model call, no network.

    python -m projectzero.ops.parity_triage_decide goldens   # (re)generates golden_v1/oracle_triage_decide.json
    python -m projectzero.ops.parity_triage_decide check     # the pure parts against the stored golden (no database)
    python -m projectzero.ops.parity_triage_decide hosted    # the whole new side in a throw-away pz_itest_* schema
    python -m projectzero.ops.parity_triage_decide real      # PZ_LEGACY_DATA (read only) through a pz_rehearse_* import

The world (``world_docs``): candidates with proposals of every path (Stage 0, both models reject, a veto WATCH, a
``needs_human``, a stale one, a Conviction-conflict flagged one, a single-model REJECT, a KEEP, a RESEARCH), an already
decided candidate, one without a proposal (pending in the automatic runs), two inbox records of one company (the
importer merges ``dup-b`` into ``dup-a``: one invented DUNS) and an archived ``triage_decisions.jsonl`` (an absorbed id's line, a line for
a candidate that no longer exists, an unreadable line, a CRLF line). The script (``script``): accept, override, KEEP,
RESEARCH with a note, every refusal, an override with a note, an empty batch, the batch preview, then its confirm.

``check``: per step, over the OLD state before / after the step (no database): the new pure answer and log line of a
decision, the new batch classification, and the new view build (``view.build`` with the merge aliases) of the old
files. ``hosted``: the world through the PRODUCTION importer into a scratch schema, then the same script through the
routes (``app.state.clock`` frozen per step); compared after each step: the answer (with its status code), the log
lines (archive + rows), every candidate's decision and notes, and the view's ``proposals`` / ``counts`` /
``calibration`` / ``pending``. ``model_ledger`` must not change.

Declared differences, ALL applied by ``normalise`` (the ONE place):

* **(a) the statuses:** RESEARCH -> ``reviewing`` (the old ``research``): compared in the old vocabulary
  (``STATUS_TO_DECISION``), so nothing to normalise; the event's ``reason`` is additive (not compared).
* **(b) / (d) atomicity:** invisible on this path (the hosted tests force the failures).
* **(c) no case preparation:** the old RESEARCH started ``case_prep.request``; the oracle records the calls, the
  expected new side has none.
* **(e) per survivor:** the old ``_latest_verdicts`` / ``calibration`` keyed lines by the recorded id; the expected
  ``mohamed`` of every proposal and the ``calibration`` are the OLD code's values over the same lines with each id
  mapped through the merge aliases first (the oracle's ``survivor``).
* **(f) ``expected_status``:** additive; the old code ignored the key (one decide sends it, both sides get it).
* **revision 2, ``same candidate as another id``:** a batch id naming the same survivor as an earlier one is that
  skip in the new answer (the old batch counted it by its own old reason, or applied it and logged its line).
* **(review 009) the absorbed record:** ``dup-b`` is no candidate of its own: its proposal, its counts and its
  decision leave the old side; its ``pending`` entry (none here) would map to the survivor.
* **errors:** the old ``ApiError`` was a 400 ``{ok: false, error}``; every answer carries its status code.

The world holds INVENTED names only. Exit 1 on any difference.
"""

from __future__ import annotations

import copy
import functools
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

from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.ranking.service import STATUS_TO_DECISION
from projectzero.dealflow.triage import card, view
from projectzero.dealflow.triage import decide as td
from projectzero.dealflow.triage import log as triage_log
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js
from projectzero.ops.parity_triage import counts_with, counts_without
from projectzero.ops.scratch_import import files_of

ORACLE = REPO_ROOT / "scripts" / "oracle" / "triage_decide_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_triage_decide.json"
ALIASES = {"dup-b": "dup-a"}  # what the importer does with the two records of one company (hosted asserts it)
CLOCK0 = datetime(2026, 11, 13, 10, 0, 0)


# ------------------------------------------------------------------ the world (invented names only)
def _c(cid: str, name: str, description: str, **extra: Any) -> dict[str, Any]:
    base = {"id": cid, "name": name, "description": description, "source": "Invented Feed", "source_id": "fx-feed",
            "discovery_tier": "announcement", "decision": "new", "notes": "", "geo": ["DE"], "sectors": ["ai_sw"],
            "first_seen": "2026-10-10", "source_date": "2026-10-09", "location": "Berlin, Germany", "country": "DE",
            "source_url": f"https://feed.invented.example/news/{cid}"}  # fmt: skip
    return base | extra


def world_candidates() -> list[dict[str, Any]]:
    same = "Kestrel Mapping builds survey software for municipal surveyors."
    return [
        _c("tri-acc", "Arvelle Robotics", "Arvelle Robotics builds welding cells for small factories."),
        _c("tri-ovr", "Brontide Labs", "Brontide Labs offers consulting for regional retailers."),
        _c("tri-keep", "Calyx Forge", "Calyx Forge builds metal printing for aerospace parts."),
        _c("tri-veto", "Dornwell Systems", "Dornwell Systems sells inventory software to pharmacies."),
        _c("tri-human", "Embry Analytics", "Embry Analytics models crop yields from satellite data."),
        _c("tri-s0", "07.10.2026 11:00", ""),
        _c("tri-both", "Fennimore Cartage", "Fennimore Cartage is a family haulage business since 1952."),
        _c("tri-both2", "Gorsedd Holdings", "Gorsedd Holdings manages rental flats in Leipzig."),
        _c("tri-stale", "Halvard Optics", "Halvard Optics changed its text after the machine read it."),
        _c("tri-flag", "Ilsworth Dynamics", "Ilsworth Dynamics resells office furniture."),
        _c("tri-done", "Jessamy Biotech", "Jessamy Biotech is a contract laboratory.", decision="rejected"),
        _c("dup-a", "Kestrel Mapping", same, first_seen="2026-10-01", entity_ids={"duns": "987654321"}),
        _c("dup-b", "Kestrel Mapping", same, first_seen="2026-10-05", entity_ids={"duns": "987654321"}),
        _c("tri-none", "Lumen Quarry", "Lumen Quarry builds quarry drones."),
    ]


def _prop(c: Mapping[str, Any], proposal: str, **extra: Any) -> dict[str, Any]:
    p = {"candidate_id": c["id"], "name": c["name"], "proposal": proposal, "status": "proposed",
         "prompt_version": card.PROMPT_VERSION, "input_sha": card.card_sha(c), "proposed_at": "2026-10-20T08:00:00",
         "model": card.CHEAP_MODEL, "model_proposal": proposal, "stage": "stage1", "path": "cheap",
         "confidence": "medium", "reasons": ["an invented reason"], "missing": [], "flags": [],
         "capital_stage": "UNKNOWN", "themes": [], "sector": "software", "entity_type": "VENTURE",
         "run_id": "triage-20261020-080000-ab12", "reject_basis": None, "reject_evidence": None}  # fmt: skip
    return p | extra


def _both(c: Mapping[str, Any], basis: str = "NON_VENTURE", **extra: Any) -> dict[str, Any]:
    veto = {"model": card.VETO_MODEL, "mode": "standard", "ok": True, "model_proposal": "REJECT",
            "reject_basis": basis, "reasons": ["not a venture"]}  # fmt: skip
    return _prop(c, "REJECT", stage="veto", path="cheap REJECT -> veto: both reject", reject_basis=basis,
                 reject_evidence=str(c["description"])[:40], veto_model=card.VETO_MODEL, veto=veto, **extra)  # fmt: skip


def world_proposals() -> dict[str, dict[str, Any]]:
    by = {c["id"]: c for c in world_candidates()}
    out = {
        "tri-acc": _prop(by["tri-acc"], "RESEARCH"),
        "tri-ovr": _prop(by["tri-ovr"], "REJECT", reject_basis="NON_VENTURE", reject_evidence="consulting"),
        "tri-keep": _prop(by["tri-keep"], "KEEP", capital_stage="PRE_COMPANY"),
        "tri-veto": _prop(by["tri-veto"], "WATCH", stage="veto", path="cheap REJECT -> veto: second opinion WATCH",
                          model_proposal="REJECT", veto_model=card.VETO_MODEL,
                          veto={"model": card.VETO_MODEL, "mode": "standard", "ok": True, "model_proposal": "WATCH",
                                "reject_basis": None, "reasons": ["maybe later"]}),
        "tri-human": _prop(by["tri-human"], "RESEARCH", status="needs_human", path="schema failure"),
        "tri-s0": _prop(by["tri-s0"], "REJECT", stage="stage0", path="stage0 junk", model=None,
                        reject_basis="NOT_AN_ENTITY", reject_evidence="07.10.2026 11:00"),
        "tri-both": _both(by["tri-both"]),
        "tri-both2": _both(by["tri-both2"], "NOT_AN_ENTITY"),
        "tri-stale": _both(by["tri-stale"], input_sha="0123456789abcdef"),
        "tri-flag": _both(by["tri-flag"]),
        "tri-done": _both(by["tri-done"]),
        "dup-a": _both(by["dup-a"]),
        "dup-b": _both(by["dup-b"]),
    }  # fmt: skip
    return out


def _line(**e: Any) -> str:
    base = {"ts": "2026-10-30T10:00:00", "candidate_id": "", "name": None, "machine": "REJECT", "machine_path": "cheap",
            "machine_reject_basis": None, "machine_model": card.CHEAP_MODEL, "machine_run_id": "triage-20261001-000000-0000",
            "prompt_version": card.PROMPT_VERSION, "verdict": "REJECT", "mode": "accept", "agreed": True,
            "inbox_decision_applied": "rejected", "note": ""}  # fmt: skip
    return json.dumps(base | e, ensure_ascii=False, sort_keys=True)


def archived_log() -> str:
    return (
        _line(candidate_id="dup-b", name="Kestrel Mapping", verdict="WATCH", mode="override", agreed=False,
              inbox_decision_applied="watch") + "\n"
        + "not json\n"
        + _line(ts="2026-10-30T10:05:00", candidate_id="tri-gone", name="Gone Co", machine="KEEP", verdict="KEEP",
                inbox_decision_applied=None) + "\r\n"
        + _line(ts="2026-10-30T10:06:00", candidate_id="tri-human", name="Embry Analytics", machine="RESEARCH",
                verdict="RESEARCH", inbox_decision_applied="research") + "\n"
    )  # fmt: skip


def world_docs() -> dict[str, Any]:
    return {
        "inbox.json": {"candidates": world_candidates(), "last_run": "2026-10-20 08:00:00", "reprocess_v": 3},
        "triage_proposals.json": {"version": 1, "proposals": world_proposals()},
        "triage_decisions.jsonl": archived_log(),
        "real_data.json": {
            "signals": [
                {
                    "company": "Ilsworth Dynamics",
                    "conflict": "potential_conflict",
                    "status": "new",
                    "one_liner": "Invented conflict record",
                }
            ]
        },
        "shadow_triage/acceptance.json": {"status": "ACCEPTED — shadow only", "holdout": {"n": 10}},
        "shadow_triage/auto_runs.json": {
            "runs": [{"pending": [{"id": "tri-none", "reason": "provider outage"}], "failed": []}]
        },
    }


def script() -> list[dict[str, Any]]:
    ids = ["tri-s0", "tri-both", "tri-both2", "tri-stale", "tri-flag", "tri-veto", "tri-acc", "tri-done", "dup-a",
           "dup-b", "tri-none", "tri-ghost", "tri-both", "tri-human"]  # fmt: skip
    ops: list[tuple[str, dict[str, Any]]] = [
        ("decide", {"id": "tri-acc", "verdict": "RESEARCH", "mode": "accept", "expected_status": "new"}),
        ("decide", {"id": "tri-ovr", "verdict": "watch", "mode": "override"}),
        ("decide", {"id": "tri-keep", "verdict": "KEEP"}),
        (
            "decide",
            {
                "id": "tri-veto",
                "verdict": "RESEARCH",
                "mode": "override",
                "note": "Talk to the founders first — ünïcode.",
            },
        ),
        ("decide", {"id": "tri-human", "verdict": "REJECT", "mode": "accept"}),
        ("decide", {"id": "tri-human", "verdict": "MAYBE"}),
        ("decide", {"id": "tri-human", "verdict": "REJECT", "mode": "later"}),
        ("decide", {"id": "tri-ghost", "verdict": "REJECT", "mode": "override"}),
        ("decide", {"id": "tri-none", "verdict": "REJECT", "mode": "override"}),
        ("decide", {"id": "tri-human", "verdict": "REJECT", "mode": "override", "note": "Not a venture."}),
        ("batch", {"ids": []}),
        ("batch", {"ids": ids}),
        ("batch", {"ids": ids, "confirm": True}),
    ]
    return [{"clock": CLOCK0.replace(minute=i).isoformat(), "op": op, "body": body} for i, (op, body) in enumerate(ops)]


def world_input() -> dict[str, Any]:
    return {"aliases": ALIASES, "docs": world_docs(), "steps": script()}


# ------------------------------------------------------------------ the oracle
def oracle(inp: Mapping[str, Any]) -> dict[str, Any]:
    """The invented world (``world_input``): its documents written as ``scratch_import.files_of`` writes them."""
    return oracle_files(files_of(dict(inp["docs"])), inp["aliases"], inp["steps"])


def oracle_files(files: Mapping[str, bytes], aliases: Mapping[str, str], steps: list[Any]) -> dict[str, Any]:
    """The oracle over raw files (the invented world's, or a byte-exact copy of the real snapshot) in a scratch folder."""
    inp = {"aliases": dict(aliases), "steps": steps}
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-triage-decide-oracle-") as tmp:
        data = Path(tmp) / "data"
        data.mkdir()
        for rel, raw in files.items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        srcf.write_bytes(json.dumps({k: inp[k] for k in ("aliases", "steps")}, ensure_ascii=False).encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL" and not k.endswith(("_API_KEY", "_TOKEN"))}
        env.update({"PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")})
        res = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if res.returncode != 0:
            raise SystemExit(f"oracle failed:\n{res.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_bytes().decode("utf-8"))
        return out


# ------------------------------------------------------------------ the declared differences (ONE place)
def _absorbed(aliases: Mapping[str, str] | None = None) -> set[str]:
    return {a for a, s in (ALIASES if aliases is None else aliases).items() if a != s}


def _old_reason(raw: str, before: Mapping[str, Any]) -> str | None:
    """The old batch's classification of one id over the old state before the step (``None``: eligible)."""
    s = before["view"]["proposals"].get(raw)
    c = next((x for x in before["inbox"] if x["id"] == raw), None)
    if not s or not c:
        return td.NO_PROPOSAL
    if c["decision"] != "new":
        return td.ALREADY_DECIDED
    if not s["obvious_reject"]:
        return td.NOT_OBVIOUS
    return None


def _lines(text: str) -> list[str]:
    return text.splitlines()


def normalise(
    step: Mapping[str, Any],
    before: Mapping[str, Any],
    body: Mapping[str, Any],
    op: str,
    aliases: Mapping[str, str] | None = None,
    carried: Mapping[str, tuple[str, Mapping[str, Any], bool]] | None = None,
) -> dict[str, Any]:
    """The old step -> the expected new one. ``before``: the old state before the step (the previous step, or the
    world as imported). ``aliases``: the merge aliases (default: the invented world's). ``carried`` (the real
    snapshot, review 009): survivor id -> (the absorbed old id, the new view's summary, the survivor is undecided) for
    a survivor with no proposal of its own that the view CARRIES an absorbed record's proposal to: expected is the new
    summary with the OLD absorbed proposal's machine value, and its count when undecided. ``op`` ``view``: no write
    (no answer)."""
    amap = dict(ALIASES if aliases is None else aliases)
    s = copy.deepcopy(dict(step))
    absorbed = _absorbed(amap)
    before_lines = _lines(before["log"])
    lines = _lines(s["log"])
    added = lines[len(before_lines) :]
    answer: dict[str, Any] | None
    if op == "view":
        answer = None
    elif "error" in s:
        answer = {"status": 400, "ok": False, "error": s["error"]}
    else:
        answer = {"status": 200, **s["answer"]}
    if op == "batch" and answer is not None and "error" not in s:  # revision 2: the same survivor twice
        seen: set[str] = set()
        skipped = dict(answer["skipped"])
        for raw in dict.fromkeys(str(i) for i in body["ids"]):
            sid = amap.get(raw, raw)
            if sid not in seen:
                seen.add(sid)
                continue
            reason = _old_reason(raw, before)
            if reason is None:
                answer["eligible" if answer.get("preview") else "applied"] -= 1
                added = [x for x in added if json.loads(x).get("candidate_id") != raw]
            else:
                skipped[reason] -= 1
                if not skipped[reason]:
                    del skipped[reason]
            skipped[td.SAME_CANDIDATE] = skipped.get(td.SAME_CANDIDATE, 0) + 1
        answer["skipped"] = skipped
    v = s["view"]
    decisions = {c["id"]: c["decision"] for c in s["inbox"]}
    dropped = [v["proposals"][a] for a in absorbed if a in v["proposals"] and decisions.get(a) == "new"]
    latest = s["survivor"]["latest"]
    proposals = {}
    for cid, p in v["proposals"].items():
        if cid in absorbed:
            continue
        e = latest.get(cid)  # (e): the old code's latest line per survivor
        p["mohamed"] = (
            {"verdict": e.get("verdict"), "mode": e.get("mode"), "at": e.get("ts"), "agreed": e.get("agreed")}
            if e
            else None
        )
        proposals[cid] = p
    added_counts = []
    for sid, (oid, summary, undecided) in (carried or {}).items():
        proposals[sid] = {**copy.deepcopy(dict(summary)), "proposal": v["proposals"][oid]["proposal"]}
        if undecided:
            added_counts.append(summary)
    expected_view = {
        "proposals": proposals,
        "counts": counts_with(counts_without(v["counts"], dropped), added_counts),
        "calibration": s["survivor"]["calibration"],  # (e)
        "pending": {amap.get(k, k): x for k, x in v["pending"].items()},
    }
    return {
        "answer": answer,
        "log": before_lines + added,
        "candidates": {
            c["id"]: {"decision": c["decision"], "notes": c.get("notes")} for c in s["inbox"] if c["id"] not in absorbed
        },
        "view": expected_view,
    }


def world_state() -> dict[str, Any]:
    """The old state before the first step, in the oracle's step shape (``view`` / ``survivor`` are only read for the
    batch's old reasons, and the first step is no batch)."""
    docs = world_docs()
    return {"log": docs["triage_decisions.jsonl"], "inbox": [{"id": c["id"], "decision": c["decision"],
            "notes": c["notes"]} for c in docs["inbox.json"]["candidates"]], "view": {"proposals": {}}}  # fmt: skip


# ------------------------------------------------------------------ check: the pure parts
def pure_inputs(state: Mapping[str, Any]) -> view.TriageInputs:
    """The new view's inputs over an old state (as the importer would hold it: the absorbed record folded away)."""
    docs = world_docs()
    absorbed = _absorbed()
    st = {c["id"]: c for c in state["inbox"]}
    records = [
        {**c, "decision": st[c["id"]]["decision"], "notes": st[c["id"]]["notes"]}
        for c in docs["inbox.json"]["candidates"]
        if c["id"] not in absorbed
    ]
    props = {k: p for k, p in docs["triage_proposals.json"]["proposals"].items() if k not in absorbed}
    return view.TriageInputs(
        candidates=[c for c in records if c["id"] in props],
        proposals=props,
        decision_log=state["log"],
        conviction_signals=docs["real_data.json"]["signals"],
        scout_items={},
        acceptance=docs["shadow_triage/acceptance.json"],
        auto_runs=copy.deepcopy(docs["shadow_triage/auto_runs.json"]),
        aliases=dict(ALIASES),
    )


def pure_step(before: Mapping[str, Any], step: Mapping[str, Any]) -> dict[str, Any]:
    """The new pure answer (and the decision's line) over the old state before the step."""
    inp = pure_inputs(before)
    built = view.build(inp)
    records = {c["id"]: c for c in inp.candidates}
    body = step["body"]
    ts = td.now_ts(datetime.fromisoformat(step["clock"]))
    try:
        if step["op"] == "decide":
            req = td.parse_decide(body)
            sid = ALIASES.get(req.candidate_id, req.candidate_id)
            known = {c["id"] for c in world_candidates()} - _absorbed()
            if not req.candidate_id or sid not in known:
                raise td.TriageError(f"unknown candidate {req.candidate_id!r}")
            p, c = inp.proposals.get(sid), records.get(sid)
            if c is None or p is None or p.get("status") not in view.OPEN_STATUSES:
                raise td.TriageError("this candidate has no machine proposal")
            td.check_accept(req.mode, req.verdict, p)
            applied = td.VERDICT_TO_INBOX[req.verdict]
            entry = td.log_entry(c, p, req.verdict, req.mode, applied, req.note, ts)
            answer = {"ok": True, "verdict": req.verdict, "agreed": entry["agreed"], "inbox_decision": applied,
                      "open_keep": req.verdict == "KEEP"}  # fmt: skip
            return {"answer": {"status": 200, **answer}, "added": [triage_log.line(entry)]}
        ids = td.batch_ids(body)
        known = {c["id"] for c in world_candidates()}
        resolved = {i: (ALIASES.get(i, i) if i in known else None) for i in ids}
        latest = view.latest_verdicts(view.decisions(inp.decision_log), inp.aliases)
        eligible, skipped = td.classify_batch(ids, resolved, built["proposals"], records, latest)
        if not body.get("confirm"):
            return {"answer": {"status": 200, "ok": True, "preview": True, "eligible": len(eligible),
                               "skipped": skipped}, "added": []}  # fmt: skip
        added = [triage_log.line(td.log_entry(records[i], inp.proposals[i], "REJECT", "batch_accept", "rejected", "", ts))
                 for i in eligible]  # fmt: skip
        return {"answer": {"status": 200, "ok": True, "applied": len(eligible), "skipped": skipped}, "added": added}
    except td.TriageError as exc:
        return {"answer": {"status": 400, "ok": False, "error": str(exc)}, "added": []}


def compare_pure(golden: Mapping[str, Any]) -> list[str]:
    inp, exp = golden["input"], golden["expected"]
    problems: list[str] = []
    before: Mapping[str, Any] = world_state()
    for i, (step, old) in enumerate(zip(inp["steps"], exp["steps"], strict=True)):
        want = normalise(old, before, step["body"], step["op"])
        got = pure_step(before, step)
        problems += diff(js(want["answer"]), js(got["answer"]), f"/step{i}/answer")
        problems += diff(js(want["log"]), js(_lines(before["log"]) + got["added"]), f"/step{i}/log")
        built = view.build(pure_inputs(old))
        new_view = {k: built[k] for k in ("proposals", "counts", "calibration", "pending")}
        for s in new_view["proposals"].values():
            s.pop("queue", None)
        for s in want["view"]["proposals"].values():
            s.pop("queue", None)
        problems += diff(js(want["view"]), js(new_view), f"/step{i}/view")
        before = old
    return problems


# ------------------------------------------------------------------ hosted: the whole new side
def new_state(client: Any, conn: Any, schema: str, response: Any, keep_queue: bool = False) -> dict[str, Any]:
    from psycopg.rows import dict_row

    from projectzero.dealflow.ranking.service import ranking_input
    from projectzero.dealflow.triage import log as triage_log

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"select * from {schema}.candidates order by id".encode())
        rows = cur.fetchall()
        cur.execute(f"select raw from {schema}.legacy_documents where path = 'triage_decisions.jsonl'".encode())
        archived = cur.fetchone()
    candidates = {}
    for r in rows:
        c, _ = ranking_input(r)
        candidates[str(r["id"])] = {"decision": STATUS_TO_DECISION.get(str(r["status"]), c.get("decision")),
                                    "notes": c.get("notes")}  # fmt: skip
    text = bytes(archived["raw"]).decode("utf-8") if archived else ""
    got = client.get("/api/deal-flow/triage").json()
    for s in got["proposals"].values():
        if not keep_queue:  # the invented world has no routes; the real snapshot compares the overlay too
            s.pop("queue", None)
    return {
        "answer": None if response is None else {"status": response.status_code, **response.json()},
        "log": _lines(triage_log.log_text(conn, schema, text)),
        "candidates": candidates,
        "view": {k: got[k] for k in ("proposals", "counts", "calibration", "pending")},
    }


def hosted(golden: Mapping[str, Any] | None = None) -> int:  # pragma: no cover - needs the hosted database
    from fastapi.testclient import TestClient

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import transaction
    from projectzero.network.view import BERLIN
    from projectzero.ops.scratch_import import drop_schema, import_world

    load_dotenv()
    settings = Settings.from_env()
    golden = golden or json.loads(GOLDEN.read_text(encoding="utf-8"))
    inp, exp = golden["input"], golden["expected"]
    schema = import_world(settings.db_url, copy.deepcopy(inp["docs"]))
    problems: list[str] = []
    try:
        with transaction(settings.db_url) as conn:
            imported = {str(a): str(c) for a, c in conn.execute(
                f"select alias_id, candidate_id from {schema}.candidate_aliases where namespace = 'candidate' "
                "and alias_id <> candidate_id".encode()).fetchall()}  # fmt: skip
            ledger_before = conn.execute(
                f"select count(*), coalesce(max(id), 0) from {schema}.model_ledger".encode()
            ).fetchone()
        if imported != ALIASES:
            problems.append(f"/aliases: the importer merged {sorted(imported)} (expected {sorted(ALIASES)})")
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        before: Mapping[str, Any] = world_state()
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for i, (step, old) in enumerate(zip(inp["steps"], exp["steps"], strict=True)):
                clock = datetime.fromisoformat(step["clock"]).replace(tzinfo=BERLIN)
                app.state.clock = functools.partial(lambda c: c, clock)
                path = "decide" if step["op"] == "decide" else "batch_reject"
                response = client.post(f"/api/deal-flow/triage/{path}", json=step["body"])
                with transaction(settings.db_url) as conn:
                    new = new_state(client, conn, schema, response)
                want = normalise(old, before, step["body"], step["op"])
                for s in want["view"]["proposals"].values():
                    s.pop("queue", None)
                problems += diff(js(want), js(new), f"/step{i}")
                print(json.dumps({"step": i, "op": step["op"], "status": response.status_code,
                                  "answer": {k: v for k, v in new["answer"].items() if k != "status"}},
                                 ensure_ascii=False))  # fmt: skip
                before = old
        with transaction(settings.db_url) as conn:
            ledger_after = conn.execute(
                f"select count(*), coalesce(max(id), 0) from {schema}.model_ledger".encode()
            ).fetchone()
        if ledger_after != ledger_before:
            problems.append("/model_ledger: changed by the triage routes")
    finally:
        drop_schema(settings.db_url, schema)
    for p in problems[:80]:
        print("  DIFF", p)
    print(
        "TRIAGE DECIDE HOSTED PARITY PASSED"
        if not problems
        else f"TRIAGE DECIDE HOSTED PARITY FAILED ({len(problems)})"
    )
    return 1 if problems else 0


# ------------------------------------------------------------------ the real snapshot
REAL_CLOCK = datetime(2026, 11, 13, 11, 0, 0)
WRITABLE = frozenset({"candidates", "candidate_events", "triage_decisions"})


def real_choice(
    statuses: Mapping[str, str],
    proposals: Mapping[str, Mapping[str, Any]],
    aliases: Mapping[str, str],
    old_inbox: Mapping[str, str],
) -> list[tuple[str, str]]:
    """The two decided candidates, chosen deterministically: by id, undecided on both sides, their own survivor that
    absorbed nobody, with a CURRENT ``proposed`` proposal that is not a KEEP (so the accept changes the status). The
    first is accepted, the second overridden to a verdict that changes its status (WATCH, or REJECT for a WATCH)."""
    targets = {s for a, s in aliases.items() if a != s}
    picked = [
        cid
        for cid in sorted(statuses)
        if statuses[cid] == "new"
        and old_inbox.get(cid) == "new"
        and cid not in targets
        and aliases.get(cid, cid) == cid
        and (proposals.get(cid) or {}).get("status") == "proposed"
        and (proposals.get(cid) or {}).get("proposal") in ("RESEARCH", "WATCH", "REJECT")
    ][:2]
    if len(picked) < 2:
        raise SystemExit("the real snapshot has fewer than two decidable candidates")
    first, second = picked
    other = "WATCH" if proposals[second]["proposal"] != "WATCH" else "REJECT"
    return [(first, str(proposals[first]["proposal"])), (second, other)]


def real() -> int:  # pragma: no cover - for the main session: needs the hosted database and the old repository
    """The plan's "Real snapshot" check: the real data folder (READ ONLY: captured once, bytes only) imported by the
    PRODUCTION importer into a throw-away ``pz_rehearse_*`` schema, against the OLD code over a byte-exact scratch copy
    of the same bytes. Step 0 writes nothing: the imported view (``proposals`` / ``counts`` / ``calibration`` /
    ``pending``) against the old ``view()``, with 0 new lines. Then one ACCEPT and one OVERRIDE on two candidates
    chosen by ``real_choice``, compared after each step through ``normalise`` (the real merge aliases; a carried
    proposal of review 009 expected with the old absorbed machine value): the answer, the log lines, those candidates'
    decision and notes, the view. ``model_ledger`` must not change, and no table but ``candidates``,
    ``candidate_events`` and ``triage_decisions``. Aggregates only are printed (no name, no id)."""
    import secrets as _secrets

    from fastapi.testclient import TestClient
    from psycopg.rows import dict_row

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
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
    files = {f.path: f.raw for f in snapshot.files()}
    old_inbox = {
        str(c["id"]): str(c.get("decision"))
        for c in (snapshot.json("inbox.json") or {}).get("candidates", [])
        if isinstance(c, dict) and c.get("id")
    }
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
        with transaction(settings.db_url) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"select alias_id, candidate_id from {schema}.candidate_aliases where namespace = 'candidate'".encode()
            )
            aliases = {str(r["alias_id"]): str(r["candidate_id"]) for r in cur.fetchall()}
            cur.execute(f"select id, status from {schema}.candidates".encode())
            statuses = {str(r["id"]): str(r["status"]) for r in cur.fetchall()}
            cur.execute(
                f"select candidate_id, proposal, status from {schema}.triage_proposals where is_current".encode()
            )
            current = {str(r["candidate_id"]): r for r in cur.fetchall()}
            before_tables = _fingerprint(conn, schema)
        picks = real_choice(statuses, current, aliases, old_inbox)
        steps: list[dict[str, Any]] = [{"clock": REAL_CLOCK.isoformat(), "op": "view", "body": {}}]
        for i, (cid, verdict) in enumerate(picks, start=1):
            mode = "accept" if i == 1 else "override"
            steps.append({"clock": REAL_CLOCK.replace(minute=i).isoformat(), "op": "decide",
                          "body": {"id": cid, "verdict": verdict, "mode": mode, "expected_status": "new"}})  # fmt: skip
        out = oracle_files(files, aliases, steps)
        if out.get("blocked"):
            problems.append(f"/blocked: the OLD code wrote outside its scratch folder ({len(out['blocked'])})")
        archived = [e for e in view.decisions(out["steps"][0]["log"]) if e.get("candidate_id")]
        report["archived_lines"] = len(archived)
        report["archived_distinct_recorded"] = len({e["candidate_id"] for e in archived})
        report["archived_distinct_survivors"] = len(
            {aliases.get(e["candidate_id"], e["candidate_id"]) for e in archived}
        )
        report["archived_absorbed_ids"] = sum(
            1 for e in archived if aliases.get(e["candidate_id"], e["candidate_id"]) != e["candidate_id"]
        )
        report["aliases_merged"] = sum(1 for a, s in aliases.items() if a != s)
        report["picked_verdicts"] = [f"{s['body']['mode']} {s['body']['verdict']}" for s in steps[1:]]
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        chosen = [cid for cid, _ in picks]
        before: Mapping[str, Any] = {"log": out["steps"][0]["log"], "inbox": [], "view": {"proposals": {}}}
        new: dict[str, Any] = {}
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            for i, (step, old) in enumerate(zip(steps, out["steps"], strict=True)):
                clock = datetime.fromisoformat(step["clock"]).replace(tzinfo=BERLIN)
                app.state.clock = functools.partial(lambda c: c, clock)
                response = None
                if step["op"] == "decide":
                    response = client.post("/api/deal-flow/triage/decide", json=step["body"])
                with transaction(settings.db_url) as conn:
                    new = new_state(client, conn, schema, response, keep_queue=True)
                carried: dict[str, tuple[str, Mapping[str, Any], bool]] = {}
                old_props, new_props = old["view"]["proposals"], new["view"]["proposals"]
                for oid in sorted(a for a, s in aliases.items() if a != s and a in old_props):
                    sid = aliases[oid]
                    if sid not in old_props and sid in new_props and sid not in carried:
                        carried[sid] = (oid, new_props[sid], statuses.get(sid) == "new" and sid not in chosen[:i])
                want = normalise(old, before, step["body"], step["op"], aliases, carried)
                want["candidates"] = {k: v for k, v in want["candidates"].items() if k in chosen}
                new["candidates"] = {k: v for k, v in new["candidates"].items() if k in chosen}
                diffs = diff(js(want), js(new), f"/step{i}")
                problems += diffs
                n_added = len(want["log"]) - len(_lines(before["log"]))
                print(json.dumps({"step": i, "op": step["op"], "status": None if response is None else response.status_code,
                                  "answer": {k: v for k, v in (new["answer"] or {}).items() if k != "status"},
                                  "new_lines": n_added, "log_lines": len(new["log"]), "proposals": len(new_props),
                                  "carried": len(carried), "calibration_decisions": new["view"]["calibration"]["decisions"],
                                  "case_prep_calls": len(old["case_prep"]), "differences": len(diffs)}, ensure_ascii=False))  # fmt: skip
                if i == 0 and n_added:
                    problems.append("/step0: the read wrote a line")
                before = old
        with transaction(settings.db_url) as conn:
            after_tables = _fingerprint(conn, schema)
        changed = sorted(
            k for k in set(before_tables) | set(after_tables) if before_tables.get(k) != after_tables.get(k)
        )
        report["tables_changed"] = changed
        if not set(changed) <= WRITABLE:
            problems.append(f"/tables: unexpected tables changed {sorted(set(changed) - WRITABLE)}")
        if before_tables.get("model_ledger") != after_tables.get("model_ledger"):
            problems.append("/model_ledger: changed")
        report["decisions_after"] = sorted(new["candidates"][c]["decision"] for c in chosen)
    finally:
        admin.close()
        drop_schema(settings.db_url, schema)
    print(json.dumps(report, ensure_ascii=False))
    shapes = Counter(re.sub(r"/(proposals|candidates|pending)/[^/:]+", r"/\1/<id>", d.split(":")[0]) for d in problems)
    for shape, n in shapes.most_common(40):
        print(f"  DIFF {shape} x{n}")  # path shapes only: never a real id, name or value
    print("TRIAGE DECIDE REAL PARITY PASSED" if not problems else f"TRIAGE DECIDE REAL PARITY FAILED ({len(problems)})")
    return 1 if problems else 0


# ------------------------------------------------------------------ goldens / check
def _summary(golden: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for step, old in zip(golden["input"]["steps"], golden["expected"]["steps"], strict=True):
        out.append({"op": step["op"], "answer": old.get("answer") or {"error": old.get("error")},
                    "case_prep": len(old["case_prep"]), "log_lines": len(_lines(old["log"]))})  # fmt: skip
    return out


def write_goldens() -> int:
    inp = world_input()
    out = oracle(inp)
    meta = out.pop("meta")
    golden = {"provenance": {**meta, "clock0": CLOCK0.isoformat()}, "input": inp, "expected": out}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    if out.get("blocked"):
        print("BLOCKED WRITES in the oracle:", out["blocked"])
        return 1
    for row in _summary(golden):
        print(json.dumps(row, ensure_ascii=False))
    problems = compare_pure(golden)
    for p in problems[:60]:
        print("  DIFF", p)
    print("TRIAGE DECIDE GOLDENS MATCH" if not problems else f"TRIAGE DECIDE GOLDENS DIFFER ({len(problems)})")
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
    print("TRIAGE DECIDE CHECK PASSED" if not problems else f"TRIAGE DECIDE CHECK FAILED ({len(problems)})")
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
