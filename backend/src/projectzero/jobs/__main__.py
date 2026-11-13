"""``python -m projectzero.jobs`` — the background jobs from the command line (review 032c), the old
``python -m projectzero --run-due | --background [--dry-run]`` over the database (``SUPABASE_DB_URL``, the schema in
``PZ_SCHEMA``, default ``pz``):

    --run-due              run the overdue jobs once (source ``cli``), then exit
    --background           the unattended scheduled run (source ``background``): the recovery, then the overdue jobs
    --dry-run              (alone, or with either) list the due jobs and the lock; nothing runs and nothing is written
    --lock-status          one JSON line ``{"held", "source", "pid", "since"}``; never takes the lock, never writes

Exit codes (the old ones): 0 every job ok (or nothing due, or skipped because another run holds the lock);
2 a job failed; 3 refused: the live import has not run yet (decision a: nothing runs and nothing is recorded).
``--lock-status``: 0 the lock is free, 10 it is held. Declared: the old ``--background`` backup step is omitted (e,
032b's), and its ``schedule/background.log`` line is printed instead of appended to a file.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime

from projectzero.core.config import Settings
from projectzero.core.db import read_only_transaction
from projectzero.dealflow.intake.postgres import IntakeClosedError, ensure_intake_open
from projectzero.jobs import runner, store
from projectzero.jobs.catalog import Job, JobDeps

LOCK_HELD_EXIT = 10


def main(
    argv: list[str] | None = None,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    jobs: Sequence[Job] | None = None,
    deps: JobDeps | None = None,
    guard: runner.Guard | None = None,
    monotonic: Callable[[], float] = time.time,
) -> int:
    """``settings`` / ``now`` / ``jobs`` / ``deps`` / ``guard`` / ``monotonic``: test seams (default: the environment,
    the real clock and jobs, the network, the import marker, the duration clock)."""
    ap = argparse.ArgumentParser(prog="python -m projectzero.jobs", description="Project Zero background jobs")
    ap.add_argument("--run-due", action="store_true", help="run the overdue jobs once, then exit (source 'cli')")
    ap.add_argument("--background", action="store_true", help="the unattended scheduled run (source 'background')")
    ap.add_argument("--dry-run", action="store_true", help="list the due jobs and the lock; run and write nothing")
    ap.add_argument("--lock-status", action="store_true", help="print the runner lock as one JSON line (exit 10: held)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # never crash on a non-UTF-8 console (v1 bug)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = settings or Settings.from_env()
    db_url, schema = settings.db_url, settings.schema
    check = guard or ensure_intake_open
    if args.lock_status:
        lk = runner.lock_status(db_url, schema, now=now)
        print(
            json.dumps({"held": lk["held"], "source": lk.get("source"), "pid": lk.get("pid"), "since": lk.get("since")})
        )
        return LOCK_HELD_EXIT if lk["held"] else 0
    if args.dry_run:
        d = runner.dry_run(db_url, schema, now=now, jobs=jobs)
        lk = d["lock"]
        with read_only_transaction(db_url) as conn:
            closed = not runner.import_open(conn, schema, check)
        held = f"lock held by {lk['source']} pid {lk['pid']} since {lk['since']}" if lk["held"] else "lock free"
        print(f"DRY RUN — schema {schema} · scheduler {'enabled' if d['enabled'] else 'DISABLED'} · {held}")
        if closed:
            print("REFUSED (a real run): " + runner.IMPORT_REFUSED)
        for p in d["due"]:
            print(f"  DUE   {p['id']:20} last ok {p['last_ok'] or 'never'} · {p['state']}")
        for p in d["not_due"]:
            print(
                f"  later {p['id']:20} next {p['next_due']}"
                + (f" · {p['availability']}" if p.get("availability") else "")
            )
        print(f"{len(d['due'])} job(s) would run. Nothing was executed or written.")
        return 0
    if not (args.run_due or args.background):
        ap.print_help()
        return 2
    source = "background" if args.background else "cli"
    try:
        if args.background:
            with read_only_transaction(db_url) as conn:
                if not runner.import_open(conn, schema, check):
                    raise IntakeClosedError(runner.IMPORT_REFUSED)
                on = runner.enabled(store.config(conn, schema))
            if not on:
                print(
                    "Background run skipped: the scheduler is disabled (PZ_CATCHUP=0 or config catch_up.enabled=false)."
                )
                return 0
            runner.recover_on_start(db_url, schema, source=source, now=now, guard=check)  # never two at once
            # (e): the old "backup when something is overdue" step is 032b's (declared, omitted)
        results = runner.run_due(
            db_url, schema, source=source, now=now, jobs=jobs, deps=deps, guard=check, monotonic=monotonic
        )
    except IntakeClosedError:
        print("REFUSED: " + runner.IMPORT_REFUSED)
        return 3
    for r in results:
        print(f"{'OK ' if r['ok'] else 'ERR'} [{r.get('outcome', '')}] {r['label']}: {r['note']} ({r['seconds']}s)")
    ran = [r for r in results if r.get("job") != "*"]
    print(f"{len(ran)} overdue job(s) run." if ran else ("Skipped." if results else "Nothing overdue."))
    if args.background:  # the old schedule/background.log line (declared: printed, not appended to a file)
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        print(f"{stamp} ran={len(ran)} failed={sum(1 for r in ran if not r['ok'])} "
              + " | ".join(f"{r['job']}:{r.get('outcome')}" for r in results))  # fmt: skip
    return 0 if all(r["ok"] for r in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
