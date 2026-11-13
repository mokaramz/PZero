# 032c — Plan: the background-jobs runner (catch-up, the scheduled task, Run overdue now)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-325) — implementation next

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

## Grok notes
