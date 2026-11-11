"""Feedback-ledger parity: decisions as events against the OLD ``record_decision`` as oracle (review 008).

    python -m projectzero.ops.parity_feedback goldens   # (re)generate golden_v1/oracle_feedback_write.json

The oracle (``scripts/oracle/feedback_write_oracle.py``) replays a decision script on the OLD write path in the old
interpreter with a scratch ``PZ_DATA``. The new side replays the same script the way ``DealFlowStore.decide`` records it
(an event with a decision snapshot, none for an unchanged status) and rebuilds the effective ledger with
``ranking.ledger``. After EVERY step the decision rows, their order, the per-source table and each probe candidate's
feedback must be equal.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from projectzero.dealflow.ranking import feedback, ledger
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = Path(__file__).resolve().parents[4] / "scripts" / "oracle" / "feedback_write_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_feedback_write.json"


def _c(cid: str, name: str, *sources: str, **extra: Any) -> dict[str, Any]:
    c: dict[str, Any] = {"id": cid, "name": name, **extra}
    if sources:
        c["source_id"] = sources[0]
        if len(sources) > 1:
            c["all_source_ids"] = list(sources)
    return c


def _vote(sids: list[str], decision: str, name: str) -> dict[str, Any]:
    return {"source_ids": sids, "decision": decision, "name": name, "ts": "2026-11-01 10:00:00", "by": "Mohamed"}


def corpus() -> dict[str, Any]:
    """An imported ledger plus a decision script that walks every rule of the old write path."""
    base = {
        "version": 2, "label": feedback.LABEL, "history": [],
        "decisions": {
            "imp-1": _vote(["src-a"], "rejected", "Imported One"),
            "imp-2": _vote(["src-a"], "kept", "Acme GmbH"),
            "imp-3": _vote(["src-a"], "research", "Imported Three"),
            "imp-4": _vote(["src-a", "src-b"], "watch", "Imported Four"),
            "imp-5": _vote(["src-c"], "kept", "Acme GmbH"),
        },
        "omar": {
            "acme": {"source_ids": ["src-a", "src-c"], "outcome": "positive", "company": "Acme GmbH",
                     "candidate_id": ""},
            "linked": {"source_ids": ["src-b"], "outcome": "negative", "company": "Linked", "candidate_id": "imp-4"},
        },
    }  # fmt: skip
    cands = {
        "imp-1": _c("imp-1", "Imported One", "src-a"),
        "imp-2": _c("imp-2", "Acme GmbH", "src-a"),
        "imp-3": _c("imp-3", "Imported Three", "src-a"),
        "imp-4": _c("imp-4", "Imported Four", "src-a", "src-b"),
        "new-5": _c("new-5", "Fifth Co", "src-a"),
        "new-6": _c("new-6", "Sixth Co", "src-a", "src-b"),
        "new-7": _c("new-7", "No Source Co"),
        "b-1": _c("b-1", "B One", "src-b"),
        "b-2": _c("b-2", "B Two", "src-b"),
        "b-3": _c("b-3", "B Three", "src-b"),
        "b-4": _c("b-4", "B Four", "src-b"),
    }
    seen_also = _c("new-6", "Sixth Co", "src-a", also_seen=[{"source_id": "src-d"}])
    steps = [
        ("new-5", "kept", None),  # src-a reaches 5 unique reviewed companies -> active
        ("new-6", "research", None),  # several sources
        ("imp-1", "kept", None),  # an imported vote replaced, in place
        ("imp-2", "new", None),  # undo of an imported vote: removed (the Omar "acme" link moves to imp-5)
        ("new-7", "kept", None),  # no source ids: nothing recorded
        ("imp-3", "new", _c("imp-3", "Imported Three")),  # undo with no sources: the imported vote stays
        ("new-5", "new", _c("new-5", "Fifth Co")),  # undo with no sources: the earlier event's vote stays
        ("new-6", "baseline", None),  # baseline removes
        ("b-1", "kept", None), ("b-2", "kept", None), ("b-3", "kept", None), ("b-4", "kept", None),  # cap +3
        ("imp-2", "rejected", None),  # re-added: moves to the end (the "acme" link stays on imp-5)
        ("imp-1", "kept", None),  # identical status: one vote, no event on the new side
        ("new-6", "watch", seen_also),  # provenance via also_seen at decision time
        ("imp-4", "rejected", None),  # the linked Omar outcome and the decision stay one company
    ]  # fmt: skip
    script = [{"candidate": c or cands[cid], "decision": d} for cid, d, c in steps]
    return {"base": base, "steps": script, "probes": list(cands.values())}


def run_oracle(data: dict[str, Any]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-fb-oracle-") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "data").mkdir()
        src, dst = tmpdir / "in.json", tmpdir / "out.json"
        src.write_text(json.dumps(data), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(tmpdir / "data"), "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)
        run = subprocess.run([str(python), str(ORACLE), str(src), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


def run_new(data: dict[str, Any]) -> list[dict[str, Any]]:
    """The script as DealFlowStore.decide records it: an event per CHANGED status, with the decision snapshot."""
    status: dict[str, str] = {cid: e["decision"] for cid, e in (data["base"] or {}).get("decisions", {}).items()}
    events: list[dict[str, Any]] = []
    out = []
    for step in data["steps"]:
        c, decision = step["candidate"], step["decision"]
        if status.get(c["id"], "new") != decision:  # an unchanged status writes no event (one vote)
            rec = ledger.decision_record(c, decision, [c["id"]])
            events.append({"candidate_id": c["id"], "detail": {"feedback": rec}, "at": "2026-11-11 12:00:00"})
            status[c["id"]] = decision
        d = feedback.normalize(ledger.effective(data["base"], events))
        table = feedback.table(d)
        out.append({
            "decision_keys": list(d["decisions"]),
            "decisions": {k: {f: v for f, v in e.items() if f != "ts"} for k, e in d["decisions"].items()},
            "table": table,
            "probes": {p["id"]: feedback.for_candidate(p, table) for p in data["probes"]},
        })  # fmt: skip
    return out


def compare(oracle_steps: list[dict[str, Any]], new_steps: list[dict[str, Any]]) -> list[str]:
    problems = [] if len(oracle_steps) == len(new_steps) else [f"steps: {len(oracle_steps)} vs {len(new_steps)}"]
    for i, (o, n) in enumerate(zip(oracle_steps, new_steps, strict=False)):
        old = {k: o[k] for k in ("decision_keys", "decisions", "table", "probes")}
        problems += [f"step {i}" + d for d in diff(old, js(n))]
    return problems


def write_goldens() -> int:
    data = corpus()
    oracle = run_oracle(data)
    problems = compare(oracle["steps"], run_new(data))
    golden = {"provenance": oracle["meta"], "corpus": data, "expected": oracle["steps"]}
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"feedback-write goldens written: {len(oracle['steps'])} steps; new code differences: {len(problems)}")
    for p in problems[:40]:
        print("  DIFF", p)
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
