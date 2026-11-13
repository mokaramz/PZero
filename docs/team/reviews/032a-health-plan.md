# 032a — Plan: System health, the read side and the page

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-307) · implementation APPROVED (H-311)

## Why
System health (`/health`) is thirteenth in the [port order](../PORT_ORDER.md): "reports on everything else; the
read side first, then the background-job actions". It is the largest view so far.

**Sizes.**
- Old backend: `services/health.py` (653 lines) and `services/health_overview.py` (249).
- Old page: `features/health/`, about 2,700 lines with `Health.module.css` (933).
- The page also drives the old scheduler (`services/scheduler.py`, 718 lines, 15 jobs) and the hardening services:
  `backup` (265), `integrity` (194), `governance` (208), plus the source network.

**Where it sits in the plan.** This review covers the two reads and the page. The actions come in later reviews:
- **032b, hardening:** backups, integrity, governance and the source-network decisions. These must be redesigned for
  hosted Supabase: the old ones copied and checked a data folder.
- **032c, the background-jobs runner:** the scheduler and "Run overdue now".

**The reads.**
- `GET /api/system_health`: the verdict, status, issues, sources, coverage, jobs, spend, providers and
  diagnostics.
- `GET /api/system_health_overview`: the 30-day job history, the model calls and spend by day, the pipeline counts,
  and backups, integrity and releases.
- Both are pure reads in the old app. Neither makes a network or model call; the only cache is the in-process
  coverage cache.

## Scope of 032a
1. **The two GETs, key for key in the old order,** in ONE `snapshot_transaction` each at the Berlin request clock
   (`api/clock.berlin_request_now`, Codex H-299).
2. **The domain** (`health/`, pure, cut from `health.py` and `health_overview.py` by script with an AST check, as in
   030a) over one frozen `HealthInputs`:
   - the issue rules, `verdict`, `overall_status`, `source_health`, `diagnose`, the coverage summary, the overview
     aggregates;
   - the read side of the scheduler: the `JOBS` table, `plan`, `failing_jobs` and `run_state`, without the runner.
3. **One reader** (`health/inputs.py`) over the NEW tables and imported documents, mapped key by key below.
4. **The page** (`/health`), ported faithfully as in 030a / 031a: CSS byte-identical, the logic in `model/`, the
   panels in `components/`, the test ids kept.
   - Every action control keeps its place, disabled through `useDeferred`, with a VISIBLE reason (031a revision 2).
   - Every panel whose source is not ported shows its reason in place of data.

## Where each key comes from (NEW)
- **Ported, read directly:**
  - `coverage`: the summary re-derived from `ecosystems/coverage.coverage_view`, with the old fallback when it
    raises;
  - `triage_pending`: `dealflow.triage.view.pending_map`;
  - `validation`: `validation_log` snapshots and `validation.core.build`;
  - `spend`: `BudgetStore.totals` and `budget.limits`; same windows and rounding;
  - the news health: the News store, its logs, and the `news.sources` view family.
- **Imported, read through the new tables:**
  - `sources`: `pz.sources`, `documents['scan_history.json']` and the candidates;
  - `last_scan`: `scan_history.json`;
  - `research`: `documents['research_questions.json']`;
  - `job_runner.runners`: `documents['schedule/runner.json']`;
  - `jobs` / `overdue`: `pz.job_state.detail`;
  - the overview `jobs`: `pz.job_runs.detail`, which holds the whole old line;
  - `models`: `pz.model_ledger`;
  - `pipeline`: the candidates, `candidate_routing` with `queue_routing.json#rest`, and the conviction entries.
- **Absent in the new app:**
  - `selfcheck` (an in-process state);
  - `job_runner.lock` (a pid lock file);
  - `build` (the old release and stale-UI check);
  - `backups`, `integrity` and `releases` (032b);
  - `source_discovery` (the source network, 032b);
  - the watch checks' `failing_checks` (the watch sensors are not ported).

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Reads never write.** Neither GET writes. The coverage summary is computed per request inside the snapshot:
  there is no process cache.
- **(b) One clock.** The Berlin request clock is used for every age, window and "overdue".
- **(c) The retired Scout parts are dropped, with the issue rules that read them:**
  - from the payloads: the overview keys `search_bridge`, `scout00` and `native`, the `pipeline.intake` count, and
    `sources[].repair.bridge_job`;
  - from the issue rules: rule 16 (the search bridge notice) and rule 17 (the Scout 00 transport notice);
  - from `JOBS`: `scout00_inbox`, `native_scout`, `native_planner` and `native_bridge`;
  - from the page: the Scout lanes and KPI, the Grok bridge chart, and the "Repair research" button (`bridge_create`).
    That button is REMOVED, not disabled: it can never come back. The problem row keeps its diagnosis text.
- **(d) Absent subsystems are visible, not faked.** Each absent key above is sent as `{"deferred": "<reason>"}`,
  not as the old `"temporarily unavailable"` fallback, which would claim a passing fault.
  - The page shows that reason where the data would be.
  - The issue rules that read only those sources are omitted until their port: 5 (watch checks), 12 (the lock),
    19 (source discovery), 20 (stale UI), 21 (selfcheck DEGRADED) and 22 (`compat.skipped`).
  - The omitted rules are listed in the parity as declared.
- **(e) The jobs are the imported snapshot until the runner is ported (032c).**
  - `JOBS` keeps the 11 non-Scout jobs and their intervals.
  - `plan()` runs over `job_state.detail`, and each job's `last` comes from the new tables where it exists: the last
    scan, the Events health, the News log.
  - An imported `running` state becomes `interrupted`, which is what the old `recover_on_start` did at startup, since
    no runner is alive.
  - Every job falls overdue as time passes, so the overdue issue (6) and the status `unknown` (the last job report
    older than 6 h) are honest. The Machine panel says so in one line: "Background jobs are not ported yet: job state
    and history are the imported snapshot." The original timestamps stay visible.
  - **"Run overdue now"** is disabled with that reason.
  - `job_runs.started_at` holds the old `at`, which was the FINISH time, and `finished_at` is NULL. The reader uses
    `detail`, which keeps the old row, so the history is exact. The importer's column naming is recorded for 032c.
- **(f) The kill switch follows the NEW semantics.** Paid calls run only when `PZ_AI_PAID=on` plus a key, as decided
  for the inference gateway (029a).
  - `spend.kill_switch` is `"PZ_AI_PAID"` whenever paid calls are off, so rule 15 reads "paid calls are off" (info).
  - `providers[].key` reports only whether a key is configured: a boolean, never the key.
  - This is declared.
- **(g) Imported model rows keep their old role buckets.** They carry no `role`, so `by_role` maps them to the old
  ledger's role field read from `detail`, never to `"None"`.
- **(h) The actions in 032a**, each disabled with its visible reason:
  - "Run overdue now" (032c);
  - "Back up now", "Test latest backup" and "Safe repair" (032b);
  - "Run source network" and the source decisions (032b).

## Verification
- **Oracle** (old interpreter, frozen clock, every write blocked, the Scout services stubbed as in 030a): the old
  `system()` and `overview()` over goldens of invented names. They cover:
  - every source state and `diagnose` text;
  - the scan age either side of 10 days;
  - each job state and outcome (ok, failed twice, interrupted, budget_blocked, partial, waiting_external), and
    overdue jobs;
  - spend at the 80 % limit, and a provider without a key;
  - validation data issues;
  - every verdict and status branch;
  - a 30-day run history across the window, with skipped `*` runs;
  - the models and spend by day, and the pipeline counts;
  - empty documents.

  Expect 0 differences, with (c), (d), (e), (f) and (g) declared and normalised in one place.
- **Real snapshot** through the importer and both routes, against the old code over a byte-exact copy at a pinned
  clock: 0 differences besides the declared items. Every table is checked unchanged.
- **Hosted:** no writes; one snapshot (REPEATABLE READ, READ ONLY); the imported jobs and runs read back exactly
  from `detail`; a new gateway ledger row shows up in today's spend and the models.
- **Browser:**
  - the page on the real snapshot;
  - every panel's deferred reason visible;
  - every disabled control (click, Enter, no request);
  - no `bridge_create` control;
  - the detail drawer;
  - the capture;
  - no overflow at 1366, 1920, 390 and 150 %.

## Questions for Codex
1. (d): is `{"deferred": reason}` for the absent subsystems the right contract, or should those keys keep the old
   fallback shapes?
2. (e): showing the imported job snapshot, with every job falling overdue until 032c, rather than hiding the jobs
   panel until the runner exists.
3. The split into 032a (reads and page), 032b (hardening) and 032c (runner and actions).

---

## Codex review

### H-304 plan verdict

**REQUEST CHANGES to decision (e).** Approve the split into reads, hardening and runner work. Use the proposed deferred object for unavailable subsystems and retain imported job history, timestamps and overdue counts.

The legacy health service tells operators that overdue jobs will run at the next trigger, that “Run overdue now” starts them immediately, and that failed jobs retry automatically. Its overall status can also describe those items as handled automatically or suggest waking the computer. These instructions would appear alongside a disabled control while the new app has no runner. The Machine panel note alone cannot correct the issue list or the headline.

Specify the issue group, status summary and guidance for overdue or failed imported jobs until 032c. Keep their recorded outcomes and ages visible, identify the runner as unavailable wherever the UI gives advice about it, and preserve precedence for independent actionable issues. Declare the resulting text and grouping differences in parity. Add a case with an overdue or failed imported job and a browser assertion that the guidance explains the unavailable runner without promising a retry or an immediate run.

### Claude — plan revision 2

Codex's point is taken, and it reaches further than the job rules. While no runner exists, NO issue and no headline
may promise a mechanism the new app does not have: the runner and its catch-up, automatic retries, "Run overdue now",
the Deal Flow scan, the triage retry, or the repair research job. And no item may count as "handled automatically"
while nothing handles it.

**One switch, `RUNNER = None`, until 032c.** The domain takes the runner's availability as an input. With no runner:
- **Rules whose guidance names a missing mechanism are reworded.** They keep their recorded facts: the labels,
  `fails_in_row`, the errors, the outcomes, the counts and the ages. Only the advice and the group change; the level
  changes only where nothing in the app can act.

  | rule | old (level / group, advice) | with no runner |
  |---|---|---|
  | 1 sources failing (PZ side) | warn / need, "... an optional repair research job" | warn / need, "Open Sources health below: each has a diagnosis." (the repair research job is retired, c) |
  | 3 no scan in 10 days | warn / need, "Run Find New Candidates (or let catch-up run it)." | info / info, "Finding new candidates arrives with the scan port; the last scan is the imported one." |
  | 4 triage pending | info / **auto**, "Retried automatically ...; Deal Flow → Retry now ..." | info / info, "Preserved, nothing was lost. The machine-triage retry arrives with the background-job runner." |
  | 6 jobs overdue | info / **auto**, "They run at the next background trigger ...; Run overdue now starts them immediately." | info / info, "The background-job runner is not ported yet: these jobs do not run, and Run overdue now is unavailable until it is." |
  | 7 keeps failing | warn / need, "... the job retries automatically when due." | info / info, "Recorded in the imported job history; nothing retries it until the runner is ported. Open Background jobs below for the error." |
  | 8 failed or interrupted | warn / need, "... they run again when due." | info / info, "Recorded in the imported job history; nothing runs it again until the runner is ported." |
  | 9 budget blocked | warn / need, "Work is kept for retry; caps are never overridden. ..." | info / info, "Recorded in the imported job history; caps are never overridden, and nothing retries it until the runner is ported. Review spend under Models and budget." |
  | 10 partial | info / **auto**, "The rest is kept for retry ..." | info / info, "Recorded in the imported job history; the rest is not retried until the runner is ported." |
  | 11 waiting external | info / ext, "Nothing to do ... unless it persists." | info / info, "Recorded in the imported job history; nothing checks it again until the runner is ported." |

- **Precedence is preserved.** The independent rules keep their old level and group, so an actionable problem still
  decides "Action required": a failing source (1), the spend limit (13), a missing provider key (14), validation
  data issues (18) and the News source failures (23). The reworded job rules can never raise the verdict. Their
  "need" count no longer includes imported history, so "N items need you" counts only what the user can act on.
- **The headline:**
  - **`unknown`** (the last job report is older than 6 h, which is always the case once the snapshot ages):
    - old: "No background job has reported for N h — the figures below may be stale. Is the computer asleep or the
      background task disabled?"
    - new: "The background-job runner is not ported yet: no job has run since the imported snapshot (last report
      YYYY-MM-DD HH:MM). The job figures below are that snapshot."
    - The label "Status unknown" stays.
  - **`action` / `degraded`:** the suffix "No background job has reported for N h." becomes "The background-job
    runner is not ported yet; the job figures are the imported snapshot."
  - **`limited`:** "N items handled automatically" can no longer count a job or the triage retry, because none of
    them is in the `auto` group any more.
- **The Machine panel and the jobs table** show the same one line next to the recorded outcomes and ages. "Run
  overdue now" is disabled with that reason (h).
- **032c** sets `RUNNER` and restores the old texts and groups exactly, with the oracle goldens as its check.

**Parity: declared (k), normalised in one place.**
- The old texts and groups are mapped through the table above to the expected new ones, so the new texts are checked
  exactly; so is the status sentence.
- The goldens gain two worlds:
  - **`jobs_unrun`:** imported jobs that are overdue, failing twice in a row, interrupted (an imported `running`),
    budget-blocked, partial and waiting-external, plus a failing source. The verdict and status stay "Action
    required" with "1 item needs you": only the source counts.
  - **`jobs_only`:** the same jobs and no actionable problem. The status is `unknown`, with the runner sentence.

**Browser (both e2e specs)** on `jobs_unrun` and on the real snapshot:
- The guidance under every job item and the headline say the runner is not ported.
- No text on the page contains "retries automatically", "kept for retry", "run again when due", "starts them
  immediately", "next background trigger", "let catch-up run it", "handled automatically" (for a job) or "asleep".
- The "Run overdue now" control is disabled with its visible reason.

### H-306 revision 2 verdict

**APPROVE for implementation.** The revised rules keep imported job outcomes visible as history. The paired goldens check that a failing source still drives “Action required” and that stale job history alone yields “Status unknown.” The browser checks cover the headline, issue guidance and disabled run control. This resolves H-305.

Two details for implementation: the legacy `overall_status` also returns `unknown` when there has never been a report. In the empty-world fixture, say that the snapshot contains no job report and omit the timestamp. When 032c restores runner guidance, keep the retired repair-research action out of rule 1 and restore scan or retry instructions only when their corresponding actions exist.

### Claude — implementation

**Backend**
- `health/`, the pure domain:
  - **Cut by script with AST checks** (`scripts/gen_health_catalog.py`): `diagnose`, the repair rules,
    `overall_status`, `classify`, `run_state`, the constants, and the `JOBS` rows as data. The four Scout jobs are
    dropped (c).
  - **Hand-ported line for line:** `system`, `source_health`, `_coverage_summary`, `_providers`, `last_job_report`,
    `plan`, `failing_jobs`, the `last` readers, the ledger spend, `job_history`, `models`, `pipeline`, and the News
    health.
  - **The runner switch (k):** `status_of` wraps the verbatim `overall_status` and rewords only when there is no
    runner. `system_view(inputs, now, runner=RUNNER)` restores the old texts and groups exactly when given a runner;
    the parity proves this on every world. Rule 1 keeps its new text in both modes (H-307).
- `health/inputs.load(conn, schema, now)` builds every field on ONE connection: the Sources store, the archived
  scan history and inbox, the triage inputs, the job state and runs from `detail`, the ledger rows as the old lines,
  the Validation and News inputs, the coverage inputs, the routing summary and the Conviction records.
  - The paid switch and each key's presence are read from the environment, never a key's value.
  - `research_questions.json`, `schedule/runner.json` and `queue_routing.json` are read archive-first. `documents`
    is jsonb, which reorders object keys, and the real parity caught that order in the payload. Nothing in the new
    app writes those three documents.
  - `event_health.json`, which the new Events scan writes, is read from `documents`.
- **Routes:** `GET /api/system_health` and `GET /api/system_health_overview` (`api/routers/system_health.py`), each
  in one `snapshot_transaction`, on the shared Berlin clock.

**Two decisions taken during the build (please challenge them)**
- **(f), rule 15's advice.** The old advice was "Intentional? Unset it to resume machine triage." Under the new
  switch, unsetting keeps paid calls off. It now reads: "Paid calls run only when PZ_AI_PAID=on and a provider key is
  set; switching them on is a deliberate choice." The parity maps the old text to the new one.
- **Page texts that promised a runner were reworded, in the spirit of revision 2:**
  - the triage node mark "Retrying" is now "Pending";
  - the runs drawer's "Retry now" shows the runner reason;
  - the error-kind texts drop "kept for retry" and "retried later";
  - the News empty line drops "(catch-up)";
  - the 032b panels show only their reason, not the old local-zip "Why?" text, and "No backup yet" no longer
    points at a control that does nothing.

**Page** (`features/health/`)
- `Health.module.css` is byte-identical. The pure logic lives in `model/` (`dashboard.ts` and its test,
  `deferred.ts`, `detail.ts`, `format.ts`), and the panels in `components/`.
- **Removed (c):** the Scout lanes and the Scouting KPI, which leaves 5 KPIs; the Grok bridge chart; "Prepare repair
  research".
- **Deferred (d):** each key arrives as `{"deferred": reason}`, and its reason shows where the data would be.
- **Disabled (h):** every action control goes through `useDeferred`, with a visible reason that `aria-describedby`
  points at:
  - "Run overdue now", in both places;
  - Back up, Test, and Safe repair;
  - the source network and its decisions.
- No request is made for backups, integrity, governance or the source network. Refresh is the only control that acts.

**Verification (all pass)**
- **Goldens** (`parity_health check`): 7 worlds against the old `system()` and `overview()`, with 0 differences and
  the runner switch matching. The worlds are `main`, `attention`, `limited`, `healthy`, `jobs_unrun`, `jobs_only` and
  `empty`. The empty world has no job report, so its status sentence has no timestamp.
  - The source-network candidates now carry real URLs, so the importer accepts every world. The goldens were
    regenerated with the oracle.
- **Real snapshot** (`parity_health real`): the importer into a throw-away schema, through both routes, against the
  old reads at 2026-11-13 09:00. The result is 0 differences besides the declared items, with all 49 tables unchanged.
  - The real day: FYI, `limited`, 11 jobs (2 overdue), 47 sources, 328 runs in 30 days, 6 model rows.
- **Hosted** (`test_health_hosted.py`, 10 tests):
  - Every golden world through the importer and both routes equals the normalised old answer, with every table
    unchanged.
    - Declared for fresh worlds only: the News import seeds the old app's shipped curated case (028), which the old
      app wrote at its first News read. The test checks that those seeded rows are curated cases (`nw-case-`) and
      counts them. The real snapshot already holds them.
  - The imported job state and runs read back exactly.
  - A new gateway ledger row adds exactly its cost to the day, week and month and appears in the models.
  - Both reads run at REPEATABLE READ, READ ONLY.
- **Vitest:** 59 health tests, among them:
  - every panel and deferred reason;
  - every disabled control: click, Enter and Space do nothing, with no request;
  - none of the forbidden phrases anywhere, with every section open.
- **E2e:** `health-mocked.spec.ts` (15 tests) and `health.spec.ts` (10 tests, on the preview database, GETs only) all
  pass.
  - The headline and every job item say the runner is not ported.
  - None of the forbidden phrases appears.
  - "Run overdue now" is disabled with its visible reason.
  - The drawers work.
  - There is no overflow at 1366, 1920, 390 or 150 %.
- **Capture old vs new** (1366 and 1920, light and dark, 150 %). The screenshot waits for the overview read. The
  differences are the declared ones:
  - the Scout lanes, the Scouting KPI and the Scout jobs are gone (c);
  - releases, backups and integrity show their reasons (d);
  - the headline names the unported runner (k);
  - spend shows "Paid AI off" (f).
- **Gate** (`scripts\check.ps1`): backend 1,810, frontend 826, PGlite: all pass.

### H-308 implementation verdict

**REQUEST CHANGES before commit.** The overview's “You: review” node links to Deal Flow and labels `pipeline.inbox.new` as the number of undecided candidates. Health builds that count from Validation's reconstructed legacy inbox. In `validation/inputs.py`, `_old_inbox` excludes candidates with only retired Scout origins, and `old_inbox` also restores absorbed records. The destination and the Investment Desk count the merged candidate rows. H-298 identified 36 additional new candidates on the reviewed snapshot. Matching the old oracle therefore misses a discrepancy users see when following the link.

Use the canonical Deal Flow candidates and current decisions for the overview's inbox counts. Preserve the legacy inputs for checks that require them. Declare the parity difference and add a hosted case with a Scout-only new candidate and an absorbed record, comparing the overview counts by decision with the actual Deal Flow inbox.

I accept rule 15's paid-switch advice and the revised runner guidance. The empty-report headline handles the missing timestamp. I ran all 16 backend Health unit tests successfully. The hosted and browser results above are Claude's runs.

### Claude — implementation revision 2 (H-309)

Codex's point is taken. The "You: review" node links to the Deal Flow inbox, so its counts by decision are now that
inbox's.
- **New input `inbox_decisions`.** It holds the decision of every candidate the Deal Flow inbox lists:
  `ranking_input(row)[0]["decision"]` over `dealflow.inbox_view.candidate_rows`, the same population and decision
  the inbox view builds. `pipeline.inbox` counts it.
- **The legacy reconstruction (`candidates`) stays** for the checks that need the old inbox: `source_health` and the
  watch view. The pure golden adapter keeps the old count, because there `inbox.json` is the whole Deal Flow.
- **Declared (l)**, normalised in the real parity: the expected `pipeline.inbox` is the count over
  `GET /api/deal-flow/inbox` in the same run, and the report prints its difference from the old count.
  - On the real snapshot that difference is `new` +36, `watch` +20 and `kept` +1: the Scout-only candidates the merge
    brought into Deal Flow. The 36 are the same as the desk's (j).
  - Every other key still has 0 differences, and all 49 tables are unchanged.
- **New hosted case** `test_the_overview_inbox_counts_what_the_deal_flow_inbox_lists`. Two open inbox records share a
  registry number, so the importer absorbs one into the other (a `merge` alias). A Scout-only `new` candidate is
  added. The overview's counts by decision then equal the Deal Flow inbox route's exactly: `watch` is one less than
  the legacy count and `new` one more.
- **Re-run, all pass:** the goldens (MATCH, and the runner switch matches); the real parity (0 differences besides
  l); the health hosted tests (11); the gate (backend 1,810, frontend 826, PGlite).
- The paid-switch advice and the runner wording are recorded as accepted (H-309).

### H-310 implementation revision 2 verdict

**APPROVE for commit.** The overview now counts decisions from Deal Flow's candidate rows using its current-status mapping. An empty merged inbox correctly produces empty counts. I inspected the hosted regression comparing both routes with an absorbed twin and a Scout-only candidate, and reran all 16 Health unit tests successfully. Claude reports the hosted and real-snapshot comparisons passed. Declared difference (l) resolves H-309.

## Grok notes
