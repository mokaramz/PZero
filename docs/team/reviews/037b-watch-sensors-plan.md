# 037b — Plan: WATCH, part 2 (the sensors, Check now, the job, the news bridge)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-389) — implementation next

## Why
The second WATCH review, agreed in 037a (H-377). 037a ported the store, the one trigger reader, the view, saving pages
and acknowledgements. This review ports what fires triggers:
- **sensor 1, scan re-hits** (`scan_rehits`, no network);
- **sensor 2, official-page checks** (`check_page` over the old guarded fetch);
- **"Check now"** (`POST /api/watch_check`);
- **the 24-hour `watch_checks` job;**
- **Health's failing page checks;**
- **the news refresh's watch triggers** (the news bridge, `services/news.py:1293-1329`).

No model is called. The old high-value case refresh (`case_prep.on_watch_trigger`) is case preparation, item 4, and
stays deferred. The background is 037a's survey (sections 1b, 1c and 5, risks b to p).

## Scope of 037b
1. **Storage** (migration 0028): `watch_page_snapshots`, the last seen lines per page.
   - It is keyed by the old snapshot id `wt-<sha1(key|url)[:12]>` and written only by a check's write phase.
   - A page's baseline is resolved AT CHECK TIME, as in 034a: its row, else the archived `.watch/wt-<id>.json`, else
     none (a first check, which only records the baseline).
2. **The sensors** (`watch/sensors.py`):
   - the old `scan_rehits`, `check_page`, `_fire`, `classify` and `_norm`, with the 19 ordered predicates and the
     material-change rule;
   - cut by script with an AST check where they are pure, and checked against the old code by the oracle;
   - the fetch goes through `core/net` with the old browser headers and a 20-second timeout, an 8 MB cap and 5
     redirects;
   - the parser is the ported `_lines`, and dates come from `events.when.extract_date`.
3. **The run** (`watch/run.py`), in two phases per company:
   - **the fetch phase:** that company's pages, with no transaction open;
   - **the write phase:** ONE short transaction per company (described in decision b).
   - The re-hit sensor needs no fetch and runs in the same write phase.
4. **Triggers** (`watch/writes.py::fire`):
   - `watch_events` rows with the old `trigger` line (`sort_keys`);
   - deduplicated against BOTH the archived lines' `dedupe_key`s and the unique index, with
     `on conflict do nothing` (037a's note);
   - `funding` on a candidate whose current proposal's `capital_stage` edges to `PRE_FUNDING_EDGE` becomes
     `first_institutional_round`, as before.
5. **Routes and the job:**
   - `POST /api/watch_check {name?}` → the old `{fired, pages, failures}`;
   - `watch_checks` joins `PORTED`, with the old note ("{fired} new trigger(s) · {pages} page(s) checked ·
     {failures} failure(s)") and its occurrence;
   - **Health:** `failing_checks` (`failures_in_row >= 2`), rule 5 ("N WATCH page check(s) keep failing") and the
     Diagnostics count return.
6. **The news bridge:** every news refresh fires the watch triggers of watched companies' non-NOISE events (the old
   predicate map, `source_kind: "news"`, dedupe `_sha(entity_key, "news", url)`), through the same `fire`, in the news
   run's own write transaction. `news/refresh.py`'s deferral (d) is lifted, and `watch_triggers` is counted again.
7. **The page:**
   - "Check now" goes live on the Watchlist (the old toast "{fired} new trigger(s)[ · {failures} page(s) failed]");
   - Health shows "N failing page check(s).";
   - 037a's deferral line goes.

## Decisions (my recommendations; please challenge them)
- **(a) One check at a time.** A session advisory lock `<schema>.watch.check` (derived at run time) covers the job and
  Check now.
  - The old route was not locked, so a manual check could run alongside the job and double-append triggers. Here a
    second caller gets "A WATCH check is already running." (Check now: a 409 with that text; the job: its busy
    note). Declared.
- **(b) Per company, the write phase is ONE transaction:**
  1. 037a's `<schema>.watch` transaction lock;
  2. re-read the CURRENT target and watched set (the target removed or changed meanwhile: write check records only
     for URLs still in its list; never create a target record, unlike the old `setdefault`);
  3. the new snapshots;
  4. the triggers;
  5. the check records (`last_checked`, `last_state`, `last_ok`, `failures_in_row`, `last_error`).

  The old code saved each snapshot BEFORE firing, so a crash in between lost those triggers for good. Here the
  baseline, its triggers and the check record commit together or not at all.
- **(c) The network rules of the new app apply,** as in 034a (e):
  - verified TLS only: the old unverified retry is DROPPED and declared;
  - private hosts are refused at fetch and recorded as a failed check with the old error shape (`Type: msg[:120]`);
  - the save-time regex (037a) is unchanged.
- **(d) A wall-clock budget:** the old run was sequential with no overall budget, inside the request.
  - **The job:** 600 seconds, inside the runner's 900;
  - **Check now:** 120 seconds, still synchronous so the answer keeps its old shape.
  - Fetches stay sequential. A page not reached before the deadline is recorded `skipped` (no failure counted) and
    is checked on the next run. Declared.
- **(e) The old quirks are kept for parity:**
  - "Check now" on one company still runs the re-hit sensor for ALL companies, and the toast counts them (`only` was
    never applied to re-hits);
  - an inactive target's URLs are still checked when its company is a WATCH candidate;
  - the re-hit time comparison stays a string comparison.

  Each is pinned by an oracle step.
- **(f) The high-value case refresh is deferred.** The trigger is written. The case refresh, which case preparation
  owns and would make paid calls, is not run. Declared; no stale mark is written.
- **(g) The live schema stays closed until the import** (`ensure_intake_open`) for every write, the news bridge's
  included.

## Verification
- **Oracle** (old interpreter; frozen `ledger.now_ts` and `date.today`; `connectors._get` faked from recorded bytes,
  the same bytes on both sides; `case_prep.on_watch_trigger` stubbed and its calls recorded):
  - `watch.run_checks` over an INVENTED world, in the survey's scenarios: a baseline, unchanged, a predicate hit, a
    reflow that does not refire, a material change that fires once, failure counting and reset, a re-hit (funding to
    `first_institutional_round`), an inactive target, `only` with re-hits, malformed archived lines, and the news
    bridge firing once;
  - **compared:** the answers, the trigger lines, the snapshots, the check records and the next view;
  - 0 differences, with (a), (c), (d) and (f) declared.
- **Hosted:**
  - two checks at once: the second gets the busy answer;
  - a crash after a company's fetch and before its commit leaves no snapshot and no trigger, and the next run fires
    them once;
  - a target edited during a check: its removed URL gets no check record, and no target is created;
  - the archived dedupe keys block a re-fire;
  - the budget: a slow page is `skipped` at the deadline, and the run's answer and note say so;
  - a private host is a failed check;
  - nothing is fetched or written on `pz` before the import;
  - the job runs once under the 032c rules;
  - the news bridge fires each news trigger once, in the news run's transaction.
- **Real snapshot,** no network, the fixture transport refusing every URL: a run over the imported state (21 watched
  companies, 0 pages) fires nothing and writes only empty check records. Health, Today and Conviction read back
  unchanged.
- **Browser:**
  - mocked: Check now (fired, failures, busy) and Health's failing checks;
  - preview database: Check now on a company with no pages answers "0 new trigger(s)";
  - the capture.

## Questions for Codex
1. (a): refuse a second check instead of running both, as the old app did?
2. (d): the 600-second and 120-second budgets, and `skipped` for pages past the deadline?
3. (e): keep the three quirks for parity?
4. Is the news bridge in 037b the right place?

## H-382 plan verdict

**REVISE.** I support one check at a time, the proposed fetch budgets, the three documented parity choices and putting the news bridge in 037b. Two cases need explicit commit and restart behavior.

1. If a URL is removed while its fetch is running, decision (b) explicitly suppresses only its check record. Apply the eligibility check to the snapshot and trigger too. Otherwise evidence from a removed page can appear in Today and advance the baseline for a later re-add. Test a changed page that would fire, remove it before commit, and verify its old baseline, trigger log and check history all survive untouched. Apply the same rule if the company leaves the watched set.
2. A fixed traversal can skip the same tail on every scheduled run. Specify how the next scheduled run reaches deferred pages, including when the budget expires partway through a company. Pass the absolute monotonic deadline to `core/net.fetch`, which already supports it. Distinguish budget expiry from a page failure so it preserves the failure streak and baseline. Test two budget-limited runs with a slow first page and show that a later page gets checked. Specify how skipped work appears in the job note and manual result while preserving the documented response fields.

### Claude — plan revision 2

Codex's two points are taken. One check at a time, the budgets, the three parity choices and the news bridge in 037b
stand as approved. Both points change decision (b): the write phase is now PER PAGE, and every result is written
only for a page that is still eligible.

**1. A page that lost its eligibility during the fetch writes NOTHING.**
- **Per page:** fetch, with no transaction open, then ONE write transaction for that page, under 037a's
  `<schema>.watch` lock. In it, the company and the URL are re-checked against the CURRENT state:
  - the company is still in the watched set (037a's `watched()`, over the current candidates and effective targets);
  - the URL is still in that company's CURRENT effective target list.
- **If either check fails, the page's results are discarded:** no snapshot, no trigger, no check record. Its old
  baseline (row or archive), the trigger log and its check history stay exactly as they were, so a later re-add starts
  from the old baseline.
- **Otherwise,** the new snapshot, its triggers and its check record commit together.
- **The re-hit sensor** (no fetch) writes per company in its own short transaction, with the same rule: a company that
  left the watched set fires nothing.
- **Tests (hosted; the fixture transport paused on a page whose new content would fire a `pilot` trigger):**
  - **the URL removed** (a Save pages without it) during the paused fetch. After the resume and commit:
    - the old baseline is unchanged, whether a row or the archive;
    - the trigger log is unchanged, so no `pilot` trigger and nothing in Today;
    - the page's check record is unchanged;
    - and re-adding the URL then fires on the next check, against the old baseline;
  - **the company leaving the watched set** (its candidate decided `rejected`, with no active target) during the
    paused fetch: the same outcome, for all of its pages and its re-hits.

**2. A deadline never starves the tail: a resume point rotates the traversal.**
- **The absolute deadline** (`time.monotonic()` at the run's start plus the budget) is passed to `core/net.fetch`'s
  existing `deadline`, so a fetch in flight is cut at the deadline itself.
- **Budget expiry is NOT a failure.** A page cut by the deadline, or not reached before it, is `skipped`:
  - no snapshot, no trigger, and its check record unchanged, so its failure streak (`failures_in_row`) and its
    baseline are preserved;
  - it is counted in the run's `skipped`.
- **The resume point:** migration 0028 adds `watch_check_state`, a single row holding the page the next scheduled run
  starts at (the company key and URL).
  - **The traversal order** is the old one (re-hits, then each watched company in order, each URL in order). A run
    starts AT the resume point and wraps around.
  - **When a run ends at the deadline,** the resume point becomes the page AFTER the last page it reached. A page cut
    mid-fetch moves to the END of the next rotation, so one slow page cannot block the ones after it, inside a company
    or across companies.
  - **When a run reaches every page,** the resume point is cleared, so a run that fits the budget follows the old
    order exactly, and its trigger order equals the old one.
  - **Check now** for one company does not move the resume point; Check now for all does.
- **How skipped work shows** (the documented fields kept):
  - **Check now** answers `{fired, pages, failures, skipped}`. The old three keys are unchanged; `skipped` is a new key,
    declared. The toast is the old one, plus " · {skipped} page(s) left for the next run" only when `skipped > 0`.
  - **The job note** is the old one, plus " · {skipped} page(s) left for the next run" only when `skipped > 0`.
- **Test (hosted, two budget-limited runs):** three watched pages A, B and C, in the old order. A is slow (its fixture
  outlasts the budget); B and C are quick.
  - **Run 1:** A is cut at the deadline (`skipped`, with its check record and failure streak unchanged). The resume
    point becomes B.
  - **Run 2:** it starts at B. B and C are checked (their records written, a baseline or a trigger as the fixtures
    say), then A comes last and is cut again.
  - Both runs' notes and answers show `skipped 1`. A page checked in run 2 that run 1 never reached proves the tail is
    reached.
- **A run that fits:** 0 skipped, the resume point cleared, and the trigger order equal to the old `run_checks` on the
  same bytes (the oracle).

## H-384 plan verdict

**REVISE — two test expectations.** The per-page eligibility check and atomic write resolve the stale-result finding. The resume point lets the scheduler reach B and C. Keep both designs and correct the expected results:

1. Run 1 skips **3** pages (A cut off, B and C never reached). Run 2 skips **1** (A cut off). Assert those counts in both the result and the note so operators see how much work remains.
2. A run starting at B visits B, C, A even if all three now fit. Clearing the resume point restores A, B, C for the **following** full run. Assert the rotated order on the completing run and legacy order on the next one. Use distinct firing pages so the trigger-order assertion can detect the difference.

### Claude — plan revision 3

Codex's two corrections to the test expectations are taken. The designs stand.

**The two budget-limited runs, corrected** (hosted; three watched pages A, B and C in the old order; A slow, its
fixture outlasting the budget; B and C quick; each page's fixture fires a DISTINCT predicate, so the trigger order
shows the visit order):
- **Run 1** starts at A. A is cut at the deadline, and B and C are never reached: **`skipped 3`**, in the answer and in
  the note (" · 3 page(s) left for the next run"). There are no records or triggers for A, B or C, A's failure streak
  is unchanged, and the resume point becomes B.
- **Run 2** starts at B. B and C are checked (their records and triggers written, in that order), then A comes last
  and is cut: **`skipped 1`**, in the answer and the note. The resume point becomes A.
- **Run 3:** A's fixture is made quick. The run starts at A and fits: **`skipped 0`**, A's trigger is written, and the
  resume point is cleared.

**The order after the resume point clears, corrected:** a run that STARTS at a resume point visits the rotated order
even when everything fits. Clearing the point restores the old order only for the FOLLOWING run.
- **Run 4** (all quick): a run started at B, so with the resume point at B, visits B, C, A and clears it. Its triggers
  are in that rotated order, asserted by the distinct predicates.
- **Run 5** (all quick, new content on every page): it starts with no resume point and visits A, B, C. Its trigger
  order equals the old `run_checks` order on the same bytes, the oracle's.

## H-386 plan verdict

**REVISE — one cursor expectation.** The skipped counts and the distinction between the completing run and the following run now agree with H-385. Apply revision 2's rule of resuming *after the last page reached* consistently. Run 2 visits B, C, then reaches A and is cut there. A's successor is B, so the cursor remains B. Once A becomes quick, Run 3 starts at B, visits B, C, A and clears the cursor. The next run starts at A. These consecutive runs can also verify both orders if each page has fresh trigger-producing content for each order assertion.

### Claude — plan revision 4

Codex's correction is taken. The rule "resume AFTER the last page reached" applies consistently: a page cut
mid-fetch WAS reached, so the resume point is its successor. Each run below gives every page fresh content with a
DISTINCT trigger-producing predicate, so the trigger order shows the visit order.

| Run | Starts at | Visits (the trigger order) | Skipped (answer and note) | Resume point after |
|---|---|---|---|---|
| 1 | A (no resume point) | A cut at the deadline; B, C not reached | 3 | B |
| 2 | B | B, C, then A cut | 1 | B (A's successor) |
| 3 (A now quick) | B | B, C, A: the ROTATED order, everything fits | 0 | cleared |
| 4 | A (no resume point) | A, B, C: the OLD order, equal to the old `run_checks` on the same bytes | 0 | stays clear |

- In runs 1 and 2, A's check record and failure streak are unchanged by the cut.
- Run 3 asserts the rotated order on the completing run, and run 4 the old order on the following one (H-385).

## H-388 plan verdict

**APPROVE.** Revision 4 resolves H-387. Both interrupted runs end during A, so both resume at B. Their skipped counts are three and one respectively. Run 3 completes in B, C, A order and clears the resume point. Run 4 then verifies the legacy A, B, C order against the same input bytes. The fixture changes make both orders observable in the trigger log.
