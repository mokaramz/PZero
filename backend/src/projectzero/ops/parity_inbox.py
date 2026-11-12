"""Inbox parity: the new Deal Flow read model against the OLD ``inbox_view`` on the real snapshot (review 009).

    python -m projectzero.ops.parity_inbox real [--dump DIR]   # DIR (scratch only): old.json / new.json payloads

1. The oracle runs the old ``inbox_view`` in the old interpreter on a temporary COPY of the old data folder (it writes).
2. The real snapshot is imported into a throw-away scratch schema with the production importer; the new
   ``inbox_view`` reads it back.
3. Comparison population (review 009, Codex #2):
   * the old candidates are mapped to their survivors through the import's ``candidate`` aliases; a record merged
     into another is "absorbed" and must have a verified merge alias;
   * the ordered sequence of legacy survivors (first occurrence, old input order) must equal the new payload's
     order of those candidates;
   * every other new candidate (Scout Intake / Native survivors) must come after them, in a deterministic order;
   * per legacy survivor, every field the old payload carries is compared, except the explicit ``EXCLUDED`` list;
   * the top-level fields are compared, except ``manual_sources`` / ``pages`` / ``feeds`` (never read by the page).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.ops.parity_ranking import OLD_REPO, diff, js

ORACLE = REPO_ROOT / "scripts" / "oracle" / "inbox_oracle.py"
TOP_LEVEL_NOT_CARRIED = frozenset({"manual_sources", "pages", "feeds"})
EXCLUDED: dict[str, str] = {}  # field -> why it may differ (kept empty unless a difference is justified)
# fields the new payload adds on purpose: the decision's stale check (review 009) and the revisit flag (review 018)
NEW_ONLY = frozenset({"pz_status", "revisit"})
TOP_LEVEL_NEW = frozenset({"revisit_count"})  # review 018


def run_oracle(data_dir: Path) -> dict[str, Any]:
    python = OLD_REPO / "backend" / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        raise SystemExit(f"old interpreter not found: {python} (set PZ_OLD_REPO)")
    with tempfile.TemporaryDirectory(prefix="pz-inbox-oracle-") as tmp:
        copy = Path(tmp) / "data"
        shutil.copytree(data_dir, copy)  # inbox_view writes: never on the real folder
        dst = Path(tmp) / "out.json"
        env = {**os.environ, "PZ_DATA": str(copy), "PYTHONPATH": str(OLD_REPO / "backend" / "src")}
        env.pop("SUPABASE_DB_URL", None)
        run = subprocess.run([str(python), str(ORACLE), str(dst)], env=env, capture_output=True, text=True)
        if run.returncode != 0:
            raise SystemExit(f"oracle failed:\n{run.stderr[-3000:]}")
        out: dict[str, Any] = json.loads(dst.read_text(encoding="utf-8"))
        return out


def compare(old: dict[str, Any], new: dict[str, Any], aliases: dict[str, tuple[str, str]]) -> dict[str, Any]:
    """``aliases``: old candidate id -> (survivor id, reason) from the import's 'candidate' namespace."""
    problems: list[str] = []
    old_cands = [c for c in old["candidates"] if isinstance(c, dict) and c.get("id")]
    new_cands = new["candidates"]
    new_ids = [c["id"] for c in new_cands]
    if len(set(new_ids)) != len(new_ids):
        problems.append("duplicate ids in the new payload")
    by_new = {c["id"]: c for c in new_cands}

    survivors: list[str] = []
    absorbed = 0
    for c in old_cands:
        target, reason = aliases.get(c["id"], (c["id"], "own_id"))
        if target != c["id"]:
            absorbed += 1
            if reason != "merge":
                problems.append(f"{c['id']}: resolves to {target} with reason {reason!r}, not a merge")
        if target not in by_new:
            problems.append(f"{c['id']}: survivor {target} missing from the new payload")
        elif target not in survivors:
            survivors.append(target)
    legacy_part = new_ids[: len(survivors)]
    if legacy_part != survivors:
        first = next((i for i, (a, b) in enumerate(zip(legacy_part, survivors, strict=False)) if a != b), None)
        problems.append(f"legacy survivor order differs (first at position {first})")
    extra = new_ids[len(survivors) :]
    if set(extra) & set(survivors):
        problems.append("a legacy survivor appears after the additional candidates")

    fields: list[str] = []
    old_by_id = {c["id"]: c for c in old_cands}
    for cid in survivors:
        o, n = js(old_by_id.get(cid)), js(by_new[cid])
        if o is None:
            continue  # a survivor whose own id was not an inbox record (it absorbed one): checked by order only
        for key in sorted(set(o) | set(n)):
            if key in EXCLUDED:
                continue
            if key not in n:
                fields.append(f"/{cid}/{key}: missing in new")
            elif key not in o:
                if key not in NEW_ONLY:
                    fields.append(f"/{cid}/{key}: extra in new")
            else:
                fields += [f"/{cid}/{key}{d}" for d in diff(o[key], n[key])]
    top = [
        k for k in sorted(set(old) | set(new)) if k != "candidates" and k not in TOP_LEVEL_NOT_CARRIED | TOP_LEVEL_NEW
    ]
    top_diffs = [f"top/{k}{d}" for k in top for d in diff(js(old.get(k)), js(new.get(k)))]
    return {
        "old_records": len(old_cands),
        "legacy_survivors": len(survivors),
        "absorbed": absorbed,
        "additional": len(extra),
        "problems": problems,
        "field_differences": fields,
        "top_level_differences": top_diffs,
    }


def real(dump: Path | None = None) -> int:
    import secrets as _secrets

    from psycopg import sql as _sql

    from projectzero.core.config import Settings, load_dotenv
    from projectzero.core.db import connect, transaction
    from projectzero.dealflow.inbox_view import inbox_view
    from projectzero.ops.db_check import _scratch_sql
    from projectzero.ops.legacy.apply import apply_plan
    from projectzero.ops.legacy.plan import build_plan
    from projectzero.ops.legacy.source import LegacySnapshot

    load_dotenv()
    settings = Settings.from_env()
    data_dir = Path(os.environ["PZ_LEGACY_DATA"])
    oracle = run_oracle(data_dir)
    snapshot = LegacySnapshot.capture(data_dir)
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
            new = inbox_view(conn, schema)
            from projectzero.dealflow.triage.view import triage_view

            triage = triage_view(conn, schema) if dump is not None else None
            rows = conn.execute(
                _sql.SQL(
                    "select alias_id, candidate_id, reason from {}.candidate_aliases where namespace = 'candidate'"
                ).format(_sql.Identifier(schema))
            ).fetchall()
    finally:
        admin.execute(_sql.SQL("drop schema if exists {} cascade").format(_sql.Identifier(schema)))
        admin.close()
    aliases = {str(a): (str(c), str(r)) for a, c, r in rows}
    if dump is not None:  # real data: a scratch folder only, never the repository
        assert REPO_ROOT not in dump.resolve().parents, "dump into a scratch folder, not the repository"
        dump.mkdir(parents=True, exist_ok=True)
        (dump / "old.json").write_text(json.dumps(oracle["view"], ensure_ascii=False), encoding="utf-8")
        (dump / "new.json").write_text(json.dumps(js(new), ensure_ascii=False), encoding="utf-8")
        (dump / "aliases.json").write_text(json.dumps(aliases), encoding="utf-8")
        (dump / "triage.json").write_text(json.dumps(js(triage), ensure_ascii=False), encoding="utf-8")
    result = compare(oracle["view"], js(new), aliases)
    report = {k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}
    report["oracle"] = oracle["meta"]
    print(json.dumps(report, indent=2))
    for key in ("problems", "top_level_differences", "field_differences"):
        for line in result[key][:25]:
            print(f"  {key.upper()}: {line}")
    return 1 if result["problems"] or result["field_differences"] or result["top_level_differences"] else 0


def main(argv: list[str]) -> int:
    if argv[1:2] == ["real"]:
        dump = Path(argv[3]) if argv[2:3] == ["--dump"] and len(argv) > 3 else None
        return real(dump)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
