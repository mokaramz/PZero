"""Ranking parity: the ported rules against the OLD code as oracle (review 006).

    python -m projectzero.ops.parity_ranking goldens   # (re)generate the small synthetic oracle goldens
    python -m projectzero.ops.parity_ranking real      # all real candidates + the real ledger; exit 1 on any diff

The oracle runs in the OLD repository's own interpreter and package (``scripts/oracle/ranking_oracle.py``), in a
separate process, with ``PZ_DATA`` pointed at an empty scratch folder. Both sides get the same JSON input. Outputs
are compared after a JSON round trip, key by key, list order included; a missing, extra or duplicated candidate key
is a failure. ``real`` prints and saves AGGREGATES only (counts, digests); real records never leave the machine.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.dealflow.ranking import attention, feedback, themes

OLD_REPO = Path(os.environ.get("PZ_OLD_REPO", r"C:\Users\MohamedKaram\Desktop\project-zero"))
ORACLE = REPO_ROOT / "scripts" / "oracle" / "ranking_oracle.py"
GOLDEN_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "golden_v1"
REPORT = REPO_ROOT / "docs" / "team" / "import" / "ranking_parity.json"


def js(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def run_new(candidates: list[dict[str, Any]], ledgers: dict[str, Any], last_run: Any) -> dict[str, Any]:
    tables = {name: feedback.table(led) for name, led in ledgers.items()}  # None (no file) reads as empty
    per = {}
    for index, c in enumerate(candidates):
        sc, sig = themes.lens_signals(c)
        per[f"{index}:{c.get('id')}"] = {
            "themes": themes.themes_for(c),
            "lens": {"score": sc, "signals": sig},
            "attention_v2": attention.annotate_v31(c, last_run),
            "feedback": {name: feedback.for_candidate(c, tbl) for name, tbl in tables.items()},
        }
    out: dict[str, Any] = js(per)
    return out


def run_oracle(candidates: list[dict[str, Any]], ledgers: dict[str, Any], last_run: Any) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-oracle-") as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "data").mkdir()
        src, dst = tmpdir / "in.json", tmpdir / "out.json"
        src.write_text(
            json.dumps({"last_run": last_run, "candidates": candidates, "ledgers": ledgers}), encoding="utf-8"
        )
        env = {**os.environ, "PZ_DATA": str(tmpdir / "data"), "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)  # the oracle never needs, and never sees, the database
        run = subprocess.run([str(python), str(ORACLE), str(src), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out = json.loads(dst.read_text(encoding="utf-8"))
        assert isinstance(out, dict)
        return out


def diff(old: dict[str, Any], new: dict[str, Any], path: str = "") -> list[str]:
    """Every difference as a path. Dicts: missing/extra keys and value diffs. Lists: length and element order."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = [f"{path}/{k}: missing in new" for k in sorted(old.keys() - new.keys())]
        out += [f"{path}/{k}: extra in new" for k in sorted(new.keys() - old.keys())]
        for k in sorted(old.keys() & new.keys()):
            out += diff(old[k], new[k], f"{path}/{k}")
        return out
    if isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            return [f"{path}: length {len(old)} != {len(new)}"]
        return [d for i, (a, b) in enumerate(zip(old, new, strict=True)) for d in diff(a, b, f"{path}[{i}]")]
    if old != new or type(old) is not type(new):
        return [f"{path}: {old!r} != {new!r}"]
    return []


def compare(candidates: list[dict[str, Any]], ledgers: dict[str, Any], last_run: Any) -> dict[str, Any]:
    oracle = run_oracle(candidates, ledgers, last_run)
    new = run_new(candidates, ledgers, last_run)
    differences = diff(oracle["per_candidate"], new)
    ids = [c.get("id") for c in candidates]
    return {
        "oracle_meta": oracle["meta"],
        "candidates": len(candidates),
        "distinct_ids": len(set(ids)),
        "duplicate_ids": len(ids) - len(set(ids)),
        "missing_ids": sum(1 for i in ids if not i),
        "compared_keys": len(oracle["per_candidate"]),
        "differences": len(differences),
        "first_differences": differences[:20],
        "oracle": oracle,
    }


# ── synthetic goldens: quirks of the legacy text building, and the feedback ledger ───────────────────────────────
def quirk_corpus() -> list[dict[str, Any]]:
    base = {"id": "q", "source": "NIH RePORTER", "source_id": "us-nih", "discovery_tier": "announcement"}
    return [
        base | {"id": "absent-fields", "name": "Acme Robotics GmbH"},
        base | {"id": "null-fields", "name": "Acme Robotics GmbH", "description": None, "notes": None, "why": None,
                "sectors": None, "founder_signal": None, "why_found": None},
        base | {"id": "list-repr", "name": "Quote Labs", "sectors": ["robotics", "it's ai"],
                "why": ["fits \"frontier\"", "line\nbreak"], "description": "We build robotic arms for factories."},
        base | {"id": "numbers", "name": "Num Co", "notes": 42, "why": [1, 2], "archetype_hits": [1, "2", 13, 15]},
        base | {"id": "new-this-run", "name": "Fresh Labs", "run_id": "2026-11-08 19:09:09"},
        base | {"id": "run-id-other-type", "name": "Typed Labs", "run_id": 20261108},
        base | {"id": "noise", "name": "Noisy AI", "noise": True},
        base | {"id": "pre-company", "name": "Proj X", "discovery_tier": "pre_company",
                "description": "Founding team of PhD researchers at TU Munich; spin-off project."},
        base | {"id": "grant", "name": "Grant Co", "discovery_tier": "grant", "description": "EIC grant for a photonic chip."},  # noqa: E501
        base | {"id": "seed-amount", "name": "Big Seed", "description": "Raised a € 9,5 million seed round."},
        base | {"id": "series-b", "name": "Later Co", "description": "Closed its Series B."},
        base | {"id": "mature", "name": "Old Co", "description": "Acquired by a listed group; 500 employees."},
        base | {"id": "saas", "name": "Crm Tool", "description": "An all-in-one platform CRM for SMEs."},
        base | {"id": "org-name", "name": "Robotics Society of Europe", "description": "A network of researchers."},
        base | {"id": "headline", "name": "How 5 startups won the year", "description": "A roundup."},
        base | {"id": "unknown", "name": "UNKNOWN"},
        base | {"id": "mismatch", "name": "Foo Analytics", "description": "Bar Robotics raises seed to scale drones."},
        base | {"id": "omar-source", "name": "Omar Co", "source_id": "legacy-omar", "also_seen": [{"source_id": "eu-a"}]},  # noqa: E501
        base | {"id": "multi-source", "name": "Multi Co", "all_source_ids": ["src-pos", "src-neg", "src-half"]},
        base | {"id": "no-source", "name": "Sourceless", "source_id": None},
        base | {"id": "repr-vs-spaces", "name": "Split Co", "why": ["Series", "B"]},
        base | {"id": "unicode", "name": "Ölwerk Süd AG",
                "description": "Gegründet von Dr. Anna Müller (PhD) in Zürich."},
    ]  # fmt: skip


def ledgers() -> dict[str, Any]:
    def decisions(sid: str, pairs: list[tuple[str, str]]) -> dict[str, Any]:
        return {f"{sid}-{i}": {"source_ids": [sid], "decision": d, "name": n} for i, (d, n) in enumerate(pairs)}

    positive = decisions("src-pos", [("kept", f"Pos {i}") for i in range(6)])
    negative = decisions("src-neg", [("rejected", f"Neg {i}") for i in range(5)] + [("research", "Neg R")])
    half = decisions("src-half", [("kept", "Half K")] + [("watch", f"Half W{i}") for i in range(5)])
    below = decisions("src-below", [("kept", f"Below {i}") for i in range(4)])
    return {
        "no_file": None,
        "empty": {},
        "not_a_dict": [],
        "positive": {"decisions": positive},
        "negative": {"decisions": negative},
        "mixed": {
            "decisions": positive | negative | half | below,
            "omar": {
                "omar-co": {"source_id": "legacy-omar", "outcome": "positive", "company": "Omar Co"},  # v1 record
                "pos-1": {"source_ids": ["src-pos"], "outcome": "negative", "company": "Pos 1"},  # same company
                "linked": {"source_ids": ["eu-a"], "outcome": "negative", "candidate_id": "x1", "company": "L"},
            },
        },
    }


def write_goldens() -> None:
    result = compare(quirk_corpus(), ledgers(), "2026-11-08 19:09:09")
    golden = {
        "provenance": result["oracle_meta"],
        "last_run": "2026-11-08 19:09:09",
        "candidates": quirk_corpus(),
        "ledgers": ledgers(),
        "expected": result["oracle"]["per_candidate"],
    }
    (GOLDEN_DIR / "oracle_quirks_feedback.json").write_text(
        json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"oracle goldens written: {len(golden['expected'])} candidates x {len(golden['ledgers'])} ledgers; "
          f"new code differences: {result['differences']}")  # fmt: skip
    for d in result["first_differences"]:
        print("  DIFF", d)


def real() -> int:
    from projectzero.core.config import load_dotenv
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    inbox_file, ledger_file = snapshot.file("inbox.json"), snapshot.file("feedback.json")
    inbox = snapshot.json("inbox.json")
    candidates = [c for c in inbox.get("candidates", []) if isinstance(c, dict) and c.get("id")]
    ledger = snapshot.json("feedback.json")
    result = compare(candidates, {"frozen": ledger, "empty": {}}, inbox.get("last_run"))
    adjustments = [v["feedback"]["frozen"]["adjustment"] for v in result["oracle"]["per_candidate"].values()]
    report = {
        "oracle": result["oracle_meta"],
        "snapshot": {
            "inbox_sha256": inbox_file.sha256,
            "feedback_sha256": ledger_file.sha256,
            "inbox_bytes": len(inbox_file.raw),
            "last_run": inbox.get("last_run"),
            "capture_attempts": snapshot.attempts,
        },
        "candidates": result["candidates"],
        "distinct_ids": result["distinct_ids"],
        "duplicate_ids": result["duplicate_ids"],
        "missing_ids": result["missing_ids"],
        "compared_keys": result["compared_keys"],
        "differences": result["differences"],
        "feedback_adjustments": {
            "positive": sum(a > 0 for a in adjustments),
            "negative": sum(a < 0 for a in adjustments),
            "zero": sum(a == 0 for a in adjustments),
        },
        "gated": sum(1 for v in result["oracle"]["per_candidate"].values() if v["attention_v2"]["gated"]),
        "digest_of_outputs": hashlib.sha256(
            json.dumps(result["oracle"]["per_candidate"], sort_keys=True).encode()
        ).hexdigest(),
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if result["differences"]:
        print("first differences (paths only):")
        for d in result["first_differences"]:
            print("  ", d.split(":")[0])
    ok = not result["differences"] and not result["duplicate_ids"] and not result["missing_ids"]
    print("PARITY PASSED" if ok else "PARITY FAILED")
    return 0 if ok else 1


def verify_survivors(
    planned: set[str], returned: set[str], aliases: list[dict[str, Any]], source_ids: set[str]
) -> list[str]:
    """The list must return EXACTLY the import plan's surviving candidates, and every source record that is not
    returned must be absorbed by a merge alias pointing at a returned survivor (review 006: absent != merged)."""
    problems = [f"missing survivor {cid}" for cid in sorted(planned - returned)]
    problems += [f"unexpected candidate {cid}" for cid in sorted(returned - planned)]
    merge_target = {a["alias_id"]: a for a in aliases if a["namespace"] == "candidate"}
    for cid in sorted(source_ids - returned):
        alias = merge_target.get(cid)
        if alias is None:
            problems.append(f"source {cid} not returned and has no alias")
        elif alias["reason"] != "merge" or alias["candidate_id"] == cid:
            problems.append(f"source {cid} not returned but its alias is not a merge ({alias['reason']})")
        elif alias["candidate_id"] not in returned:
            problems.append(f"source {cid} merged into {alias['candidate_id']}, which the list did not return")
    return problems


def real_through_api() -> int:
    """The strongest check: import the real snapshot into a scratch schema with the real importer, read every
    candidate back through the production list (paged), and compare its ranking with the oracle's output for the
    same legacy Deal Flow record. Source records and surviving candidates are counted separately (merges)."""
    import secrets as _secrets

    from psycopg import sql as _sql

    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.dealflow.candidates import DealFlowStore, ListQuery
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    snapshot = LegacySnapshot.capture(Path(os.environ["PZ_LEGACY_DATA"]))
    inbox = snapshot.json("inbox.json")
    records = [c for c in inbox.get("candidates", []) if isinstance(c, dict) and c.get("id")]
    oracle = run_oracle(records, {"frozen": snapshot.json("feedback.json")}, inbox.get("last_run"))["per_candidate"]
    expected = {key.split(":", 1)[1]: value for key, value in oracle.items()}

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
        items: dict[str, Any] = {}
        cursor = None
        while True:
            with transaction(settings.db_url) as conn:
                page = DealFlowStore(conn, schema).list_candidates(ListQuery(limit=200, cursor=cursor))
            for item in page["items"]:
                if item["id"] in items:
                    raise SystemExit(f"duplicate id across pages: {item['id']}")
                items[item["id"]] = item
            if not (cursor := page["next_cursor"]):
                break
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()

    differences: list[str] = []
    compared = 0
    for cid, want in expected.items():
        item = items.get(cid)
        if item is None:
            continue  # absorbed by a merge: reported below
        compared += 1
        got = js(item["ranking"])  # as the client receives it (JSON: tuples become lists)
        if got["inputs"] != "full":
            differences.append(f"/{cid}: inputs {got['inputs']}")
            continue
        differences += [f"/{cid}{d}" for d in diff(
            {**want, "feedback": want["feedback"]["frozen"]},
            {k: got[k] for k in ("attention_v2", "themes", "lens", "feedback")},
        )]  # fmt: skip
    survivors = {row["id"] for row in plan.tables["candidates"]}
    problems = verify_survivors(survivors, set(items), plan.tables["candidate_aliases"], set(expected))
    report = {
        "mode": "real through the production import + list API",
        "source_records": len(expected),
        "planned_survivors": len(survivors),
        "returned_by_list": len(items),
        "compared_inbox_records": compared,
        "absorbed_by_merge_verified": sum(1 for cid in expected if cid not in items) if not problems else None,
        "partial_inputs": sum(1 for i in items.values() if i["ranking"]["inputs"] == "partial"),
        "survivor_problems": len(problems),
        "differences": len(differences),
    }
    print(json.dumps(report, indent=2))
    for problem in problems[:20]:
        print("  ", problem)
    for d in differences[:20]:
        print("  ", d.split(":")[0])
    ok = not differences and not problems
    print("PARITY (THROUGH API) PASSED" if ok else "PARITY (THROUGH API) FAILED")
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if argv[1:] == ["real-api"]:
        return real_through_api()
    if argv[1:] == ["goldens"]:
        write_goldens()
        return 0
    if argv[1:] == ["real"]:
        return real()
    print("usage: python -m projectzero.ops.parity_ranking goldens|real")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
