"""Triage view parity: ``GET /api/deal-flow/triage`` against the OLD ``triage_review.view()`` as oracle (review 009).

    python -m projectzero.ops.parity_triage goldens   # (re)generate tests/fixtures/golden_v1/oracle_triage.json
    python -m projectzero.ops.parity_triage real      # the real snapshot through a scratch import; exit 1 on any diff

The oracle (``scripts/oracle/triage_oracle.py``) runs in the OLD repository's interpreter and package, with ``PZ_DATA``
pointed at a temp folder that this module fills: the synthetic golden files, or a byte-exact copy of the captured
snapshot (``LegacySnapshot``) — the old data folder itself is only ever read. Besides the view it runs the pure rules
(routing, entity repair, portfolio check, candidate card) on given candidates and dumps their tables.

``real`` imports the SAME snapshot into a throw-away scratch schema with the production importer, runs the new view,
and compares, per candidate id after mapping the old ids to their survivors (``candidate`` merge aliases), every
field. It also runs the pure rules on every real inbox record on both sides. It prints AGGREGATES only (counts, and
difference paths without values); real records never leave the machine.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow import workspaces
from projectzero.dealflow.triage import card, entity_repair, portfolio_check, routing, view
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "triage_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_triage.json"

# Explicit, documented exclusions for the real comparison. Each one must be justified here; keep this minimal.
#   absorbed_by_merge: an old inbox record merged into another survivor. Its old row is not shown under its old id; if
#   it was undecided it leaves the old counts. When the survivor has no proposal of its own, the view CARRIES the
#   absorbed proposal to the survivor (review 009): the comparison then expects that survivor row with the same
#   machine proposal, judged against the survivor's card, and adds it to the expected counts when the survivor is
#   undecided. Real snapshot: one record, a new KEEP absorbed by a Scout Intake survivor.
EXCLUSIONS = ("absorbed_by_merge",)
APOS = chr(0x2019)  # the typographic apostrophe the old name rules handle ("Sweden’s", "DeepPsy’s")  # noqa: RUF003


# ------------------------------------------------------------------ the oracle
def run_oracle(files: Mapping[str, bytes], units: list[dict[str, Any]]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-triage-oracle-") as tmp:
        tmpdir = Path(tmp)
        data = tmpdir / "data"
        data.mkdir()
        for rel, raw in files.items():
            target = (data / rel).resolve()
            if data.resolve() not in target.parents:
                raise SystemExit(f"refusing a path outside the scratch folder: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        src, dst = tmpdir / "in.json", tmpdir / "out.json"
        src.write_text(json.dumps({"units": units}), encoding="utf-8")
        env = {**os.environ, "PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)  # the oracle never needs, and never sees, the database
        run = subprocess.run([str(python), str(ORACLE), str(src), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


# ------------------------------------------------------------------ the new side
def _pattern(rx: Any) -> list[Any]:
    return [rx.pattern, int(rx.flags)]


def new_tables() -> dict[str, Any]:
    er, pc, rt = entity_repair, portfolio_check, routing
    return {
        "eu_places": list(rt.EU_PLACES),
        "cities": list(rt.CITIES),
        "incumbents": list(rt._INCUMBENTS),
        "routing_patterns": {k: _pattern(getattr(rt, k)) for k in
                             ("_UNIVERSITY", "_GOVERNMENT", "_CATAPULT", "_PUBLIC_RESEARCH", "_PLC")},
        "repair_patterns": {k: _pattern(getattr(er, k)) for k in
                            ("_DATEISH", "_EVENTISH", "_AFTER_DESCRIPTOR", "_BEFORE_VERB", "_NOT_A_COMPANY",
                             "_LEGAL_SUFFIX")},
        "repair_sets": {k: sorted(getattr(er, k)) for k in ("_DEMONYMS", "_LEADING_NOISE", "_GENERIC")},
        "headline_patterns": {k: _pattern(getattr(er, k)) for k in
                              ("_HEADLINE_LABELS", "_CITY_BASED", "_COUNTRY_POSS")},
        "headline_strings": {k: getattr(er, k) for k in ("_FUNDING_VERBS", "_NAME_TOKEN", "_NAME_RUN")},
        "name_stop": sorted(er._NAME_STOP),
        "portfolio": [[n, w, list(k)] for n, w, k in pc.PORTFOLIO],
        "portfolio_patterns": {k: _pattern(getattr(pc, k)) for k in ("_PROJECT_A", "_RELATIONSHIP_WORDS")},
        "discovery_tiers": dict(card.DISCOVERY_TIERS),
        "locked_v3": dict(card.LOCKED_V3),
        "prompt_version": card.PROMPT_VERSION,
        "pre_funding": sorted(view.PRE_FUNDING),
    }  # fmt: skip


def new_units(
    units: list[dict[str, Any]], checker: portfolio_check.Checker, override: workspaces.Override
) -> dict[str, Any]:
    out = {}
    for index, c in enumerate(units):
        out[f"{index}:{c.get('id')}"] = {
            "route": routing.route(c, override),
            "non_startup_reason": routing.non_startup_reason(c),
            "european_connection": routing.european_connection(c),
            "broken_name_reason": entity_repair.broken_name_reason(c),
            "repair": entity_repair.repair(c),
            "extract_entities": entity_repair.extract_entities(c),
            "extract_company": entity_repair.extract_company(c.get("name")),
            "names_for": checker.names_for(c),
            "check": checker.check(c),
            "card": card.candidate_card(c),
            "card_sha": card.card_sha(c),
        }
    result: dict[str, Any] = js(out)
    return result


def _json_or(raw: bytes | None, default: Any) -> Any:
    """The old tolerant ``storage.load_json``: a missing or unreadable file is the default."""
    if raw is None:
        return default
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return default


def inputs_from_files(files: Mapping[str, bytes]) -> view.TriageInputs:
    """The old data folder's files as the view's inputs, read exactly as the old modules read them (no database):
    the offline counterpart of ``view.load``."""
    inbox = _json_or(files.get("inbox.json"), {"candidates": []})
    proposals = _json_or(files.get("triage_proposals.json"), {}) or {}
    real_data = _json_or(files.get("real_data.json"), {}) or {}
    intake = _json_or(files.get("scout_intake.json"), {}) or {}
    log = files.get(view.DECISION_LOG)
    return view.TriageInputs(
        candidates=[c for c in inbox.get("candidates") or [] if isinstance(c, dict)],
        proposals=proposals.get("proposals") or {},
        routes=(_json_or(files.get("queue_routing.json"), {}) or {}).get("routes") or {},
        decision_log=log.decode("utf-8") if log is not None else "",
        conviction_signals=real_data.get("signals", []) or [],
        scout_items=intake.get("items", {}) or {},
        acceptance=_json_or(files.get(view.ACCEPTANCE_DOC), {}),
        auto_runs=_json_or(files.get(view.AUTO_RUNS_DOC), {}),
        override=workspaces.parse_override(_json_or(files.get("workspace_geos.json"), {})),
    )


def checker_and_override(inp: view.TriageInputs) -> tuple[portfolio_check.Checker, workspaces.Override]:
    return portfolio_check.Checker(inp.conviction_signals, inp.scout_items), inp.override


# ------------------------------------------------------------------ synthetic goldens
def _c(cid: str, name: str, description: str | None = "", **extra: Any) -> dict[str, Any]:
    base = {"id": cid, "name": name, "description": description, "source": "Oracle Feed", "source_id": "oracle",
            "discovery_tier": "announcement", "decision": "new", "geo": ["DE"], "sectors": ["ai_sw"]}  # fmt: skip
    return base | extra


def golden_candidates() -> list[dict[str, Any]]:
    long = "Robotics for factories across Europe. " * 40
    return [
        _c("eu-plain", "Acme Robotics GmbH", "Industrial robots for SMEs in Munich."),
        _c("uni", "Technical University of Munich", "A spinout project from the robotics lab."),
        _c("gov", "Innovate UK", "Grant programme."),
        _c("catapult", "Digital Catapult", "UK innovation centre."),
        _c("research", "Fraunhofer Institute for Laser Technology", "Applied research."),
        _c("incumbent", "Rolls-Royce Holdings", "Engines."),
        _c("plc", "Acme Widgets PLC", "Listed widgets."),
        _c("na-global", "Prairie AI Inc", "Agents for US farmers in Iowa.", geo=["US"]),
        _c("na-eu", "Harbor AI Inc", "US startup with an office in Munich.", geo=["US"]),
        _c("na-country", "Maple Labs", "Built in Toronto.", geo=[], country="Canada"),
        _c("override", "Zed Labs", "Software.", geo=["ZZ"]),
        _c("region-eu", "Scope Co", "Pan-European.", geo=[], geo_scope="region-eu"),
        _c("geo-str", "String Geo", "Software.", geo="US"),
        _c("broken-date", "01.10.2026 17:08", "RheoCarti awarded the EIC grant. The team builds cartilage implants."),
        _c("broken-unknown", "UNKNOWN", "Startup Kontext raises €2M to secure AI agents."),
        _c("headline", "How Acme Labs is shaping the future of defence", "Acme Labs builds C2 software."),
        _c("label-kontext", "KI-Security-Startup Kontext", "Security for AI agents."),
        _c("portfolio", "Nexcade", "AI agents for freight forwarders."),
        _c("portfolio-reject", "Tabular GmbH", "Accounting automation."),
        _c("relationship", "Orbit Systems", "Orbit Systems raised a seed round led by Project A Ventures."),
        _c("not-relationship", "Lesson Co", "Project A: 5 lessons from building a fund."),
        _c("resembles", "Cargo Brain", "Quoting and booking automation for freight forwarders and logistics agent."),
        _c("conviction", "Conflict Robotics", "Robots."),
        _c("conviction-clear", "Clear Robotics", "Robots."),
        _c("intake", "Intake Labs", "Found by a scout."),
        _c("obvious", "Junk Page", "Cookie banner.", decision="new"),
        _c("obvious-stage0", "05.10.2026 14:00", ""),
        _c("stale", "Changed Co", "The text changed after triage."),
        _c("old-prompt", "Old Prompt Co", "Triaged under v2."),
        _c("baseline", "Baseline Co", "Already known.", decision="baseline"),
        _c("research-decided", "Decided Co", "Operator reviewing.", decision="research"),
        _c("error", "Error Co", "Triage failed."),
        _c("needs-human", "Human Co", "Needs a human."),
        _c("no-proposal", "Quiet Co", "Never triaged."),
        _c("verdict", "Verdict Co", "Operator decided."),
        _c(
            "card",
            "Card Co",
            long,
            also_seen=[{"source": f"Feed {i}"} for i in range(7)] + ["junk"],
            discovery_tier="grant",
            source_url="https://example.org/a",
            source_date="2026-10-01",
            date_kind="published",
            location="Berlin",
            country="DE",
            sectors=[],
            source_sectors=["robotics", "defence"],
        ),
        _c("card-none", "Card None", None, discovery_tier=None, geo=None, sectors=None),
        _c("", "No Id", "Skipped by the view."),
    ]


def unit_extras() -> list[dict[str, Any]]:
    names = [
        ("Thursday, November 5, 2026 ·", ""), ("Swiss-German", "A Swiss-German team."),
        ("TechCrunch Disrupt Summit", ""),
        ("Foo Bar Baz Qux Quux GmbH raises", "Long legal name."), ("Shell Energy Retail", ""), ("BP", ""),
        ("Imperial College London", ""), ("Exclusive: Gravity Gardens secures €3M", ""),
        ("Dutch AgTech Gravity Gardens secures €3M seed", ""), ("Berlin-based Foo raises €1M", ""),
        (f"Sweden{APOS}s Einride lands $100M", ""), ("UNKNOWN", f"DeepPsy{APOS}s obtains CE mark. More text."),
        ("UNKNOWN", "The defence technology company DOD Solution has raised a round."),
        ("UNKNOWN", "Meet the AI Research Lab Grubel, based in Zurich."),
        ("UNKNOWN", "Five startups win — Acme Wins Prize."), ("German Bionic raises €10M", ""),
        ("The Startup Fooly raises seed", ""), ("ACMEROBOTICSINTERNATIONAL", ""), ("Project A 2", "project a 2 fund"),
        ("X", "y"), ("", ""), ("Startup Kontext: AI security", ""), ("Fintech Mondu raises", ""),
        ("Robotics Spin-off Nimble from Munich wins award", ""), ("Acme Robotics and the Future Factory", ""),
        ("Acme Robotics for Future Factories", ""), ("ACME ROBOTICS", ""), ("ACMEROBOTICSX raises €2M", ""),
        ("ACMEROBOTICS raises €2M", ""),
    ]  # fmt: skip
    return [_c(f"unit-{i}", n, d) for i, (n, d) in enumerate(names)]


def golden_files() -> dict[str, bytes]:
    cands = golden_candidates()
    by_id = {c["id"]: c for c in cands}

    def prop(cid: str, proposal: str, **extra: Any) -> dict[str, Any]:
        p = {"candidate_id": cid, "proposal": proposal, "status": "proposed", "prompt_version": card.PROMPT_VERSION,
             "input_sha": card.card_sha(by_id[cid]), "proposed_at": "2026-10-09T08:17:12", "model": card.CHEAP_MODEL,
             "stage": "stage1", "path": "cheap", "confidence": "medium", "reasons": ["grounded reason"],
             "missing": [], "flags": [], "capital_stage": "UNKNOWN", "themes": [], "sector": "robotics",
             "entity_type": "VENTURE", "run_id": "run-1"}  # fmt: skip
        return p | extra

    proposals = {cid: prop(cid, "RESEARCH") for cid in by_id if cid not in ("no-proposal", "")}
    proposals["portfolio"] = prop("portfolio", "KEEP", capital_stage="PRE_COMPANY")
    proposals["portfolio-reject"] = prop("portfolio-reject", "REJECT", reject_basis="NON_VENTURE",
                                         path="cheap -> veto: both reject")  # fmt: skip
    proposals["relationship"] = prop("relationship", "WATCH", capital_stage="ROUND_FORMING")
    proposals["uni"] = prop("uni", "KEEP", capital_stage="FIRST_INSTITUTIONAL")
    proposals["obvious"] = prop(
        "obvious", "REJECT", path="cheap -> veto: both reject", reject_basis="NOT_AN_ENTITY",
        reject_evidence="Cookie banner", model_proposal="REJECT", capital_stage="ALREADY_INSTITUTIONALLY_FUNDED",
        veto={"model": card.VETO_MODEL, "mode": "standard", "ok": True, "model_proposal": "REJECT",
              "reject_basis": "NOT_AN_ENTITY", "reasons": ["not an entity"]},
    )  # fmt: skip
    proposals["obvious-stage0"] = prop("obvious-stage0", "REJECT", stage="stage0", path="stage0 junk")
    proposals["stale"] = prop("stale", "REJECT", path="cheap -> veto: both reject", input_sha="0123456789abcdef")
    proposals["old-prompt"] = prop("old-prompt", "KEEP", prompt_version="triage-v2")
    proposals["error"] = prop("error", "RESEARCH", status="error")
    proposals["needs-human"] = prop("needs-human", "WATCH", status="needs_human", veto={})
    proposals["baseline"] = prop("baseline", "REJECT", path="both reject", capital_stage="ANGEL_ONLY")
    proposals["research-decided"] = prop("research-decided", "KEEP", capital_stage="GRANT_ONLY")
    proposals["broken-unknown"] = prop("broken-unknown", "RESEARCH", capital_stage=None)
    routes = {
        cid: {"state": state, "priority": pr, "reason": f"routed {cid}", "priority_why": ["fresh"], "underlying": None,
              "resurfaced": False, "at": "2026-11-08T19:40:00", "evidence_fp": "abc", "proposal": "RESEARCH"}
        for cid, state, pr in (("eu-plain", "NEEDS_OPERATOR", 80), ("uni", "MACHINE_WATCH", 10),
                               ("baseline", "NEEDS_OPERATOR", 50), ("portfolio", "CONFLICT_GATED", 90),
                               ("no-proposal", "BACKGROUND", 1), ("ghost", "BACKGROUND", 2))
    }  # fmt: skip
    log = [
        {"ts": "2026-10-31T17:20:00", "candidate_id": "verdict", "machine": "RESEARCH", "verdict": "REJECT",
         "mode": "override", "agreed": False},
        {"ts": "2026-10-31T17:21:00", "candidate_id": "verdict", "machine": "RESEARCH", "verdict": "RESEARCH",
         "mode": "accept", "agreed": True},
        {"ts": "2026-10-31T17:22:00", "candidate_id": "gone", "machine": "REJECT", "verdict": "KEEP",
         "mode": "override", "agreed": False},
        {"ts": "2026-10-31T17:23:00", "candidate_id": "obvious", "machine": "REJECT", "verdict": "REJECT",
         "mode": "batch_accept", "agreed": True},
        {"ts": "2026-10-31T17:24:00", "candidate_id": "", "machine": "KEEP", "verdict": "KEEP"},
    ]  # fmt: skip
    log_text = (
        "\n".join(json.dumps(e) for e in log[:2])
        + "\nnot json\n[1, 2]\n\n"
        + "\r\n".join(json.dumps(e) for e in log[2:])
    )
    runs = {"runs": [
        {"pending": [{"id": "old-run", "reason": "too old: outside the last five runs"}], "failed": []},
        *({"pending": [], "failed": []} for _ in range(2)),
        {"pending": [{"id": "no-proposal", "reason": "provider outage"}, {"id": "eu-plain", "reason": "has one"}],
         "failed": [{"id": "error", "reason": "schema error"}]},
        {"pending": [{"id": "needs-human", "reason": "waiting"}], "failed": []},
        {"pending": [], "failed": [{"id": "no-proposal", "reason": "failed again"}]},
    ]}  # fmt: skip
    real_data = {"signals": [
        {"company": "Conflict Robotics", "conflict": "potential_conflict", "slug": "conflict-robotics"},
        {"company": "Clear Robotics", "conflict": "none"},
        {"company": "Conflict Robotics GmbH", "conflict": "unclear"},  # same normalised name: the later one wins
        {"company": ""}, "not a record",
    ]}  # fmt: skip
    intake = {"items": {
        "si-1": {"entity_name": "Intake Labs", "status": "REVIEWING"},
        "si-2": {"entity_name": "Intake Labs Ltd", "status": "MONITOR"},  # same name: the first one wins
        "si-3": {"entity_name": "Clear Robotics", "status": "NEW INTAKE"},  # never replaces a Conviction record
        "si-4": {"status": "NEW INTAKE"},
    }}  # fmt: skip
    acceptance = {"status": "ACCEPTED — shadow only", "holdout": {"n": 100, "false_rejects": 0}, "other": 1}
    files = {
        "inbox.json": {"candidates": [*cands, "not a record"]},
        "triage_proposals.json": {"version": 1, "proposals": proposals},
        "queue_routing.json": {"routes": routes},
        "real_data.json": real_data,
        "scout_intake.json": intake,
        view.ACCEPTANCE_DOC: acceptance,
        view.AUTO_RUNS_DOC: runs,
        "workspace_geos.json": {"eu": ["ZZ"]},
    }
    out = {path: json.dumps(body, ensure_ascii=False).encode("utf-8") for path, body in files.items()}
    out[view.DECISION_LOG] = log_text.encode("utf-8")
    return out


def compare_goldens(golden: Mapping[str, Any]) -> list[str]:
    """Every difference between the new code and a golden file (used by ``goldens`` and by the offline tests)."""
    files = {k: v.encode("utf-8") for k, v in golden["files"].items()}
    inp = inputs_from_files(files)
    checker, override = checker_and_override(inp)
    problems = ["/tables" + d for d in diff(golden["tables"], js(new_tables()))]
    problems += ["/view" + d for d in diff(golden["view"], js(view.build(inp)))]
    problems += ["/units" + d for d in diff(golden["units"], new_units(golden["candidates"], checker, override))]
    return problems


def write_goldens() -> int:
    files = golden_files()
    units = golden_candidates() + unit_extras()
    oracle = run_oracle(files, units)
    golden = {
        "provenance": oracle["meta"],
        "files": {k: v.decode("utf-8") for k, v in files.items()},
        "candidates": units,
        "tables": oracle["tables"],
        "view": oracle["view"],
        "units": oracle["units"],
    }
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
    v = oracle["view"]
    print(f"triage goldens written: {len(v['proposals'])} proposals, {len(oracle['units'])} unit candidates, "
          f"counts {v['counts']}; new code differences: {len(problems)}")  # fmt: skip
    for p in problems[:40]:
        print("  DIFF", p)
    return 1 if problems else 0


# ------------------------------------------------------------------ the real snapshot
def counts_without(counts: Mapping[str, Any], dropped: list[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """The old ``counts`` minus the contribution of the given (excluded, undecided) proposal summaries."""
    out = {q: dict(v) for q, v in counts.items()}
    for s in dropped:
        keys = [(s["routing"]["queue"], s["display_proposal"])]
        if s["obvious_reject"] and s["routing"]["queue"] == "operating":
            keys.append(("operating", "OBVIOUS_REJECT"))
        for q, k in keys:
            out[q][k] -= 1
            if not out[q][k]:
                del out[q][k]
            if not out[q]:
                del out[q]
    return out


def counts_with(counts: Mapping[str, Any], added: list[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """``counts`` plus the contribution of the given (carried, undecided) proposal summaries."""
    out = {q: dict(v) for q, v in counts.items()}
    for s in added:
        keys = [(s["routing"]["queue"], s["display_proposal"])]
        if s["obvious_reject"] and s["routing"]["queue"] == "operating":
            keys.append(("operating", "OBVIOUS_REJECT"))
        for q, k in keys:
            out.setdefault(q, {})[k] = out.get(q, {}).get(k, 0) + 1
    return out


def compare_real(
    old: Mapping[str, Any],
    new: Mapping[str, Any],
    aliases: Mapping[str, str],
    old_decisions: Mapping[str, Any],
    survivor_decisions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Old view vs new view. Old ids are mapped to survivors; each difference is a path (values are not printed).
    ``old_decisions`` (old inbox id -> decision) lets an excluded undecided record leave the old ``counts`` too."""
    differences: list[str] = []
    excluded: dict[str, list[str]] = {name: [] for name in EXCLUSIONS}
    old_props, new_props = old["proposals"], new["proposals"]
    absorbed = [oid for oid in old_props if aliases.get(oid, oid) != oid]
    excluded["absorbed_by_merge"] = absorbed
    dropped = [old_props[oid] for oid in absorbed if old_decisions.get(oid) == "new"]
    seen: set[str] = set()
    carried: list[Mapping[str, Any]] = []
    for oid in absorbed:  # carried to a survivor that has no proposal of its own
        sid = aliases[oid]
        if sid in old_props or sid in seen or sid not in new_props:
            continue
        seen.add(sid)
        if new_props[sid]["proposal"] != old_props[oid]["proposal"]:
            differences.append(f"/proposals/{sid}: carried proposal differs from absorbed {oid}")
        if (survivor_decisions or {}).get(sid) == "new":
            carried.append(new_props[sid])
    expected = {**old, "counts": counts_with(counts_without(old["counts"], dropped), carried)}
    for key in ("architecture", "note", "calibration", "counts"):
        differences += [f"/{key}{d}" for d in diff(js(expected[key]), js(new[key]))]
    for oid, want in old_props.items():
        sid = aliases.get(oid, oid)
        if sid != oid:
            continue
        seen.add(sid)
        got = new_props.get(sid)
        if got is None:
            differences.append(f"/proposals/{oid}: missing in new")
            continue
        differences += [f"/proposals/{oid}{d}" for d in diff(js(want), js(got))]
    differences += [f"/proposals/{sid}: extra in new" for sid in sorted(set(new_props) - seen)]
    mapped_pending = {aliases.get(k, k): v for k, v in old["pending"].items()}
    differences += [f"/pending{d}" for d in diff(js(mapped_pending), js(new["pending"]))]
    queues = [s["routing"]["queue"] for s in new_props.values()]
    return {
        "proposals_old": len(old_props),
        "proposals_new": len(new_props),
        "routed_overlay": sum(1 for s in new_props.values() if s.get("queue")),
        "non_startup": queues.count("non_startup"),
        "global_only": queues.count("global_only"),
        "operating": queues.count("operating"),
        "stale": sum(1 for s in new_props.values() if s["stale"]),
        "obvious_reject": sum(1 for s in new_props.values() if s["obvious_reject"]),
        "flagged_display": sum(1 for s in new_props.values() if s["display_proposal"] != s["proposal"]),
        "repaired_names": sum(1 for s in new_props.values() if s["entity"]["broken"]),
        "with_verdict": sum(1 for s in new_props.values() if s["mohamed"]),
        "pending_old": len(old["pending"]),
        "pending_new": len(new["pending"]),
        "excluded": {k: len(v) for k, v in excluded.items()},
        "excluded_ids": excluded,
        "differences": differences,
    }


def real() -> int:
    import secrets as _secrets

    from psycopg import sql as _sql

    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot.files()}
    inbox = snapshot.json("inbox.json")
    records = [c for c in inbox.get("candidates", []) if isinstance(c, dict) and c.get("id")]
    oracle = run_oracle(files, records)

    offline = inputs_from_files(files)
    checker, override = checker_and_override(offline)
    unit_diffs = diff(oracle["units"], new_units(records, checker, override))
    table_diffs = diff(oracle["tables"], js(new_tables()))
    offline_diffs = diff(js(oracle["view"]), js(view.build(offline)))

    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            plan = build_plan(snapshot)
            applied = apply_plan(plan, schema=schema, conn=conn)
            assert applied.get("applied"), applied
        finally:
            conn.close()
        with transaction(settings.db_url) as conn:
            new = js(view.triage_view(conn, schema))
            aliases = {
                str(a): str(c)
                for a, c in conn.execute(
                    _sql.SQL("select alias_id, candidate_id from {}.candidate_aliases where namespace = 'candidate'")
                    .format(_sql.Identifier(schema))
                ).fetchall()
            }  # fmt: skip
            status_rows = conn.execute(
                _sql.SQL("select id, status from {}.candidates").format(_sql.Identifier(schema))
            ).fetchall()
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()

    from projectzero.dealflow.ranking.service import STATUS_TO_DECISION

    decisions = {str(c["id"]): c.get("decision") for c in records}
    survivors = {str(i): STATUS_TO_DECISION.get(str(st), "new") for i, st in status_rows}
    result = compare_real(oracle["view"], new, aliases, decisions, survivors)
    differences = result.pop("differences")
    report = {
        "mode": "real snapshot through the production import + the triage view",
        "oracle": oracle["meta"],
        "inbox_records": len(records),
        **result,
        "differences": len(differences),
        "offline_view_differences": len(offline_diffs),
        "unit_rule_differences": len(unit_diffs),
        "table_differences": len(table_diffs),
    }
    print(json.dumps(report, indent=2))
    for d in (differences + offline_diffs + unit_diffs + table_diffs)[:40]:
        print("  ", d.split(":")[0])
    ok = not (differences or offline_diffs or unit_diffs or table_diffs)
    print("TRIAGE PARITY PASSED" if ok else "TRIAGE PARITY FAILED")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    if argv[1:] == ["real"]:
        return real()
    print("usage: python -m projectzero.ops.parity_triage goldens|real")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
