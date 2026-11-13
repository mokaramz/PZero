"""Review 032a, offline: the catalog is the old text cut by script (AST-checked), the port carries only the old
literals plus the declared new texts, and the pure System health reads match the OLD code's goldens
(``oracle_health.json``, ``python -m projectzero.ops.parity_health goldens``), key order included, with the declared
(c), (d), (e), (f), (g) and (k) normalised in ``parity_health.normalise``. Also: reads never write, the runner switch
restores the old texts, no job text promises a missing mechanism, the deferred subsystems, the status branches the
worlds cannot reach, the spend windows and the paid switch."""

from __future__ import annotations

import ast
import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from projectzero.health import RUNNER, HealthInputs, catalog, core, inputs_from_docs, overview_view, system_view
from projectzero.health import inputs_model as health_inputs
from projectzero.jobs.ported import NOT_PORTED, PORTED
from projectzero.jobs.ported import RUNNER as JOBS_RUNNER
from projectzero.ops import parity_health as ph
from projectzero.ops.parity_ranking import OLD_REPO

GOLDEN: dict[str, Any] = ph.read_golden()
OLD = OLD_REPO / "backend" / "src" / "projectzero"
HEALTH_PY = OLD / "services" / "health.py"
SCHEDULER_PY = OLD / "services" / "scheduler.py"
OVERVIEW_PY = OLD / "services" / "health_overview.py"
TOP = {
    HEALTH_PY: ["STALE_DAYS", "_ts", "_days", "REPAIR_RULES", "_EXTERNAL_CAUSES", "diagnose", "STALE_JOB_REPORT_H",
                "overall_status"],
    SCHEDULER_PY: ["STALE_RUNNING_H", "REPEATED_FAILURES", "OUTCOMES", "classify"],
    OVERVIEW_PY: ["HISTORY_DAYS", "run_state"],
}  # fmt: skip
NOW = datetime.fromisoformat(ph.CLOCK)
SYSTEM_KEYS = ["at", "verdict", "status", "issues", "sources", "coverage", "triage_pending", "research", "watch", "jobs",
               "overdue", "job_runner", "spend", "providers", "last_scan", "news", "build", "selfcheck",
               "source_discovery", "validation"]  # fmt: skip
OVERVIEW_KEYS = ["at", "jobs", "models", "pipeline", "backups", "integrity", "releases"]
PROMISES = ("retries automatically", "kept for retry", "run again when due", "starts them immediately",
            "next background trigger", "let catch-up run it", "handled automatically", "asleep")  # fmt: skip


def _inputs(name: str, now: datetime = NOW) -> HealthInputs:
    _fn, _clock, paid, key = ph.WORLDS[name]
    return inputs_from_docs(ph.as_read(ph.WORLDS[name][0]()), now.date(), now, paid=paid, keys={ph.KEY_ENV: key})


def _old(name: str, route: str = "system") -> dict[str, Any]:
    body: dict[str, Any] = GOLDEN["worlds"][name]["expected"][route]["ok"]
    return body


def _nodes(path: Path) -> dict[str, ast.stmt]:
    out: dict[str, ast.stmt] = {}
    for n in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            out[n.targets[0].id] = n
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            out[n.target.id] = n
        elif isinstance(n, ast.FunctionDef):
            out[n.name] = n
    return out


# ------------------------------------------------------------------ the cut catalog
@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_catalog_is_the_old_lines_cut_by_script() -> None:
    text = Path(catalog.__file__ or "").read_text(encoding="utf-8")
    ours = _nodes(Path(catalog.__file__ or ""))
    for path, names in TOP.items():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        old = _nodes(path)
        for name in names:
            node = old[name]
            assert "".join(lines[node.lineno - 1 : node.end_lineno]) in text, name  # the exact old lines
            assert ast.dump(ours[name]) == ast.dump(node), name  # the same syntax tree
    # one ``_ts`` serves both: the scheduler's is the same function
    assert ast.dump(_nodes(SCHEDULER_PY)["_ts"]) == ast.dump(_nodes(HEALTH_PY)["_ts"])


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_jobs_table_is_the_old_rows_without_the_runner() -> None:
    node = _nodes(SCHEDULER_PY)["JOBS"]
    assert isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.List)
    rows = []
    for elt in node.value.elts:
        assert isinstance(elt, ast.Dict)
        row: dict[str, Any] = {}
        for k, v in zip(elt.keys, elt.values, strict=True):
            assert isinstance(k, ast.Constant)
            if k.value != "run":
                row[k.value] = v.id if isinstance(v, ast.Name) else ast.literal_eval(v)
        rows.append(row)
    assert list(catalog.JOBS) == rows
    assert [j["id"] for j in core.active_jobs()] == [r["id"] for r in rows if r["id"] not in core.RETIRED_JOBS]
    assert len(core.active_jobs()) == 11 and set(core.LAST) == {r["last"] for r in rows if r["last"]}  # decision (c)


def _literals(path: Path) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}  # fmt: skip


@pytest.mark.skipif(not OLD.exists(), reason="the old repository is not checked out")
def test_the_port_carries_the_old_literals_unchanged() -> None:
    old: set[str] = set()
    for f in ("services/health.py", "services/health_overview.py", "services/scheduler.py", "services/news.py",
              "services/news_sources.py", "services/watch.py", "inference/ledger.py"):  # fmt: skip
        old |= _literals(OLD / f)
    allowed = {*core.NO_RUNNER_DO.values(), core.RULE1_DO, core.NO_RUNNER_UNKNOWN, core.NO_RUNNER_NO_REPORT,
               core.NO_RUNNER_SUFFIX, core.SELFCHECK_DEFERRED, core.LOCK_DEFERRED, core.BUILD_DEFERRED,
               core.SOURCE_DISCOVERY_DEFERRED, core.WATCH_CHECKS_DEFERRED, core.BACKUPS_DEFERRED,
               core.INTEGRITY_DEFERRED, core.RELEASES_DEFERRED, core.PAID_OFF_DO, *core.LAST, "deferred", "%Y-%m-%d %H:%M",
               "the Deal Flow registry could not be read",
               "availability", "deal_flow_scan", "triage_retry"}  # fmt: skip  # 032c (b) / (c)
    tree = ast.parse(Path(core.__file__ or "").read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)  # docstrings are commentary, not the old data
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr)}  # fmt: skip
    ours = {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs}  # fmt: skip
    assert sorted(v for v in ours if v not in old and v not in allowed) == []


def test_the_new_texts_are_revision_2s_table() -> None:
    assert {k: v for k, v in ph.NEW_DO.items() if k != 1} == core.NO_RUNNER_DO
    assert ph.NEW_DO[1] == core.RULE1_DO
    assert (core.NO_RUNNER_UNKNOWN, core.NO_RUNNER_NO_REPORT, core.NO_RUNNER_SUFFIX) == (
        ph.NEW_UNKNOWN, ph.NEW_NO_REPORT, ph.NEW_SUFFIX)  # fmt: skip
    assert RUNNER is core.RUNNER is JOBS_RUNNER  # 032c: the real runner replaced decision (k)'s None
    assert ph.PORTED_JOBS == PORTED and ph.NEW_NOT_PORTED == NOT_PORTED  # the parity restates them


# ------------------------------------------------------------------ the goldens
def test_provenance_and_inputs_are_current() -> None:
    assert GOLDEN["provenance"]["old_revision"] == "6c739b9cb6ca2517b845e381d39a36c50eccc59e"
    assert GOLDEN["provenance"]["old_dirty"] is False
    assert set(GOLDEN["worlds"]) == set(ph.WORLDS)
    for name, (fn, clock, paid, key) in ph.WORLDS.items():
        w = GOLDEN["worlds"][name]
        assert (w["clock"], w["paid"], w["key"]) == (clock, paid, key)
        # serialized without sort_keys: the documents' insertion order is part of the input
        assert json.dumps(w["docs"]) == json.dumps(json.loads(json.dumps(fn()))), name
        e = w["expected"]
        assert e["blocked"] == [] and e["changed"] == [] and e["skipped"] == {}, name  # the old reads wrote nothing
        assert set(e["held"]) <= {"save_json:radar_regions.json", "save_json:radar_sources.json"}, name
        assert "ok" in e["system"] and "ok" in e["overview"], name


def test_the_pure_reads_match_the_old_code_including_key_order() -> None:
    assert ph.compare_goldens(GOLDEN) == []


def test_with_a_runner_the_old_texts_and_groups_come_back_exactly() -> None:
    assert ph.compare_goldens(GOLDEN, runner=True) == []
    body = system_view(_inputs("jobs_unrun"), NOW, ph.StubRunner())
    assert body["verdict"] == _old("jobs_unrun")["verdict"] == "UNHEALTHY"
    assert body["status"] == _old("jobs_unrun")["status"]
    old_issues = [i for i in _old("jobs_unrun")["issues"] if ph.rule_of(i) != 1]
    assert [i for i in body["issues"] if ph.rule_of(i) != 1] == old_issues


def test_the_real_runner_restores_the_old_texts_only_for_the_ported_jobs() -> None:
    """032c decision (c): the per-job switch, against the goldens and on the jobs_unrun world."""
    assert ph.compare_goldens(GOLDEN, real=True) == []
    body = system_view(_inputs("jobs_unrun"), NOW, JOBS_RUNNER)
    labels = {j["id"]: j["label"] for j in catalog.JOBS}
    unported = {j["id"] for j in core.active_jobs()} - PORTED
    assert len(unported) == 4  # review 034a: the Deal Flow scan is ported; 035b: the triage retry
    for j in body["jobs"]:  # (b): the four unported jobs are never overdue and say so
        assert (j.get("availability") == NOT_PORTED) == (j["id"] in unported)
        assert not (j["overdue"] and j["id"] in unported)
    assert body["overdue"] == sum(1 for j in body["jobs"] if j["overdue"]) == 5  # 035b: triage_retry too
    for i in body["issues"]:
        named = {jid for jid in labels if labels[jid] in i["what"]}
        if ph.rule_of(i) in (6, 7, 8, 9, 10, 11) and named <= PORTED:  # the old guidance, old level and group
            assert i["do"] not in core.NO_RUNNER_DO.values(), i
        elif ph.rule_of(i) == 3:  # review 034a: the scan is ported, so rule 3 has its old advice back
            assert (i["level"], i["do"]) == ("warn", "Run Find New Candidates (or let catch-up run it)."), i
        elif ph.rule_of(i) == 4:  # review 035b: the triage retry is ported, so rule 4 has its old advice back
            assert i["do"].startswith("Retried automatically") and i["group"] == "auto", i
        elif ph.rule_of(i) in (6, 7, 8, 9, 10, 11):  # revision 2's wording for the others
            assert named <= unported and (i["level"], i["group"]) == ("info", "info"), i
            assert i["do"] in core.NO_RUNNER_DO.values() and not [p for p in PROMISES if p in i["do"]], i
        if ph.rule_of(i) == 1:
            assert i["do"] == core.RULE1_DO  # rule 1 never regains the repair research job
    assert body["job_runner"]["lock"] == {"held": False}  # the runner's lock exists with the runner
    assert {j["id"]: j["state"] for j in body["jobs"]}["validation_snapshot"] == "interrupted"  # no live claim


def test_a_running_record_is_alive_only_under_the_lock_holders_generation() -> None:
    docs = ph.unrun_world(False)
    docs["schedule/jobs.json"] = {**docs["schedule/jobs.json"],
                                  "event_scan": {"state": "running", "pid": 7, "generation": 5, "started": "2026-11-13T08:59:00"}}  # fmt: skip
    inputs = inputs_from_docs(docs, NOW.date(), NOW)
    held = {j["id"]: j for j in core.plan(inputs, NOW, JOBS_RUNNER.holding(5))}
    assert held["event_scan"]["state"] == "running" and not held["event_scan"]["overdue"]
    for runner in (JOBS_RUNNER.holding(6), JOBS_RUNNER):  # a larger generation took over / nobody holds the lock
        row = {j["id"]: j for j in core.plan(inputs, NOW, runner)}["event_scan"]
        assert row["state"] == "interrupted" and row["overdue"]


def test_the_goldens_cover_the_planned_cases() -> None:
    worlds = GOLDEN["worlds"]
    rows = [r for n in worlds for r in _old(n)["sources"]["sources"]]
    assert {r["state"] for r in rows} == {"FAILING", "NEVER_SUCCESSFUL", "STALE", "DEGRADED", "NEVER_RUN", "HEALTHY",
                                          "DISABLED"}  # fmt: skip
    causes = {r["repair"]["cause"] for r in rows if "repair" in r}
    assert causes == {c for _rx, c, _fix in catalog.REPAIR_RULES} | {"unknown error", "no error recorded"}
    assert any(r["repair"].get("bridge_job") for r in rows if "repair" in r)  # (c): an old research job, dropped
    assert any(r["noise_rate"] is not None for r in rows)
    whats = {n: [i["what"] for i in _old(n)["issues"]] for n in worlds}
    assert "no Deal Flow scan in over 10 days" in whats["limited"] and "no Deal Flow scan yet" in whats["empty"]
    assert not any("Deal Flow scan" in w and "no " in w for w in whats["healthy"])  # 10 days and 3 h: not over 10
    jobs = [j for n in worlds for j in _old(n)["jobs"]]
    assert {"ok", "failed", "interrupted", "never_run"} <= {j["state"] for j in jobs}
    assert {"completed", "no_findings", "partial", "failed", "budget_blocked", "waiting_external"} <= {
        j["outcome"] for j in jobs}  # fmt: skip
    assert any(j["fails_in_row"] >= 2 for j in jobs) and any(j["overdue"] for j in jobs)
    assert [j for j in jobs if j["id"] in core.RETIRED_JOBS] == []  # the oracle never planned them
    spend = {n: _old(n)["spend"]["month"] for n in worlds}
    assert spend["attention"] == 0.8 * 25 and spend["main"] > 20 and spend["healthy"] < 20
    assert any(p["key"] is False for p in _old("main")["providers"])
    assert _old("main")["validation"]["data_issues"] and _old("healthy")["validation"]["data_issues"] == 0
    assert {n: _old(n)["verdict"] for n in ("main", "attention", "healthy")} == {
        "main": "UNHEALTHY", "attention": "NEEDS ATTENTION", "healthy": "HEALTHY"}  # fmt: skip
    new = {n: ph.normalise(worlds[n]["expected"])["system"]["ok"] for n in worlds}
    assert {n: (b["verdict"], b["status"]["key"]) for n, b in new.items()} == {
        "main": ("UNHEALTHY", "action"), "attention": ("NEEDS ATTENTION", "action"),
        "limited": ("FYI — EXTERNAL LIMITATIONS", "limited"), "healthy": ("HEALTHY", "ok"),
        "jobs_unrun": ("NEEDS ATTENTION", "action"), "jobs_only": ("FYI — EXTERNAL LIMITATIONS", "unknown"),
        "empty": ("FYI — EXTERNAL LIMITATIONS", "unknown")}  # fmt: skip
    history = _old("main", "overview")["jobs"]
    assert any(r["job"] == "*" and r["state"] == "skipped" for r in history["runs"])
    assert history["runs"][0]["at"] == "2026-10-14T09:00:00"  # the line before the window is left out
    assert any(len(r["note"]) == 400 for r in history["runs"])
    models = _old("main", "overview")["models"]
    assert (
        len(models["rows"]) == 4
        and "2026-10-14" in models["spend_by_day"]
        and "2026-10-01" not in models["spend_by_day"]
    )
    assert _old("main", "overview")["pipeline"]["intake"]  # (c): an old count, dropped
    assert _old("empty", "overview")["jobs"] == {"days": 30, "runs": [], "outcomes_recorded_since": None}


def test_the_revision_2_worlds() -> None:
    unrun = system_view(_inputs("jobs_unrun"), NOW, None)
    assert unrun["status"]["label"] == "Action required"
    assert unrun["status"]["sentence"].startswith("1 item needs you")  # only the failing source counts
    assert unrun["status"]["groups"]["need"] == 1 and unrun["status"]["groups"]["auto"] == 0
    assert {j["id"]: j["state"] for j in unrun["jobs"]}["validation_snapshot"] == "interrupted"  # (e)
    only = system_view(_inputs("jobs_only"), NOW, None)
    assert only["status"]["key"] == "unknown" and only["status"]["label"] == "Status unknown"
    assert only["status"]["sentence"] == core.NO_RUNNER_UNKNOWN.format(at="2026-11-10 22:00")
    empty = system_view(_inputs("empty"), NOW, None)
    assert empty["status"]["key"] == "unknown" and empty["status"]["sentence"] == core.NO_RUNNER_NO_REPORT
    assert empty["status"]["last_job_report"] == "" and "20" not in empty["status"]["sentence"]  # no timestamp
    for body in (unrun, only, empty, system_view(_inputs("main"), NOW, None)):
        texts = [body["status"]["sentence"], *(i["what"] + " " + i["do"] for i in body["issues"])]
        assert not [t for t in texts for p in PROMISES if p in t], texts
        assert all(i["group"] in ("need", "ext", "info") for i in body["issues"])  # nothing counts as automatic


# ------------------------------------------------------------------ purity, payload shape, deferrals
def test_reads_never_write_and_never_mutate_their_inputs() -> None:
    docs = ph.main_docs()
    before = copy.deepcopy(docs)
    inputs = inputs_from_docs(ph.as_read(docs), NOW.date(), NOW)
    snapshot = copy.deepcopy(inputs)
    system_view(inputs, NOW)
    overview_view(inputs, NOW)
    system_view(inputs, NOW, ph.StubRunner())
    assert docs == before and inputs == snapshot


def test_the_payload_key_order_and_the_deferred_subsystems() -> None:
    body, ov = system_view(_inputs("main"), NOW, None), overview_view(_inputs("main"), NOW)
    assert list(body) == SYSTEM_KEYS and list(ov) == OVERVIEW_KEYS
    assert list(ov["pipeline"]) == ["inbox", "routing", "conviction", "manager_sent"]  # no ``intake`` (c)
    for value in (body["build"], body["selfcheck"], body["source_discovery"], body["job_runner"]["lock"],
                  body["watch"]["failing_checks"], ov["backups"], ov["integrity"], ov["releases"]):  # fmt: skip
        assert list(value) == ["deferred"] and isinstance(value["deferred"], str) and value["deferred"]
    assert all("bridge_job" not in r.get("repair", {}) for r in body["sources"]["sources"])
    assert [p["role"] for p in body["providers"]] == ["CHEAP", "STANDARD", "ESCALATION"]  # no RESEARCH (029a h)
    assert body["job_runner"]["outcomes"] == catalog.OUTCOMES


def test_an_imported_running_job_is_interrupted_without_a_runner() -> None:
    docs = ph.unrun_world(False)
    recent = {"state": "running", "started": "2026-11-13T08:30:00", "note": ""}  # no pid, 30 min old
    docs["schedule/jobs.json"] = {**docs["schedule/jobs.json"], "case_refresh": recent}
    inputs = inputs_from_docs(docs, NOW.date(), NOW)
    plan = {j["id"]: j for j in core.plan(inputs, NOW, None)}
    assert plan["case_refresh"]["state"] == "interrupted" and plan["case_refresh"]["overdue"]  # (e)
    with_runner = {j["id"]: j for j in core.plan(inputs, NOW, ph.StubRunner())}
    assert with_runner["case_refresh"]["state"] == "running" and not with_runner["case_refresh"]["overdue"]  # 2 h rule
    assert with_runner["validation_snapshot"]["state"] == "interrupted"  # its pid is gone


def test_the_status_branches_the_worlds_cannot_reach() -> None:
    old = (NOW - timedelta(hours=30)).isoformat(timespec="seconds")
    warn = {"level": "warn", "what": "DEGRADED: an invented part", "do": "", "group": "need"}
    degraded = core.status_of("DEGRADED", [warn], old, NOW, None)
    assert degraded["key"] == "degraded" and degraded["sentence"].endswith(core.NO_RUNNER_SUFFIX)
    assert core.status_of("DEGRADED", [warn], old, NOW, ph.StubRunner())["sentence"].endswith(
        " No background job has reported for 30 h.")  # fmt: skip
    auto = [{"level": "info", "what": "x", "do": "", "group": "auto"}]
    fresh = (NOW - timedelta(hours=1)).isoformat(timespec="seconds")
    limited = core.status_of("FYI — EXTERNAL LIMITATIONS", auto, fresh, NOW, ph.StubRunner())
    assert limited["sentence"].endswith("1 item handled automatically.")
    assert core.status_of("HEALTHY", [], "not a time", NOW, None)["sentence"] == core.NO_RUNNER_NO_REPORT
    for verdict, issues, report in (("DEGRADED", [warn], old), ("FYI — EXTERNAL LIMITATIONS", auto, fresh),
                                    ("HEALTHY", [], ""), ("UNHEALTHY", [warn], old)):  # fmt: skip
        assert core.status_of(verdict, issues, report, NOW, ph.StubRunner()) == catalog.overall_status(
            verdict, issues, report, NOW)  # fmt: skip


def test_the_spend_windows_are_the_old_naive_berlin_windows() -> None:
    def old_spend(items: list[dict[str, Any]], now: datetime) -> dict[str, float]:  # the old ``ledger.spend``
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week0, month0 = day0 - timedelta(days=day0.weekday()), day0.replace(day=1)
        out = {"day": 0.0, "week": 0.0, "month": 0.0, "all_time": 0.0}
        for e in items:
            v = float(e.get("usd") or 0.0)
            if not v:
                continue
            out["all_time"] += v
            try:
                t = datetime.strptime(str(e.get("ts")), "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                continue
            out["day"] += v if t >= day0 else 0.0
            out["week"] += v if t >= week0 else 0.0
            out["month"] += v if t >= month0 else 0.0
        return {k: round(v, 6) for k, v in out.items()}

    ledger = [{"ts": t, "usd": 0.1 * (i + 1)} for i, t in enumerate((
        "2026-10-25T02:30:00", "2026-10-25T00:00:00", "2026-10-24T23:59:59", "2026-10-19T00:00:00",
        "2026-10-18T23:59:59", "2026-10-01T00:00:00", "2026-09-30T23:59:59", "2026-10-26T10:00:00", "garbage"))]  # fmt: skip
    for now in (datetime(2026, 10, 25, 2, 30), datetime(2026, 10, 25, 23, 0), datetime(2026, 10, 1, 0, 0)):
        got = core.spend_summary(HealthInputs(ledger=ledger), now)["spend"]
        assert got == old_spend(ledger, now), now


def test_the_paid_switch_and_the_key_are_presence_only() -> None:
    off = system_view(HealthInputs(paid=False, keys={ph.KEY_ENV: True}), NOW)
    assert off["spend"]["kill_switch"] == "PZ_AI_PAID"  # (f): off unless PZ_AI_PAID is exactly ``on``
    assert "paid AI is switched off (PZ_AI_PAID)" in [i["what"] for i in off["issues"]]
    on = system_view(HealthInputs(paid=True, keys={ph.KEY_ENV: True}), NOW)
    assert on["spend"]["kill_switch"] is None
    assert [p["key"] for p in on["providers"]] == [True, True, None]
    missing = system_view(HealthInputs(paid=True), NOW)
    assert [p["key"] for p in missing["providers"]] == [False, False, None]
    assert "an AI provider key is missing for machine triage / analysis" in [i["what"] for i in missing["issues"]]


def test_the_adapter_reads_like_the_old_loaders() -> None:
    empty = inputs_from_docs({}, NOW.date(), NOW)
    assert empty.runs == [] and empty.ledger == [] and empty.job_state == {} and empty.sources == []
    assert empty.coverage is not None and empty.triage_next_try is None
    lines = (
        '{"at": "2026-11-12T10:00:00", "job": "x"}\n\n{"torn": \n[1, 2]\n{"at": "2026-11-12T11:00:00", "job": "y"}\n'
    )
    assert [r["job"] for r in health_inputs.dict_lines(lines)] == ["x", "y"]
    assert health_inputs.next_try({"a": {"next_eligible": "2026-11-13T10:00:00"}, "b": {"next_eligible": None},
                                   "c": {"next_eligible": "2026-11-13T09:30:00"}, "d": "junk"}) == "2026-11-13T09:30:00"  # fmt: skip
    unreadable = inputs_from_docs({"sources.json": ph.UNREADABLE, "schedule/jobs.json": ph.UNREADABLE}, NOW.date(), NOW)
    assert unreadable.sources == [] and unreadable.job_state == {}  # tolerant, as before
    assert core.coverage_summary(HealthInputs(coverage=None), NOW) == {"available": False,
                                                                       "error": "temporarily unavailable"}  # fmt: skip
