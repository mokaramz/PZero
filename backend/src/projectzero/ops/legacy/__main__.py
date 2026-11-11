"""``python -m projectzero.ops.legacy plan|rehearse|apply``.

* plan      — read the legacy folder, build every row in memory, write the reconciliation report. Writes nothing else.
* rehearse  — plan, then apply into a scratch schema on the hosted database, verify, drop the scratch schema.
* apply     — plan, then apply into ``pz`` in one transaction. Requires ``--confirm``; refuses if already imported.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from projectzero.core.paths import REPO_ROOT
from projectzero.ops.legacy.plan import ImportPlan, build_plan
from projectzero.ops.legacy.source import LegacySnapshot

REPORT_DIR = REPO_ROOT / "docs" / "team" / "import"


def _plan() -> ImportPlan:
    root = os.environ.get("PZ_LEGACY_DATA")
    if not root:
        sys.exit("PZ_LEGACY_DATA is not set")
    return build_plan(LegacySnapshot.capture(Path(root)))


def _write_report(plan: ImportPlan, name: str, extra: dict[str, Any] | None = None) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / name
    body = plan.report | {"secrets_found": plan.secrets_found} | (extra or {})
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return path


def _summary(plan: ImportPlan) -> None:
    print("rows per table:")
    for table, count in plan.counts().items():
        print(f"  {table:<22} {count:>6}")
    print(f"archive bytes: {plan.report['archive_bytes']:,}")
    identity = plan.report["identity"]
    print(
        f"companies: {identity['companies']} | merge suggestions: {identity['merge_suggestions']} "
        f"| strong-key conflicts: {len(identity['strong_key_conflicts'])}"
    )
    print("reconciliation:")
    for name, numbers in plan.report["reconciliation"].items():
        print(f"  {name}: {json.dumps(numbers, ensure_ascii=False, default=str)[:200]}")
    print(f"secret-looking values: {len(plan.secrets_found)}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m projectzero.ops.legacy")
    parser.add_argument("command", choices=["plan", "rehearse", "apply"])
    parser.add_argument("--confirm", action="store_true", help="required for apply")
    args = parser.parse_args(argv[1:])

    plan = _plan()
    _summary(plan)
    if args.command == "plan":
        print(f"report: {_write_report(plan, 'plan_report.json')}")
        return 0

    from projectzero.ops.legacy.apply import apply_plan, rehearse

    if args.command == "rehearse":
        result = rehearse(plan)
        print(f"report: {_write_report(plan, 'rehearsal_report.json', {'rehearsal': result})}")
        return 0 if result["passed"] else 1
    if not args.confirm:
        sys.exit("apply writes to the live pz schema: re-run with --confirm")
    result = apply_plan(plan, schema="pz")
    print(f"report: {_write_report(plan, 'apply_report.json', {'apply': result})}")
    return 0 if result.get("applied") or result.get("already_imported") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
