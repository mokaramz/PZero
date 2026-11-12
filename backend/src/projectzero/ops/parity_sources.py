"""Sources parity: the port against the OLD code as oracle, with a FIXED clock (review 021).

    python -m projectzero.ops.parity_sources goldens   # (re)generate tests/fixtures/golden_v1/oracle_sources.json
    python -m projectzero.ops.parity_sources real      # the real snapshot through GET /api/sources and the toggle

The oracle (``scripts/oracle/sources_oracle.py``) runs the old ``sources_view()`` (+ the four inbox fields the page
read) and ``source_toggle`` over a scratch data folder. ``goldens`` compares the PURE port (normalization, coverage,
feedback, ws_geos, the lists) over synthetic registries: every repair, ``geo_scope`` default, health and coverage
edge, an unknown kind and a missing reliability; a separate registry with an unknown reliability string records that
the old view raised. Its toggle script is replayed by ``tests/hosted/test_sources_hosted.py`` on the new endpoint.
``real`` imports the snapshot with the production importer into a throw-away schema and compares the whole GET and a
toggle replay. It prints AGGREGATES and difference PATHS only. Exit 1 on any difference.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.ops.parity_ranking import GOLDEN_DIR, OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "sources_oracle.py"
GOLDEN = GOLDEN_DIR / "oracle_sources.json"
CLOCK = "2026-11-11T12:00:00"
REAL_CLOCK = "2026-11-12T09:00:00"


def src(sid: str, name: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"id": sid, "name": name, "url": f"https://{sid}.example.com/list", "kind": "watcher",
                            "parser": "page_diff", "geo": ["DACH"], "sectors": ["ai_sw"], "stage": "pre_company",
                            "reliability": "medium", "freshness": "weekly", "enabled": True, "last_scan": None,
                            "last_ok": None, "last_result_count": None, "failures_in_row": 0,
                            "yield": {"kept": 0, "research": 0, "rejected": 0}, "country": "Germany"}  # fmt: skip
    return base | kw


def corpus() -> dict[str, Any]:
    """Invented sources (the repair conditions match on the old ids / name words, as the old registry used them)."""
    sources = [
        src("x-diana", "Example DIANA cohort", kind="watcher"),  # repair 1
        src("x-eth", "ETH transfer spin-offs", kind="watcher"),  # repair 2
        src("x-ticker", "Example startupticker feed", kind="rss", reliability="low"),  # repair 4
        src("uk-gtr", "UKRI Gateway (example)", kind="api", reliability="high", geo=["UK"], country="UK"),
        src("eu-cordis", "CORDIS (example)", kind="api", reliability="high", geo=["EU"], country="EU"),
        src("eu-eic-acc", "EIC Accelerator (example)", kind="dataset", geo=["EU"], country="Europe"),
        src("eu-eic-path", "EIC Pathfinder (example)", kind="dataset", geo=["EU"], country=""),
        src("legacy-eic-x", "EIC example list", kind="manual", reliability="low"),
        src("fr-ilab", "i-Lab (example)", kind="watcher", geo=["FR"], country="France"),
        src("x-done", "Example DIANA already repaired", _repair_v=2),  # _repair_v 2: no second repair
        src("eu-ellis-signal", "ELLIS (old url)", url="https://ellis.eu/news", kind="structured", geo=["EU"]),
        src("de-insurtech-hub-munich", "Insurtech (old url)", url="https://www.insurtech-munich.com/news"),
        src("de-sprind-projects", "SPRIND (old note)", notes="Earlier note.", kind="structured"),
        src("us-yc-launches", "YC launches (example)", kind="rss", geo=["US"], country="USA", reliability="low"),
        src(
            "x-healthy",
            "Healthy proven",
            kind="api",
            reliability="high",
            last_ok="2026-11-10 08:15",
            last_scan="2026-11-10 08:15",
            total_results=12,
            last_result_count=3,
            sectors=["ai_sw", "deeptech", "bogus"],
            geo=["DACH", "CH", "XX"],
            quality={"kept": 2, "radar": 1},
        ),
        src("x-failing", "Failing proven", kind="rss", failures_in_row=3, last_ok="2026-10-01 09:00", total_results=4),
        src("x-warn", "Warning source", failures_in_row=1, last_ok="2026-11-09 10:00", total_results=1),
        src("x-off", "Disabled source", enabled=False, total_results=9, last_ok="2026-11-01 07:00"),
        src("x-unknown-kind", "Unknown kind", kind="carrier_pigeon"),
        {k: v for k, v in src("x-no-rel", "Missing reliability").items() if k != "reliability"},  # defaults to low
        src("x-no-scope", "No scope, EU", country="EU"),
        src("x-na", "North America source", geo=["CA"], country="Canada", kind="ics"),
    ]
    for s in sources:
        if s["id"] == "x-no-scope":
            s.pop("geo_scope", None)
        else:
            s.setdefault("geo_scope", "country") if s["id"] not in ("us-yc-launches", "x-no-scope") else None
    picks = ["kept", "kept", "research", "rejected", "kept", "watch"]
    decisions = {
        f"c{i}": {"decision": d, "source_ids": ["x-healthy"], "name": f"Company {i}"} for i, d in enumerate(picks)
    }
    feedback = {"version": 2, "label": "Feedback-adjusted sourcing priority", "omar": {}, "history": [],
                "decisions": decisions}  # fmt: skip
    inbox = {"candidates": [], "last_run": "2026-11-10T08:00:00",
             "report": [{"source": "Healthy proven", "status": "ok", "count": 3},
                        {"source": "Failing proven (rss)", "status": "error", "error": "HTTP 503"}]}  # fmt: skip
    return {"sources.json": {"sources": sources}, "feedback.json": feedback, "inbox.json": inbox}


STEPS: list[dict[str, Any]] = [
    {"id": "x-healthy", "enabled": False},
    {"id": "x-healthy", "enabled": False},  # the same value again
    {"id": "x-healthy", "enabled": True},
    {"id": "x-off"},  # no "enabled": bool(None) -> disabled (already)
    {"id": "x-off", "enabled": 1},  # truthy -> enabled
    {"id": "ch-epfl-creation", "enabled": False},  # exists only through the normalization (a sources_v2 default)
    {"id": "no-such-source", "enabled": True},
]


def _files(docs: dict[str, Any]) -> dict[str, bytes]:
    return {k: json.dumps(v, ensure_ascii=False, indent=2).encode("utf-8") for k, v in docs.items()}


def run_oracle(inp: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-sources-oracle-") as tmp:
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
        env = {**os.environ, "PZ_DATA": str(data), "PZ_TESTING": "1", "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)
        run = subprocess.run([str(python), str(ORACLE), str(srcf), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


def new_view(docs: dict[str, Any]) -> dict[str, Any]:
    """The pure port over the same files (no events since an import: no deltas)."""
    from projectzero.dealflow import workspaces
    from projectzero.dealflow.sources.view import sources_view

    inbox = docs.get("inbox.json") or {}
    out: dict[str, Any] = js(sources_view(
        list(docs["sources.json"]["sources"]), ledger=docs.get("feedback.json"), deltas={},
        override=workspaces.parse_override(docs.get("workspace_geos.json") or {}),
        inbox_rest={k: v for k, v in inbox.items() if k != "candidates"},
    ))  # fmt: skip
    return out


def unknown_reliability() -> dict[str, Any]:
    return {"sources.json": {"sources": [src("x-rel", "Odd reliability", reliability="excellent")]}}


def compare_goldens(golden: dict[str, Any]) -> list[str]:
    problems = [f"/view{p}" for p in diff(golden["expected"]["view"], new_view(golden["docs"]))]
    try:
        new_view(golden["unknown_reliability"]["docs"])
        problems.append("/unknown_reliability: the old view raised, the new one did not")
    except KeyError:
        pass
    return problems


def write_goldens() -> int:
    docs = corpus()
    oracle = run_oracle({"clock": CLOCK, "steps": STEPS}, _files(docs))
    odd = run_oracle({"clock": CLOCK, "steps": []}, _files(unknown_reliability()))
    meta = oracle.pop("meta")
    golden = {"provenance": meta, "docs": docs, "steps": STEPS, "expected": oracle,
              "unknown_reliability": {"docs": unknown_reliability(), "expected": odd["view"]}}  # fmt: skip
    GOLDEN.write_text(json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    problems = compare_goldens(json.loads(GOLDEN.read_text(encoding="utf-8")))
    view = oracle["view"]
    print(f"sources goldens written: {len(view['sources'])} sources after normalization (from "
          f"{len(docs['sources.json']['sources'])}), {len(STEPS)} toggle steps, unknown reliability -> {odd['view']}; "
          f"provenance {meta['old_revision'][:7]} dirty={meta['old_dirty']}; "
          f"new code differences: {len(problems)}")  # fmt: skip
    for p in problems[:40]:
        print("  DIFF", p)
    return 1 if problems else 0


def real() -> int:  # pragma: no cover - needs the hosted database and the old repository
    import secrets as _secrets
    from datetime import datetime

    from fastapi.testclient import TestClient
    from psycopg import sql as _sql

    from projectzero.api.app import create_app
    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    files = {f.path: f.raw for f in snapshot.files()}
    registry = snapshot.json("sources.json", {}).get("sources", [])
    on = next(s["id"] for s in registry if s.get("enabled"))
    off = next((s["id"] for s in registry if not s.get("enabled")), on)
    steps = [{"id": on, "enabled": False}, {"id": on, "enabled": False}, {"id": on, "enabled": True},
             {"id": off}, {"id": "no-such-source", "enabled": True}]  # fmt: skip
    old = run_oracle({"clock": REAL_CLOCK, "steps": steps}, files)
    schema = f"pz_rehearse_{_secrets.token_hex(4)}"
    report: dict[str, Any] = {"oracle": old["meta"], "sources_archived": len(registry)}
    problems: list[str] = []
    admin = connect(settings.db_url, autocommit=True)
    try:
        admin.execute(_scratch_sql(schema).encode())
        conn = connect(settings.db_url)
        try:
            applied = apply_plan(build_plan(snapshot), schema=schema, conn=conn)
            assert applied.get("applied"), applied
        finally:
            conn.close()
        app = create_app(Settings(db_url=settings.db_url, schema=schema))
        app.state.clock = lambda: datetime.fromisoformat(REAL_CLOCK)
        with TestClient(app, base_url="http://127.0.0.1:8177") as client:
            first = client.get("/api/sources").json()
            problems += [f"/view{p.split(':')[0]}" for p in diff(js(old["view"]), first)]
            report["sources_in_view"] = len(first.get("sources", []))
            for i, (step, exp) in enumerate(zip(steps, old["steps"], strict=True)):
                r = client.post("/api/sources/toggle", json=step)
                if r.json() != exp["body"]:
                    problems.append(f"/step{i}/body")
                got = client.get("/api/sources").json()
                problems += [f"/step{i}/view{p.split(':')[0]}" for p in diff(js(exp["view"]), got)]
            report["steps"] = len(steps)
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    report["differences"] = len(problems)
    print(json.dumps(report, indent=2))
    for p in problems[:60]:
        print("  DIFF", p)
    print("SOURCES PARITY PASSED" if not problems else "SOURCES PARITY FAILED")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if argv[1:] == ["goldens"]:
        return write_goldens()
    if argv[1:] == ["real"]:
        return real()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
