"""``pz`` — the Project Zero command line.

    pz intake submit DELIVERY.json [--by NAME]   validate, record and resolve one delivery (Grok's path)
    pz intake check  DELIVERY.json               validate only; touches nothing

Exit codes: 0 accepted or duplicate (already delivered), 2 rejected (nothing written), 3 intake not open yet
(before the legacy import), 1 unexpected error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from projectzero.dealflow.intake.contract import validate_external
from projectzero.dealflow.intake.service import IntakeResult


def _load(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        sys.exit(f"file not found: {path}")
    except json.JSONDecodeError as exc:
        print(f"REJECTED - not valid JSON: {exc}")
        sys.exit(2)


def _print_result(result: IntakeResult) -> None:
    print(f"{result.outcome.upper()} - sha256 {result.sha256 or '-'}")
    for issue in result.issues:
        print(f"  refused {issue}")
    for index, issues in result.refused:
        for issue in issues:
            print(f"  refused entity {index}: {issue}")
    for r in result.resolution:
        print(
            f"  [{r['index']}] {r['name']} ({r['kind']}): {r['result']} candidate {r['candidate_id']} "
            f"- company {r['company_decision']}"
        )


def _submit(path: str, submitted_by: str | None) -> int:
    from projectzero.core.config import Settings
    from projectzero.core.db import transaction
    from projectzero.dealflow.intake.postgres import IntakeClosedError, PostgresIntake
    from projectzero.dealflow.intake.service import IntakeService

    payload = _load(path)
    settings = Settings.from_env()
    by = submitted_by or (payload.get("origin") if isinstance(payload, dict) else None) or "unknown"
    try:
        with transaction(settings.db_url) as conn:
            store = PostgresIntake(conn, settings.schema)
            result = IntakeService(store, resolver=store).submit_external(payload, submitted_by=str(by))
    except IntakeClosedError as exc:
        print(f"CLOSED - {exc}")
        return 3
    _print_result(result)
    return 2 if result.outcome == "rejected" else 0


def _check(path: str) -> int:
    issues = validate_external(_load(path))
    if issues:
        print("REJECTED")
        for issue in issues:
            print(f"  {issue}")
        return 2
    print("VALID - would be accepted (nothing was written)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pz", description="Project Zero command line")
    groups = parser.add_subparsers(dest="group", required=True)
    intake = groups.add_parser("intake", help="deliver leads into Deal Flow").add_subparsers(dest="cmd", required=True)
    submit = intake.add_parser("submit", help="validate, record and resolve a delivery")
    submit.add_argument("file")
    submit.add_argument("--by", help="who submits (default: the delivery's origin)")
    check = intake.add_parser("check", help="validate only")
    check.add_argument("file")
    args = parser.parse_args(argv)
    if args.cmd == "submit":
        return _submit(args.file, args.by)
    return _check(args.file)


if __name__ == "__main__":
    raise SystemExit(main())
