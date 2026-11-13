# 032c — Plan: the background-jobs runner (catch-up, the scheduled task, Run overdue now)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-325) · implementation APPROVED (H-333)

## Why
The [port order](../PORT_ORDER.md) says "the background-jobs port (the scheduled event scan, catch-up) runs alongside
10–13". System health (032a) shows the jobs as the imported snapshot, through the switch `RUNNER = None`. This review
ports the runner, so the jobs that are ported actually run.

**The old runner.** It is `services/scheduler.py` (718 lines), and it is triggered three ways:
- the in-app catch-up at startup (`start_catch_up`, after a 4-second delay);
- the Windows task "Project Zero - background jobs", which runs hourly, at logon and at unlock. It is registered
  DISABLED by `scripts/background/install-background-task.ps1` and runs `python -m projectzero --background`;
- `POST /api/catchup_run {only?}`.

One lock file, `schedule/run.lock` (a pid plus a token, broken only when its pid is dead), keeps these runs from
overlapping. Jobs run one after another, and one failure never stops the rest. State and history go to
`schedule/jobs.json`, `runs.jsonl` and `runner.json`.

**Which jobs have a NEW equivalent.** Of the 15 old jobs, 4 are the retired Scout jobs, already dropped by 032a (c).
Of the other 11:

| job | interval | NEW |
|---|---|---|
| event_scan | 72 h | `events.scan.scan`: ported (its own advisory lock; 409 when busy) |
| news_refresh | 24 h | `news.runs.refresh_run(trigger="scheduled")`: ported |
| news_source_review | 720 h | `news.runs.evaluate_run` with `record_history`: ported |
| news_weekly_review | 168 h | `news.core.weekly_review` (pure) + `evaluate_run`: **the weekly record writer is added here** |
| validation_snapshot | 24 h | `validation.core.snapshot_series` (pure): **the snapshot writer (`validation_log`, `snapshots`) is added here** |
| watch_checks, deal_flow_scan, triage_retry, source_network, triage_compression, case_refresh | — | NOT ported: they need the watch sensors, the scan, the triage, the source-network and the case-preparation ports |

## Scope of 032c
1. **`jobs/`.** The runner, `run_due(source, only)`, ported line for line over the database:
   - the due list computed INSIDE the lock (`plan`, already ported in `health/`);
   - jobs run sequentially in `JOBS` order, and one failure never stops the rest;
   - each result classified (`classify`, ported) and recorded: `fails_in_row`, `last_ok` only on success, and the
     history row;
   - a missed interval runs once.

   `dry_run` and `status` are ported too.
2. **The state lives in the database:**
   - `pz.job_state` for each job's record (`detail` keeps the old record whole);
   - `pz.job_runs` for the history, append-only. A NEW row has its real `started_at` and `finished_at`, and `detail` is
     the old line;
   - a new `pz.job_runner` for the old `runner.json`: one row per source (`app`, `background`, `manual`, `cli`), kept
     as `json` so the key order survives.
3. **The lock is a Postgres session advisory lock on a dedicated connection**, `pg_try_advisory_lock(<schema>.jobs)`.
   - It replaces `run.lock` and the pid-liveness checks: the lock dies with its connection, so it can never be left
     stale.
   - The holder (source, pid, since) is written to `job_runner` for the status display. `lock_status` reads `pg_locks`
     plus that row.
   - A busy lock records the old `skipped` row and runs nothing.
4. **`recover_on_start`.** At app start, and at the start of every `--background` run, under the lock: any job whose
   record is `running` while no runner holds the lock becomes `interrupted`, with the old note.
5. **Triggers:**
   - the in-app catch-up at startup (the old 4-second delay; only overdue jobs);
   - `python -m projectzero.jobs --background` (and `--dry-run`, `--run-due`) for a Windows task;
   - `POST /api/catchup_run {only?}`, whose answer is `{started: false, reason: "already running"}` when busy;
   - `GET /api/catchup`, which returns the status for the old `CatchUpBanner`.

   The switches stay: `PZ_CATCHUP` off, and `config.json` `catch_up.enabled` / `intervals_h`.
6. **The page.** The `CatchUpBanner` is ported, and its "Project Zero runs on your computer" sentence is reworded
   (noted in 033a). System health's "Run overdue now" is enabled for the ported jobs, and the runner line in
   Diagnostics is restored.
7. **A new Windows task script**, `scripts/background/install-background-task.ps1` for the NEW app. It is registered
   DISABLED by default, under a NEW name: "Project Zero v2 - background jobs".

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) The live schema stays closed until the import.** Every ported job writer already refuses `pz` before the
  import marker (`ensure_intake_open`). The runner checks it FIRST: on `pz` before the import it runs nothing and
  records nothing. (It cannot record in `pz` either.) The catch-up, the CLI and the route answer that the live import
  has not run.
- **(b) The 6 unported jobs never run.**
  - They stay in `JOBS`, so their imported history and timestamps remain visible, but the runner skips them.
  - Their plan rows say "not ported yet" in place of "overdue", and "Run overdue now" never includes them.
- **(c) The health texts, per job (Codex H-307).** `RUNNER` becomes the real runner, whose `ported(job_id)` says which
  jobs it can run.
  - System health restores the old texts and groups (032a k) ONLY for those jobs.
  - The 6 unported jobs, the Deal Flow scan advice (rule 3) and the triage retry (rule 4) keep their revision 2
    wording until their own ports.
  - Rule 1 never regains the repair research job.
- **(d) Paid calls stay Mohamed's switch.** `news_refresh` calls the model only through the gateway; with paid calls
  off the cards are skipped as before. No job changes `PZ_AI_PAID`.
- **(e) The background backup (`background_backup`) is 032b's** (hardening). The runner does not call it. The old
  `--background` step "backup when something is overdue" is declared and omitted.
- **(f) Mohamed's actions at the cutover.** Nothing here touches the existing task "Project Zero - background jobs",
  which runs the OLD app. The new task is registered DISABLED under its new name. At the cutover Mohamed:
  1. pauses the old task, as the live-import plan already requires;
  2. runs the import;
  3. enables the new task.
  This review only documents those steps; it does not do them.
- **(g) Two runners at once** (the app and the task) are kept apart by the one advisory lock. The old in-process
  `STATE` and the thread lock stay for overlapping catch-ups inside one process.

## Verification
- **Oracle:** the old `run_due` / `plan` / `classify` / `recover_on_start` / `dry_run` over invented jobs (the old
  test pattern: fake jobs, a frozen clock). The cases cover:
  - ok, failed twice in a row, budget_blocked, partial, waiting_external and no_findings;
  - a missed schedule run once;
  - a busy lock giving `skipped`;
  - an interrupted job recovered;
  - `only=`;
  - the dry run writing nothing.

  The new runner, over the same fake jobs in a scratch schema, must record the same `job_state` records, the same
  history lines and the same `runner` records. Expect 0 differences, with the lock (a) and the backup (e) declared.
- **Hosted:**
  - two runners at once (the app thread and a second process) never run the same job, and the second records
    `skipped`;
  - a runner whose connection dies leaves no lock, and the next start recovers its `running` job;
  - every ported job runs once through the runner in a scratch schema with fixture transports (no network, no model);
  - the live-schema refusal (a) is checked through `ensure_intake_open` on a schema with no import marker, by
    pointing the check at a scratch name;
  - the unported jobs are never run (b).
- **Browser:**
  - the `CatchUpBanner` while running and when done;
  - "Run overdue now" runs only the ported overdue jobs, and the banner shows them;
  - the health texts restored only for the ported jobs (c), and the forbidden phrases still absent for the others.
- **No live run:** the tests and the preview use scratch schemas and fixture fetchers only. The Windows task is never
  registered by a test.

## Questions for Codex
1. (a): is refusing on `pz` before the import, recording nothing, the right behaviour for the runner?
2. (b) / (c): keep the 6 unported jobs visible as "not ported yet" with the per-job text switch?
3. (f): is the new task name, registered disabled, the right cutover shape?

---

## Codex review

**H-320 verdict — REQUEST CHANGES to the recovery and import plan.** Yes to all three decisions. Check the import marker before any live dispatch or bookkeeping, including recovery and busy-run records. Keep the six unported jobs and their history visible with the per-job availability label. The distinct, initially disabled Windows task supports the proposed manual cutover.

1. Define what happens when the lock connection dies while the worker is still alive. Event scan and news refresh use their own connections. Releasing the scheduler lock can admit a replacement while the first worker can still finish or dispatch its next job. Specify how the replacement handles an in-flight job and how ownership is checked atomically for job claims and completion. In a scratch test, pause worker A inside a job, drop only its lock connection, let B recover, then resume A. Verify that A cannot overwrite B’s state or dispatch another job and that recovery cannot repeat a committed job effect.
2. Preserve the imported runner display. `health/inputs.py` currently reads `schedule/runner.json` from the archive. Specify how the new table inherits those per-source records, or overlay new rows on the archived values by source. Test that the first new manual run updates the manual entry while the imported background entry stays visible in both diagnostics and catch-up status.

### Claude — plan revision 2

Codex's points are taken. (a) is widened: the import marker is checked before ANY live dispatch or bookkeeping,
including recovery, a busy run's `skipped` record, and a runner record. On `pz` before the import the runner writes
nothing at all.

**1. A fencing generation makes the advisory lock safe when its connection dies.**
- **The lease.** A new one-row table, `pz.job_lease (generation bigint, holder json, taken_at)`. On taking the advisory
  lock, the runner increments `generation` in one transaction and keeps its own value, `G`. Every later bookkeeping
  write is CONDITIONAL on `G` still being current. A worker whose lock connection died is replaced by a runner holding
  a larger generation, so its writes stop at once.
- **Claiming a job** (before dispatch) is ONE transaction that:
  - reads the lease `FOR UPDATE`;
  - checks `generation = G` (otherwise the worker stops: no claim, no dispatch);
  - writes the job's record as `running` with `"generation": G` in its `detail`.
- **Completing a job** is ONE transaction of the same shape: the lease `FOR UPDATE`, then a check that `generation = G`
  AND that the job record is still `running` with `generation = G`. Only then are the outcome, the history line and
  `fails_in_row` written. A stale worker's completion writes nothing, and that worker dispatches no further job.
- **Recovery** (by the runner holding the larger generation): a job recorded `running` under an OLDER generation
  becomes `interrupted`. That runner then plans normally.
- **A committed job effect is never repeated:**
  - **The jobs with their own lock and their own "last run" source** (event_scan through its scan lock and
    `event_health.scan_time`; news_refresh, news_source_review and news_weekly_review through the News run lock and
    their logs). While the stale worker's job is still running, a second dispatch is refused by that job's lock and
    recorded as a failure (no effect). Once the job has committed, `plan` reads its `last()` and the job is not due.
  - **The two new writers are idempotent by key.** validation_snapshot writes at most one snapshot line per Berlin
    date. news_weekly_review records at most one review per ISO week. Each is a no-op when its key is already
    present, checked inside its own transaction.
- **Regression, hosted, in a scratch schema with fake jobs:**
  1. Worker A claims job J1 and pauses inside it (a seam).
  2. Only A's LOCK connection is terminated (`pg_terminate_backend`).
  3. Runner B takes the lock (a larger generation) and recovers J1 to `interrupted`. J1's effect has not committed
     yet, so B runs J1 itself; the fake J1 is idempotent by key, as the real writers are.
  4. A resumes: its J1 effect commits idempotently, its completion is refused, and it does not dispatch J2.
  5. Checks:
     - J1's committed effect exists exactly once;
     - B's state for J1 and J2 stands;
     - no history line comes from A after the cut;
     - A stopped.

   A second variant has J1 commit BEFORE B plans, so B finds J1 not due through its `last()` and does not run it
   again.

**2. The imported runner records stay visible, overlaid per source.**
- The archived `schedule/runner.json` (the byte-exact archive, already read by `health/inputs.py`) stays the base.
- The new `job_runner` rows (`source` as the key, `record json`) OVERLAY it by source: a source the new runner has
  written shows its new record, and every other source keeps its imported record, in the archived key order.
- System health's diagnostics and `GET /api/catchup` read the same overlay through ONE reader.
- **Sources:** the route keeps the old source (`POST /api/catchup_run` ran as `app`), and so does the CLI
  (`--background` as `background`, `--run-due` as `cli`).
- **Regression, hosted, on an imported world** with a `runner.json` holding `background` and `app` records: the first
  new run under one source updates that source's entry in both the diagnostics and the catch-up status, while the
  imported entry of the other source stays visible, unchanged and in its place.

### H-322 revision 2 verdict

**REQUEST CHANGES on dispatch only.** The generation checks address stale bookkeeping. The per-source overlay and its regression address imported status.

The event scan lock serializes scans, but it cannot invalidate an earlier due decision. Suppose A holds the event scan lock and B takes over the scheduler. B sees the old scan time and claims the overdue job. A then commits and releases the event lock before B enters `events.scan.scan`. B can now acquire that lock and run a second scan. The two proposed tests put A’s commit on either side of this gap and use an idempotent fake.

For scheduled runs, specify a check of ownership and current eligibility after taking the job-specific lock and before starting work, or an equivalent atomic claim for the same due occurrence. Cover the reverse order too, where stale A reaches the job after B finishes. Test the commit-between-plan-and-dispatch case using a counted, non-idempotent effect and assert one execution. For the date/week writers, specify a unique key or equivalent serialization so concurrent transactions cannot both pass the absence check.

### Claude — plan revision 3

Codex's ordering is taken: a due decision made before the job-specific lock can be stale by the time that lock is
held. So eligibility is re-checked AFTER the job's own lock is taken and BEFORE any work.

**A due occurrence, checked under the job's own lock.**
- **Planning** records, for each due job, the occurrence it decided on: the job's `last()` value at planning
  (`last_seen`: the scan time, the News run's time, the snapshot date, the review week) and the runner's generation
  `G`.
- **The job's entry point takes a `still_due(conn)` check** and runs it right after acquiring its OWN lock, before
  fetching or writing:
  - `events.scan.scan`, after its scan lock;
  - `news.runs.refresh_run` / `evaluate_run`, after the News run lock;
  - the two new writers, after their transaction lock.
- **`still_due` is true only if both hold:**
  - the lease's generation is still `G`, so this runner owns the scheduler;
  - the job's `last()`, re-read on the locked connection, still equals `last_seen`, so nobody ran this occurrence
    meanwhile.

  Otherwise the job does nothing. It returns the old `skipped` note "skipped — already ran" (classified `skipped`, no
  effect), and the runner's completion records it as such, or writes nothing if the runner is stale.
- **Both orders are covered:**
  - **The predecessor commits between the replacement's plan and its dispatch.** B takes the job lock after A
    released it, re-reads `last()`, finds A's newer value, and skips.
  - **The reverse: stale A reaches the job after B finished.** A's claim fails on the generation, so A does not
    dispatch. If A had already claimed before B's takeover and enters the job after B finished, `still_due` fails on
    BOTH the generation and `last()`, and A skips.
- **Manual runs** (`only=`) use the same check: an explicit run still runs one occurrence only.

**The date and week writers are serialized, not just checked.**
- **validation_snapshot** takes `pg_advisory_xact_lock(<schema>.validation.snapshot)` in its write transaction,
  checks that no `snapshots` line has the Berlin date, then appends. Two transactions for the same date are
  serialized, and the second finds the first's line.
- **news_weekly_review** works the same way with `<schema>.news.weekly` and the ISO week.
- The lock is held to commit, so the absence check and the insert cannot interleave.

**Regressions (hosted, scratch schema, fake jobs with a COUNTED, non-idempotent effect):** each execution inserts a
row into a counter table, and the job has its own lock and a `last()` that the effect updates.
1. **The commit falls between plan and dispatch.**
   - A holds the job lock mid-effect.
   - A's scheduler lock connection is cut, and B takes over, plans (it sees the old `last()`) and claims the job.
   - A commits (counter 1, `last()` advanced) and releases the job lock.
   - B acquires the job lock, `still_due` sees the new `last()`, and B skips.
   - **Expected:** the counter is exactly 1, and B's record for the job says skipped (already ran).
2. **The reverse.**
   - A claims and then pauses before the job lock.
   - B takes over, runs the job (counter 1) and finishes.
   - A resumes: it is refused at the job lock by `still_due`, or earlier at its claim.
   - **Expected:** the counter is exactly 1, and nothing is recorded by A.
3. **Concurrent date writers:** two transactions write the same date's snapshot at once, released together. Exactly
   one line is written.

These replace revision 2's two variants, which used an idempotent fake. The fencing (revision 2, point 1) and the
runner overlay (point 2) stand.

### H-324 revision 3 verdict

**APPROVE for implementation.** Checking the generation and the planned occurrence under the job’s own lock closes both dispatch races from H-323. Holding the date or week writer’s transaction lock through commit serializes its check and insert. The proposed counter tests make a duplicate execution observable in either worker ordering. At implementation review, show the counter and job-history results for both orderings and the row count for concurrent snapshot writes.

### Claude — implementation

**Migration 0023**
- **`job_lease`:** one row; `generation` can never decrease (a trigger refuses a delete or a lower value); `holder json`;
  `taken_at`.
- **`job_runner`:** `source` is the primary key, plus `record json`, `created_at` (the order of first writing) and
  `updated_at`.
- **`job_runs`:** new rows get real `started_at` / `finished_at` from `clock_timestamp()`, a check requires
  `finished_at >= started_at`, and updates are refused, so the history is append-only.
- RLS is on, the revokes are applied, and the lock keys are built from the schema name, so there is no `pz.` string to
  rewrite.

**The runner** (`jobs/`: `runner`, `store`, `catalog`, `ported`, `writers`, `__main__`; plus `core/occurrence.py`)
- **The lock:** `pg_try_advisory_lock(hashtext('<schema>.jobs'))` on a dedicated autocommit session. Taking it bumps
  the generation `G` in one statement.
- **Claiming and completing a job** are each one transaction. The transaction locks the lease row and requires
  `generation = G`; completing also requires the job record to be `running` with `"generation": G`. Runner records
  follow the same rule. A stale worker raises `Stale`: it writes nothing and dispatches nothing more.
- **The occurrence check.** Planning records each due job's `last_seen` under `G`. `still_due(conn)` runs on the
  job's OWN lock connection and passes only with the same `G` and an unchanged occurrence; otherwise the job records
  "skipped — already ran" (`AlreadyRan`). The `last()` sources are:
  - event_scan: `event_health.json` (scan time and `updated_at`);
  - news_refresh: the newest `runs` line;
  - news_weekly_review: the newest `weekly` line;
  - validation_snapshot: the newest `snapshots` line;
  - news_source_review: a `run_notes` mark `{"source_review": true}`. The weekly evaluation also appends a
    `source_history` line, which would otherwise have skipped the monthly review in the same run.
- **The hooks** (default `None` means no check): `events.scan.scan(..., still_due=)`,
  `news.runs.refresh_run(..., still_due=)` and `evaluate_run(..., still_due=)`.
- **The writers:**
  - `record_weekly` (`<schema>.news.weekly`): one record per ISO week;
  - `record_snapshot` (`<schema>.validation.snapshot`): one per Berlin date, the old line.

  Each holds its transaction lock to commit. The snapshot writer refuses when ANY line already has the date; the old
  code checked only the last line, so this is stricter.
- **(a):** the import marker is checked first everywhere: `run_due`, recovery, the busy run's `skipped` record, every
  fenced write, the catch-up, the route and the CLI.
- **(b):** the six unported jobs are not in the catalog. Their plan rows are `overdue: false` with
  `availability: "not ported yet"`, and the page reads that field.
- **(e):** no backup.
- **Recovery, added after the build:** `recover_on_start` also marks a `job_runner` record left `running` as
  `interrupted`. That covers a stale worker of another source, so the diagnostics never show a run that will never
  finish. Imported records are untouched.
- **The overlay:** `store.runner_records` is the ONE reader, used by health and `/api/catchup`. It starts from the
  archived `runner.json` and overlays the `job_runner` rows by source; an existing source keeps its place.

**Triggers**
- `GET /api/catchup` returns the old `status()`: `{running, queue, current, done, started, finished, enabled, plan,
  lock, runners}`.
- `POST /api/catchup_run {only?}` returns `{started: true}`, `{started: false, reason: "already running"}`, or the
  import refusal.
- `python -m projectzero.jobs --background | --run-due | --dry-run | --lock-status`. The exit codes are 0, 2 and 3,
  and `--lock-status` exits 0 when the lock is free, 10 when it is held. It only reads.
- The app-start catch-up runs in a thread after 4 seconds. It is off under the tests, and the preview runs it with
  `PZ_CATCHUP=0`.
- **Declared:** `--background` prints the old `background.log` line rather than writing that file.

**System health.** `RUNNER` is now `jobs.ported.RUNNER`, held at the generation that owns the lock.
- The old texts and groups come back only for the ported jobs.
- Rules 3 and 4 and the six unported jobs keep revision 2's wording, and rule 1 has no repair research.
- `parity_health check`: MATCH, with the runner switch and the per-job switch matching too.

**Page**
- `features/jobs/CatchUpBanner` polls every 2.5 seconds while running and every 60 otherwise, and stops on a 404. Its
  sentence is reworded: "Project Zero runs its periodic work (scans, news, snapshots) in this catch-up when the app
  opens, and in the optional Windows task “Project Zero v2 - background jobs”, registered disabled until the
  cutover." The rest is verbatim.
- "Run overdue now" is enabled when the runner is live, meaning the lock is a real object. It sends `only` = the
  ported overdue jobs only. `started: false` shows its reason.
- Unported rows say "not ported yet" in the diagnostics, the job matrix, the pipeline and the drawer, and keep their
  history. The deferred fallback from 032a stays for a payload without a runner.

**The Windows task scripts** (`scripts/background/`: `install-background-task.ps1`, `run-background.ps1`,
`deploy-release.ps1`, `runtime-check.ps1`; plus `scripts/ensure_python_env.ps1`)
- They are the old scripts, adapted to the v2 task name and to an explicit `-EnvFile`, whose values are never shown.
  The deploy waits on `--lock-status` instead of `run.lock`. The log and the deployment record go to
  `%LOCALAPPDATA%\ProjectZero\v2`.
- They refuse the OLD task's name, register DISABLED, and keep the old production-runtime rules: a clean clone at a
  `pz-release-*` tag that records ALL CHECKS PASSED.
- All five parse in Windows PowerShell 5.1 and are ASCII-only. None was run: registering, enabling and deploying are
  Mohamed's steps at the cutover (f).

**Counted regressions** (`test_jobs_hosted.py`, 11 tests, all pass)
- **Revision 2, lock connection cut:** after A's lock connection was terminated, the lock read free. B recovered
  `["j1"]` (generations A=1, B=3) and ran j1 and j2. A dispatched nothing (`results=[]`). The keyed rows were
  `[('j1:2026-11-13','app'), ('j2:2026-11-13','app')]`, and the history holds j1 and j2 by `app` only.
- **Order 1, A commits between B's plan and dispatch:**
  - counter = **1** (`[('j1','background')]`);
  - B's history row: `('j1','app','skipped','skipped — already ran','ok',finished)`;
  - A recorded nothing.
- **Order 2, stale A after B finished:**
  - j1 counter = **1** (rows `[('j1','app'), ('j2','app')]`; j2 is B's own run);
  - the history holds j1 and j2 completed by `app`;
  - A recorded nothing, and its final runner record was refused.
- **Concurrent same-date snapshot writers:** the results were `[False, True]`, and **1** line was written. The weekly
  writers likewise wrote one record.
- **Two runners:** in one process, the second got `skipped` and the counter was 1. As TWO OS PROCESSES (added after
  the build): `python -m projectzero.jobs --run-due` in a separate process exits 0 and records `cli: skipped`, and the
  counter stays 1.
- **Every ported job once, with fixture transports:**
  - event_scan completed;
  - the snapshot was recorded;
  - news_refresh was partial (the fixture leaves 9 feeds unanswered);
  - the weekly review and the source review completed;
  - the six unported jobs never ran.
- **(a):** no row in any table changed.
- **The overlay:** the order stayed `["background", "app"]`; the imported background entry is unchanged and `cli` is
  appended.
- **A stale runner record:** recovery marks it `interrupted`.

**Two existing hosted tests, fixed here** (both failed the same way at HEAD)
- **`test_health_hosted[main]`:** it expected the old inbox count, but the overview counts the merged Deal Flow
  (H-309). My H-309 revision re-ran only the new case and the real parity, not this one. The imported-world test now
  takes the expected `pipeline.inbox` from `GET /api/deal-flow/inbox`, as the real parity does.
- **`test_events_scan_hosted` (the deadline cutting off a trickling source):**
  - Its 8-second budget left 2 seconds for the write. Since H-284 the write never connects with less than the 2-second
    minimum, so against the hosted pooler it answered 503.
  - The budget is now 16 seconds (the write gets 4). The trickle alone takes 100 seconds, so the test still proves the
    cut-off.

**Verification (all pass)**
- `parity_jobs check`: MATCH. `parity_jobs hosted`: MATCH, with 0 differences over 8 cases and 37 steps against the old
  `run_due` / `plan` / `classify` / `recover_on_start` / `dry_run`.
- `parity_health check`: MATCH, with every switch.
- **Hosted:** jobs (11), health (all), events scan (all).
- **PGlite:** 73, with the new 0023 tests.
- **Vitest:** 907.
- **E2e:** `jobs-mocked`, `health-mocked` and `health.spec` give 38 passed and 1 skipped (the live-runner case on the
  preview payload).
- **Gate:** backend 1,870, frontend 907, PGlite: ALL CHECKS PASSED.

### H-326 implementation verdict

**REQUEST CHANGES before commit.** I inspected the two counted race tests and their history assertions, the transaction locks on the snapshot and weekly writers, and the disabled Windows task definition. All seven offline jobs tests passed on my rerun. The hosted and full-suite results above are Claude’s runs.

1. **Report cross-process contention accurately.** The approved route contract returns `started: false` when the scheduler is busy. `runner.start_manual` checks only the in-process running flag after the import guard. When the CLI holds the database lock, the route returns `started: true` and its new thread subsequently skips. Have the worker communicate the actual lock acquisition result before the POST answers. Test the POST while a separate process holds the lock and verify the busy response, zero dispatches and the expected skipped record.
2. **Keep the scheduled task on a verified runtime after a failed deployment.** In `deploy-release.ps1`, loading the environment happens after disabling the task and before the restoration block. A missing database setting therefore leaves a previously enabled task disabled. Conversely, an environment-build or import-check failure after checkout reaches a `finally` that re-enables the task on the failed release. Validate inputs before pausing and only resume against a verified runtime. Stage the new runtime separately or restore and verify the prior runtime before resuming. Exercise both failures with mocked Task Scheduler commands and a disposable runtime.

### Claude — implementation revision 2 (H-327)

Both of Codex's points are taken.

**1. `POST /api/catchup_run` reports contention across processes truthfully.**
- `runner.start_manual` now takes the scheduler lock ITSELF, synchronously, before it answers.
  - **When another runner holds the lock** (this process or another one), the route writes the old busy record
    (`app: skipped`, "skipped — another run is in progress (…)") and answers
    `{started: false, reason: "already running"}`. Nothing runs, and the in-process flag is cleared again.
  - **Otherwise** it hands the lease it already holds to `run_due(..., lease=)` in the thread, then answers
    `{started: true}`.
- The busy path is now ONE function, `_record_busy`, shared with `run_due`.
- The thread always releases the lease it was given. Release is idempotent, so this also covers a `run_due` that
  raised before its own `try`.
- **Regression** (hosted, `test_the_manual_route_answers_busy_while_another_process_holds_the_lock`): a SEPARATE OS
  process holds the scheduler lock, and the POST checks:
  - the answer is `{started: false, reason: "already running"}`;
  - `job_state` is unchanged and `job_runs` has the same count: zero dispatches;
  - the `app` runner record is `skipped` with the busy note;
  - the in-process flag is cleared;
  - once the holder exits, the same POST answers `{started: true}`.

**2. A failed deployment leaves the task on a verified runtime, or disabled.**
- `deploy-release.ps1` is now a thin wrapper over `deploy-lib.ps1` (`Invoke-PzDeploy`).
- **Every input is validated BEFORE the task is paused:** the tag and its passed-gate record, the env file and its
  `SUPABASE_DB_URL`, the lock-status Python, and an existing runtime (clean, marked `pz.runtime`). A failure says
  "nothing changed", and the task is not touched.
- **On a failed environment build or import check** after the checkout, the PREVIOUS release is checked out again,
  its environment is prepared and it is verified again: the runtime rules and the import check.
  - The task is resumed only if that verification passes.
  - When no verified runtime remains (a failed first deployment, or a previous release that no longer verifies),
    the task is left DISABLED and the failure says so.
- **Its outside effects are small functions** (`Get-PzTaskEnabled`, `Set-PzTaskEnabled`, `Invoke-PzLockStatus`,
  `Invoke-PzEnsureEnv`, `Get-PzRuntimeCodePath`), so a test can mock them.
- **Regression:** `scripts/background/tests/deploy-release.tests.ps1` mocks Task Scheduler and Python and uses
  disposable git repositories, with three tags: two that passed the gate and one that did not. All 8 cases pass:
  - a missing database setting fails before the pause, and the task is untouched;
  - a tag without a passed gate fails before the pause;
  - a failed FIRST deployment leaves the task disabled;
  - a successful deployment pauses, then resumes, on the verified release;
  - an environment-build failure restores and verifies the previous release, then resumes the task;
  - an import-check failure does the same;
  - a previous release that no longer verifies leaves the task disabled;
  - a later successful deployment moves to the new release.
- The test runs in the gate (`scripts\check.ps1`, step "scripts: deploy-release tests").

**Re-run, all pass:**
- the jobs hosted tests (12, with the new busy-route case) and the offline jobs tests (7);
- the 8 deploy cases;
- the gate: backend, frontend 907, PGlite and the deploy tests — ALL CHECKS PASSED.

### H-328 implementation verdict

**REQUEST CHANGES on release identity.** The manual route now acquires the database lease before answering and passes it to the worker. The revised deployment validates the environment before pausing and checks the restored runtime before resuming after a reported build or import failure.

The deployment still has a path to enabling the wrong release. `Invoke-PzDeploy` resolves the approved commit in the development checkout, but ignores the exit status of `fetch --tags`. If the runtime already has a conflicting tag of the same name, Git can reject the fetch and leave the old tag in place. `Set-PzRuntimeTo` then compares runtime HEAD with the **runtime’s own tag**, so that check can pass. The task resumes and the deployment log records the development commit even though the runtime is on a different commit.

Require a successful fetch, check out the exact approved commit, and compare runtime HEAD with that commit before logging success or resuming. Add a disposable-repository test with conflicting same-name tags. Verify the task resumes only on the approved commit or the verified previous release and that no deployment record claims a commit absent from runtime HEAD. This finding is from code inspection. The eight mocked deployment cases and hosted busy-route result are Claude’s reported runs.

### Claude — implementation revision 3 (H-329)

Codex's point is taken: the release identity is now verified against the APPROVED development commit, never against
what a name resolves to in the runtime.

**The fix** (`deploy-lib.ps1`):
- The fetch of the release tags must succeed. A fetch git rejected, such as a conflicting tag of the same name
  already in the runtime, is a failure: "the runtime could not fetch the release tags … (a conflicting tag?)".
- The runtime's `refs/tags/<tag>` must resolve to the approved commit (the one resolved in the development checkout).
- The exact approved commit SHA is checked out, not the tag name. `Set-PzRuntimeTo` compares HEAD with that SHA
  itself.
- HEAD is compared with the approved commit once more before the deployment is recorded or the task resumed.
- Any of these failures takes the existing path: the previous release is restored and verified, and the task resumes
  only on it; otherwise the task stays disabled.

**Found while testing, also fixed** (`runtime-check.ps1`): a commit can carry several tags. `git describe
--exact-match` picks one, so a release that also carries an unchecked tag could be refused. HEAD now counts as a
release when ANY `pz-release-*` tag pointing at it records a passed gate. The release label shows that tag.

**Regression:** `deploy-release.tests.ps1` has a ninth case, "a conflicting same-name tag in the runtime never
resumes on the wrong commit".
- The runtime holds its own `pz-release-2` annotated on release 1's commit, and the test checks the conflict exists.
- Deploying `pz-release-2` fails on the refused fetch (the assertion requires that message), and the previous release
  is restored and verified.
- The runtime HEAD is release 1, and the task was paused and resumed exactly once (`False,True`).
- No deployment record was added, and no record names a commit absent from the runtime HEAD.
- The final success case now also checks that the last record's commit equals the runtime HEAD.

(Checked directly, with git 2.55: a `fetch --tags` meeting a conflicting tag exits 1 and keeps the runtime's tag.)

**Re-run, all pass:** the 9 deploy cases; the gate: backend, frontend 907, PGlite 73 and the deploy tests — ALL CHECKS
PASSED.

### H-330 implementation verdict

**REQUEST CHANGES on the runtime tag check.** The exact-commit fix resolves H-329. The deployment checks the fetch result, verifies the runtime tag against the approved SHA, checks out that SHA and compares HEAD before logging success. The conflicting-tag regression asserts restoration of the previous HEAD, one resume and no new deployment record.

The revised multi-tag check in `runtime-check.ps1` also accepts a lightweight `pz-release-*` tag when its target commit message contains “ALL CHECKS PASSED”. For a lightweight tag, Git’s `%(contents)` reads the commit message. This lets runtime validation accept a checkout without the annotated gate record required by the installer and rollback path. Filter candidates to tag objects before reading their messages, and use the same selection in `Get-RuntimeProblem` and `Get-RuntimeRelease`. Cover a lightweight-only checkout whose commit message contains the phrase, then add a qualifying annotated tag at the same HEAD and verify it is selected. I inspected the regression and implementation. Claude reports all nine deploy cases passed.

### Claude — implementation revision 4 (H-331)

Codex's point is taken: only an ANNOTATED tag object carries a gate record.

**The fix** (`runtime-check.ps1`)
- One shared selection, `Get-PassedReleaseTags`, takes every `pz-release-*` tag at HEAD, keeps only tag objects
  (`git cat-file -t` = `tag`), and only then reads the tag's own message.
  - A lightweight tag is never read, because `%(contents)` would read its COMMIT message.
- `Get-RuntimeProblem` and `Get-RuntimeRelease` both use that selection. The release label shows the first qualifying
  annotated tag.
- The refusal now reads "no ANNOTATED release tag at HEAD (…) records a passed release gate".

**Regression** (`deploy-release.tests.ps1`, now 12 cases, all pass). Three cases on a disposable runtime clone whose
HEAD commit message contains "Release gate: ALL CHECKS PASSED":
- **a lightweight-only release tag** (`pz-release-lightweight`) is refused, and `Get-PassedReleaseTags` finds none;
- **an annotated tag WITHOUT the gate record** added beside it is still refused;
- **a qualifying annotated tag** added at the same HEAD is accepted. `Get-PassedReleaseTags` selects exactly
  `pz-release-annotated`, and `Get-RuntimeRelease` shows it.

**Re-run, all pass:** the 12 deploy cases; the gate: backend, frontend 907, PGlite 73 and the deploy tests — ALL CHECKS
PASSED.

### H-332 implementation verdict

**APPROVE revision 4 for commit.** The shared selector checks the Git object type before reading the gate message. A lightweight tag therefore cannot authorize a run through its target commit’s message. When a qualifying annotated tag shares HEAD with other tags, the release label selects it. The label can still display a tag from a rejected checkout for diagnostics. The installer, runner and deployment use the separate validity check before proceeding.

I inspected the three new regression cases and the callers. Claude reports all 12 deployment tests and the full gate passed.

## Grok notes
