# ruff: noqa: E501
# (the cases: one record per line)
"""Background-jobs runner parity: the NEW runner against the OLD ``services/scheduler.py`` as oracle, over FAKE jobs
with a FIXED clock (review 032c).

    python -m projectzero.ops.parity_jobs goldens   # (re)generates golden_v1/oracle_jobs.json (needs the old repo)
    python -m projectzero.ops.parity_jobs check     # the pure parts against the stored golden (no oracle, no database)
    python -m projectzero.ops.parity_jobs hosted    # the new runner over the same fake jobs in scratch schemas

The oracle (``scripts/oracle/jobs_oracle.py``) runs each case's steps through the old ``run_due`` / ``plan`` /
``dry_run`` / ``recover_on_start`` / ``failing_jobs`` / CLI ``--background [--dry-run]`` over a scratch data folder
holding the case's files, and records every step's answer and the three state files after it. ``hosted`` imports the
same files with the PRODUCTION importer into a throw-away ``pz_itest_*`` schema, runs the same steps through the new
runner (``jobs.runner`` / ``python -m projectzero.jobs``), and compares, step by step: the answer, the ``job_state``
records (``detail``), the history lines (``job_runs.detail`` in order) and the runner records (the ONE overlay
reader), the latter also as serialized text (key order). ``check`` compares ``classify`` over the stored notes and the
plan of each case's initial state through the pure ``health.core.plan``.

Declared differences, ALL applied by ``normalise``:

* **(a) the lock.** The old ``schedule/run.lock`` (a pid and a token, broken when its pid is dead) is a session
  advisory lock with a fencing generation: a job record claimed by the new runner carries ``"generation"`` (dropped
  here); a busy run's note names the lease's holder (its ``since`` where the old one named the lock file's
  ``started``); a held lock is always alive. Every ``pid`` is the running process's, so pids are ``<pid>`` on both
  sides. ``hold_lock`` is another runner holding the lock (the old side: a live pid in ``run.lock``; the new side:
  the advisory lock taken by a second session).
* **(e) the backup.** The old ``--background`` made a background backup when something was overdue (stubbed "not
  made" in the oracle, so it printed nothing); the new runner has none. The old CLI appended its summary line to
  ``schedule/background.log``; the new CLI prints it: the old log lines are compared after the old stdout.
* **The CLI's first dry-run line** names the old data folder / the new schema: both are ``<where>``.

The cases hold INVENTED names only. Exit 1 on any difference.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.health import core as health_core
from projectzero.health.catalog import OUTCOMES, classify
from projectzero.health.inputs_model import inputs_from_docs
from projectzero.jobs.ported import RUNNER as JOBS_RUNNER
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "jobs_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_jobs.json"
CLOCK = "2026-11-13T09:00:00"
MARKERS: dict[str, Any] = {"inbox.json": {"candidates": []}, "real_data.json": {"signals": []}}


# ------------------------------------------------------------------ the cases (invented names only)
# fmt: off
def job(jid: str, *notes: str, interval_h: float = 24) -> dict[str, Any]:
    return {"id": jid, "label": jid.replace("_", " ").capitalize(), "interval_h": interval_h, "notes": list(notes)}


def case(name: str, jobs: list[dict[str, Any]], steps: list[dict[str, Any]], clock: str = CLOCK, **docs: Any) -> dict[str, Any]:
    return {"name": name, "clock": clock, "jobs": jobs, "steps": steps, "docs": {**MARKERS, **{k.replace("__", "/").replace("_json", ".json").replace("_jsonl", ".jsonl"): v for k, v in docs.items()}}}


def cases() -> list[dict[str, Any]]:
    runner_json = {"background": {"at": "2026-11-12T22:00:00", "started": "2026-11-12T22:00:00", "finished": "2026-11-12T22:00:04", "outcome": "ok", "pid": 4242, "due": ["invented_old"], "note": "", "seconds": 4.0, "ran": 1, "failed": 0},
                   "app": {"at": "2026-11-12T08:00:00", "outcome": "skipped", "note": "skipped — another run is in progress (background, pid 4242, since 2026-11-12T07:59:00)"}}
    return [
        case("outcomes", [job("alpha_feed", "3 new things"), job("beta_feed", "0 new trigger(s) · 0 page(s) checked"),
                          job("gamma_feed", "!raise:provider exploded", "!raise:provider exploded", "1 new"),
                          job("delta_scan", "5 genuinely new · machine triage PARTIAL: 0 of 5 — budget_blocked: AI budget limit reached"),
                          job("epsilon_news", "PARTIAL · 3 new event(s) · 2 failed"), job("zeta_relay", "bridge off"),
                          job("eta_scan", "skipped — a scan is already running")],
             [{"op": "run_due", "source": "background"}, {"op": "plan"}, {"op": "run_due", "source": "app"},
              {"op": "failing_jobs"}, {"op": "advance", "clock": "2026-11-14T09:30:00"},
              {"op": "run_due", "source": "background"}, {"op": "failing_jobs"}, {"op": "plan"}]),
        case("missed", [job("daily_digest", "1 new"), job("weekly_digest", "2 new", interval_h=168)],
             [{"op": "plan"}, {"op": "run_due", "source": "background"}, {"op": "run_due", "source": "background"}, {"op": "plan"}],
             schedule__jobs_json={"daily_digest": {"state": "ok", "last_ok": "2026-11-03T09:00:00", "note": "1 new", "outcome": "completed"},
                                  "weekly_digest": {"state": "ok", "last_ok": "2026-11-10T09:00:00", "note": "2 new"}}),
        case("busy", [job("alpha_feed", "1 new")],
             [{"op": "hold_lock", "source": "background", "since": "2026-11-13T08:30:00"}, {"op": "run_due", "source": "app"},
              {"op": "dry_run"}, {"op": "release_lock"}, {"op": "run_due", "source": "app"}, {"op": "dry_run"}],
             schedule__runner_json=runner_json),
        case("interrupted", [job("alpha_feed", "1 new"), job("beta_feed", "2 new"), job("gamma_feed", "3 new")],
             [{"op": "plan"}, {"op": "recover_on_start"}, {"op": "plan"}, {"op": "run_due", "source": "background"}, {"op": "plan"}],
             schedule__jobs_json={"alpha_feed": {"state": "running", "pid": "DEAD", "started": "2026-11-13T07:00:00", "source": "background", "fails_in_row": 1},
                                  "beta_feed": {"state": "ok", "last_ok": "2026-11-13T08:00:00", "note": "2 new"},
                                  "gamma_feed": {"state": "running", "started": "2026-11-13T08:30:00", "note": "earlier note"}}),
        case("only", [job("a_job", "1 new"), job("b_job", "2 new"), job("c_job", "!raise:boom")],
             [{"op": "run_due", "source": "cli", "only": ["b_job"]}, {"op": "plan"}, {"op": "run_due", "source": "cli"}, {"op": "plan"}]),
        case("dry", [job("alpha_feed", "1 new"), job("beta_feed", "2 new")],
             [{"op": "dry_run"}, {"op": "plan"}],
             schedule__jobs_json={"beta_feed": {"state": "ok", "last_ok": "2026-11-13T08:00:00", "note": "2 new"}}),
        case("cli", [job("alpha_feed", "1 new"), job("beta_feed", "!raise:boom")],
             [{"op": "cli", "argv": ["--background", "--dry-run"]}, {"op": "cli", "argv": ["--background"]},
              {"op": "cli", "argv": ["--background"]}, {"op": "advance", "clock": "2026-11-15T10:00:00"},
              {"op": "cli", "argv": ["--background"]}, {"op": "plan"}],
             config_json={"catch_up": {"intervals_h": {"alpha_feed": 48}}}, schedule__runner_json=runner_json),
        case("disabled", [job("alpha_feed", "1 new")],
             [{"op": "cli", "argv": ["--background"]}, {"op": "dry_run"}],
             config_json={"catch_up": {"enabled": False}}),
    ]


CLASSIFY = [
    ["64 genuinely new · 15 baseline", True], ["0 new trigger(s) · 0 page(s) checked · 0 failure(s)", True],
    ["no new Scout 00 packet", True], ["nothing is waiting for a retry", True], ["PARTIAL · 11 new event(s) · 1 failed", True],
    ["64 genuinely new · machine triage PARTIAL: 0 of 67 — budget_blocked: real-provider call …", True],
    ["skipped — a scan is already running", True], ["skipped — already ran", True], ["weekend — no bridge hunt", True],
    ["failed: RuntimeError: boom", False], ["3 event(s) accepted · 0 source failure(s)", True], ["snapshot recorded", True],
    ["OK · 2 new event(s) · 1 updated · 3 already known · 4 feed(s) ok · 0 failed · $0.0000", True],
    ["weekly learning review recorded · news sources: 12 material events measured", True],
    ["12 material events · 0 lifecycle change(s) · 0 publication candidate(s) handed to the source network", True],
    ["skipped — a news refresh was already running", True],
]
# fmt: on


def files_of(docs: dict[str, Any]) -> dict[str, bytes]:
    return {
        k: (v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)).encode("utf-8")
        for k, v in docs.items()
    }


# ------------------------------------------------------------------ the oracle
def oracle(all_cases: list[dict[str, Any]]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-jobs-oracle-") as tmp:
        data = Path(tmp) / "data"
        for c in all_cases:
            folder = data / c["name"]
            folder.mkdir(parents=True)
            for rel, raw in files_of(c["docs"]).items():
                target = (folder / rel).resolve()
                if folder.resolve() not in target.parents:
                    raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
        srcf, dst = Path(tmp) / "in.json", Path(tmp) / "out.json"
        inp = {
            "cases": [{k: c[k] for k in ("name", "clock", "jobs", "steps")} for c in all_cases],
            "classify": CLASSIFY,
        }
        srcf.write_bytes(json.dumps(inp, ensure_ascii=False).encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if k != "SUPABASE_DB_URL" and not k.endswith(("_API_KEY", "_TOKEN"))}
        env.update({"PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")})
        res = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if res.returncode != 0:
            raise SystemExit(f"oracle failed:\n{res.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_bytes().decode("utf-8"))
        return out


# ------------------------------------------------------------------ the declared differences
_PID = re.compile(r"pid \d+")


def _pids(v: Any) -> Any:
    """Every ``pid`` value and ``pid NNN`` in a text is the running process's: ``<pid>`` (declared a)."""
    if isinstance(v, dict):
        return {k: ("<pid>" if k == "pid" and x is not None else _pids(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [_pids(x) for x in v]
    if isinstance(v, str):
        return _PID.sub("pid <pid>", v)
    return v


def _where(lines: list[str]) -> list[str]:
    return [re.sub(r"^DRY RUN — (data folder .+?|schema \S+) · ", "DRY RUN — <where> · ", x) for x in lines]


def normalise_step(step: dict[str, Any], *, old: bool) -> dict[str, Any]:
    s = copy.deepcopy(step)
    s.pop("runner_text", None)
    s["jobs"] = {k: {f: x for f, x in v.items() if f != "generation"} if isinstance(v, dict) else v
                 for k, v in s["jobs"].items()}  # fmt: skip  # (a): the claim's generation
    out = s.get("out")
    if s["op"] == "cli" and isinstance(out, dict):
        lines = _where(list(out["stdout"]) + (list(out.get("log") or []) if old else []))
        s["out"] = {"code": out["code"], "stdout": lines}
    if s["op"] == "dry_run" and isinstance(out, dict):
        s["out"] = {k: v for k, v in out.items() if k != "wrote"}  # the oracle's own write check
    result: dict[str, Any] = _pids(s)
    return result


def runner_text(step: dict[str, Any]) -> str:
    return str(_pids(json.loads(step["runner_text"])) if step.get("runner_text") else "")


# ------------------------------------------------------------------ check: the pure parts
def check(golden: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for note, ok, want in golden["classify"]:
        if classify(note, ok) != want:
            problems.append(f"/classify/{note}: {classify(note, ok)} != {want}")
    if golden["meta"]["outcomes"] != OUTCOMES:
        problems.append("/outcomes differ")
    by_name = {c["name"]: c for c in cases()}
    for got in golden["cases"]:
        c = by_name[got["name"]]
        first = next((i for i, s in enumerate(c["steps"]) if s["op"] in ("plan", "dry_run")), None)
        if first is None or any(s["op"] not in ("plan", "dry_run", "hold_lock") for s in c["steps"][:first]):
            continue  # only a plan of the INITIAL state is pure
        now = datetime.fromisoformat(c["clock"])
        docs = {**c["docs"]}
        jobs_doc = copy.deepcopy(docs.get("schedule/jobs.json") or {})
        docs["schedule/jobs.json"] = jobs_doc
        inputs = inputs_from_docs(docs, now.date(), now)
        rows = [{"id": j["id"], "label": j["label"], "interval_h": j["interval_h"], "last": None} for j in c["jobs"]]
        new = health_core.plan(inputs, now, JOBS_RUNNER.over(r["id"] for r in rows), rows)
        old_step = got["steps"][first]["out"]
        old_plan = old_step if c["steps"][first]["op"] == "plan" else old_step["due"] + old_step["not_due"]
        if c["steps"][first]["op"] == "dry_run":
            new = [p for p in new if p["overdue"]] + [p for p in new if not p["overdue"]]
        problems += [f"/{c['name']}/plan{p}" for p in diff({"plan": js(old_plan)}, {"plan": js(new)})]
    return problems


# ------------------------------------------------------------------ hosted: the new runner in scratch schemas
def _fake(spec: dict[str, Any]) -> Any:
    from projectzero.jobs.catalog import Job, JobContext

    notes = list(spec["notes"])
    calls = {"n": 0}

    def run(_ctx: JobContext) -> str:
        note = notes[min(calls["n"], len(notes) - 1)]
        calls["n"] += 1
        if note.startswith("!raise:"):
            raise RuntimeError(note[len("!raise:") :])
        return str(note)

    return Job(spec["id"], spec["label"], float(spec["interval_h"]), run, lambda conn, schema: None)


def new_case(db_url: str, c: dict[str, Any]) -> dict[str, Any]:
    from projectzero.core.config import Settings
    from projectzero.core.db import read_only_transaction
    from projectzero.jobs import __main__ as cli
    from projectzero.jobs import runner, store
    from projectzero.ops.scratch_import import drop_schema, import_world

    docs = copy.deepcopy(c["docs"])
    schema = import_world(db_url, docs)
    fake = [_fake(j) for j in c["jobs"]]
    rows = [j.row() for j in fake]
    cat = runner.catalog(fake)
    clock = [datetime.fromisoformat(c["clock"])]
    held: list[Any] = []
    steps = []
    old_env = os.environ.get("PZ_CATCHUP")
    os.environ["PZ_CATCHUP"] = "1"
    try:
        for step in c["steps"]:
            op = step["op"]
            out: Any = None
            now = clock[-1]
            if op == "run_due":
                out = runner.run_due(db_url, schema, source=step["source"], only=step.get("only"), now=now, jobs=fake,
                                     monotonic=lambda: 1000.0)  # fmt: skip
            elif op == "plan":
                with read_only_transaction(db_url) as conn:
                    out = runner.plan(conn, schema, now, cat, store.held_generation(conn, schema))
            elif op == "dry_run":
                out = runner.dry_run(db_url, schema, now=now, jobs=fake)
            elif op == "recover_on_start":
                out = runner.recover_on_start(db_url, schema, now=now)
            elif op == "failing_jobs":
                with read_only_transaction(db_url) as conn:
                    out = health_core.failing_jobs(runner.plan_inputs(conn, schema), rows)
            elif op == "hold_lock":
                lease = runner.acquire(db_url, schema, step["source"], datetime.fromisoformat(step["since"]))
                assert lease is not None
                held.append(lease)
            elif op == "release_lock":
                held.pop().release()
            elif op == "advance":
                clock.append(datetime.fromisoformat(step["clock"]))
            elif op == "cli":
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    code = cli.main(list(step["argv"]), settings=Settings(db_url=db_url, schema=schema), now=now,
                                    jobs=fake, monotonic=lambda: 1000.0)  # fmt: skip
                out = {"code": code, "stdout": buf.getvalue().splitlines()}
            with read_only_transaction(db_url) as conn:
                state = {"jobs": store.job_records(conn, schema), "runs": store.runs(conn, schema),
                         "runner": store.runner_records(conn, schema)}  # fmt: skip
            steps.append({"op": op, "out": js(out), **js(state),
                          "runner_text": json.dumps(state["runner"], ensure_ascii=False)})  # fmt: skip
    finally:
        for lease in held:
            lease.release()
        if old_env is None:
            os.environ.pop("PZ_CATCHUP", None)
        else:
            os.environ["PZ_CATCHUP"] = old_env
        drop_schema(db_url, schema)
    return {"name": c["name"], "steps": steps}


def hosted(golden: dict[str, Any]) -> int:  # pragma: no cover - needs the hosted database
    from projectzero.core.config import Settings

    settings = Settings.from_env()
    by_name = {c["name"]: c for c in cases()}
    problems: list[str] = []
    counts: dict[str, int] = {}
    for old_case in golden["cases"]:
        name = old_case["name"]
        if old_case.get("blocked"):
            problems.append(f"/{name}: the OLD runner wrote outside schedule/: {old_case['blocked']}")
        got = new_case(settings.db_url, by_name[name])
        counts[name] = len(got["steps"])
        for i, (o, n) in enumerate(zip(old_case["steps"], got["steps"], strict=True)):
            want, have = normalise_step(o, old=True), normalise_step(n, old=False)
            problems += [f"/{name}/{i}:{o['op']}{p}" for p in diff({"s": want}, {"s": have})]
            if runner_text(o) != runner_text(n):
                problems.append(f"/{name}/{i}:{o['op']}: the runner records' serialized text differs (key order)")
    print(json.dumps({"cases": counts, "steps": sum(counts.values())}, indent=1))
    for p in problems[:80]:
        print("  DIFF", p[:400])
    print(
        "JOBS HOSTED PARITY MATCH (0 differences)" if not problems else f"JOBS HOSTED PARITY DIFFER ({len(problems)})"
    )
    return 1 if problems else 0


# ------------------------------------------------------------------ entry points
def read_golden(path: Path = GOLDEN) -> dict[str, Any]:
    out: dict[str, Any] = json.loads(path.read_bytes().decode("utf-8"))
    return out


def write_goldens() -> int:
    all_cases = cases()
    out = oracle(all_cases)
    golden = {"provenance": out["meta"], "meta": out["meta"], "classify": out["classify"], "cases": out["cases"]}
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_bytes((json.dumps(golden, ensure_ascii=False, indent=None) + "\n").encode("utf-8"))
    return report(read_golden(), "JOBS GOLDENS")


def summary(golden: dict[str, Any]) -> dict[str, Any]:
    return {c["name"]: [f"{s['op']}:{len(s['runs'])} runs" for s in c["steps"]] for c in golden["cases"]}


def report(golden: dict[str, Any], label: str) -> int:
    problems = check(golden)
    blocked = [c["name"] for c in golden["cases"] if c.get("blocked")]
    print(json.dumps({"golden": str(GOLDEN), "bytes": GOLDEN.stat().st_size, "old": golden["provenance"]["old_revision"],
                      "classify": len(golden["classify"]), "summary": summary(golden), "blocked": blocked}, indent=1, ensure_ascii=False))  # fmt: skip
    for p in problems[:60]:
        print("  DIFF", p)
    print(f"{label} MATCH (0 differences)" if not problems and not blocked else f"{label} DIFFER ({len(problems)})")
    return 1 if problems or blocked else 0


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "check"
    if mode == "goldens":
        return write_goldens()
    if mode == "check":
        return report(read_golden(), "JOBS CHECK")
    if mode == "hosted":
        return hosted(read_golden())
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
