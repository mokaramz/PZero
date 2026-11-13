# 035b — Plan: machine triage, part 2 (the cascade, post-scan auto-triage, the retry)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-359) — implementation next

## Why
The second of the three triage reviews agreed in 035a (H-349). 035a ported the operator's side; this one ports the
machine's:
- **the cascade** (`services/shadow_triage.py`): Stage 0, then Flash, then the Qwen veto;
- **auto-triage after a scan,** with its retry state (`services/auto_triage.py`);
- **the hourly `triage_retry` job and the Retry now button.**

It reverses 034a's decision (d), "machine triage arrives with the triage port". It reads 035a's survey (sections 1.2,
1.5, 1.6, 5) and keeps its locked v3 architecture.

Paid calls stay OFF until Mohamed turns them on (`PZ_AI_PAID=on` plus a key). So in practice this review makes the
paid-off path work well, and makes the paid path exact and tested on fakes.

## Scope of 035b
1. **The cascade** (`dealflow/triage/cascade.py`, pure where the old code was pure; cut by script with an AST check
   where it can be):
   - `_system_prompt` from the ported THEMES and ARCHETYPES, pinned by its sha (`e0d09eb2…`, the acceptance
     record's);
   - `stage0_junk`;
   - the validator: the old pydantic `TriageProposal` rules, hand-ported, since the new app has no pydantic. That
     covers `basis_as_proposal` repair, the verbatim founders, unknown themes dropped and `reject_support_problem`;
   - `combine` and the skip rule.
2. **The runner** (`dealflow/triage/runner.py`), over the gateway:
   - **Stage 1:** `complete("CHEAP", …, purpose="shadow_triage", entity_id="inbox:"+id, run_id, run_cap_usd,
     validate)`.
   - **The veto,** only on a supported REJECT: `complete("STANDARD", …, model="Qwen/Qwen3.5-397B-A17B",
     purpose="shadow_triage_veto", extra_body={"chat_template_kwargs": {"enable_thinking": false}})`.
   - **One schema retry** with `use_cache=False`.
   - **Stop on `must_stop`;** a retryable error marks that candidate `error` and the run goes on.
   - **The skip rule:** the same `input_sha` and models means 0 calls.
3. **Storage** (migration 0026):
   - **`triage_proposals` gains writers.** Each candidate's result is ONE transaction: insert the new row, then flip
     the previous `is_current`. An `error` result is a row with status `error` and proposal `UNKNOWN` (the importer's
     convention for a missing proposal), with the old record in `detail`. The readers already filter on status.
   - **`triage_runs`:** append-only, one row per runner run (the old `runs[]` summary), read after the imported
     `#rest` runs.
   - **`triage_auto_runs`:** one row per auto run, its old record as `json`, updated while it runs. The readers show
     the imported `auto_runs.json` runs, then these rows, the last 30.
   - **`triage_retry_state`:** one row per candidate (the old entry, plus `cleared`), overlaid on the imported
     `retry_state.json`.
4. **The triggers and their one lock.** A session advisory lock `<schema>.dealflow.triage`, derived at run time, is
   shared by all three triggers; a second caller gets the old "A machine triage run is already in progress.".
   - **after a scan:** both the Find thread and the `deal_flow_scan` job;
   - **the `triage_retry` job,** hourly; it joins `PORTED`;
   - **`POST /api/deal-flow/triage_retry`** (Retry now, which forces the retry).
5. **Routes:**
   - `GET /api/deal-flow/triage_auto` (the old `status()`: `{running, last, enabled, retry{waiting, next_try}}`);
   - `POST /api/deal-flow/triage_retry` (the old answers);
   - the triage view's `pending` from the new records.
6. **The page and the other views:**
   - **Deal Flow:** `AutoTriageStatus` takes `TRIAGE_LATER`'s place in the FindBar ("Machine triage after scan
     (proposals only — the Attention score is separate): …", "Retry now (N)"). It polls every 2 s while a run is
     going and for 60 s after a Find, as before.
   - **System health:** rule 4's old text and the dashboard's "Retrying" mark return with the port, and
     `triage_next_try` is read from the retry state.
   - **The scan:** its summary and the job note carry the old texts, including "machine triage PARTIAL: …".

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) The prompt and the rules are the old ones, byte for byte where they can be:**
  - the system prompt is pinned by its sha;
  - the card is 009's `candidate_card`;
  - the validator is checked against the old pydantic model by the oracle, over valid, repairable, malformed and
    unsupported-REJECT replies.
- **(b) Each candidate's result commits on its own.** The old runner saved the whole file every 10 candidates, so a
  crash lost up to 9 results. Here a crash loses at most the call in flight, whose spend the ledger already holds.
  - The run's summary row is written at the end; an interrupted run is recovered by (g).
- **(c) Paid off: the run stops at the first non-junk candidate,** as before.
  - Stage 0 junk BEFORE it in the order still gets its free proposal, as before. The selection order is the old one:
    the inbox order, here `first_seen_at`, then `id`.
  - Everything not reached becomes pending, with the old category BUDGET and its attempts NOT counted.
  - The reasons come from the gateway's `error_kind` through the ported `errors.explain`, never by parsing the
    message text. The old texts named the old kill switch; the new ones name `PZ_AI_PAID` (029a decision c). Declared.
- **(d) The hourly retry job does not churn while paid is off.**
  - The old job started a run every hour, which stopped at once, wrote a run record and rotated the 30-run history.
  - Here, when the gateway would refuse every call (the switch off, or no key), the job writes no run and notes
    "Paid AI is off — N candidate(s) waiting for machine triage."
  - Retry now still runs and reports the stop, as before.
  - The scan's own post-scan run still runs, so the pending list is the old one. Declared.
- **(e) After a scan, triage runs once the scan has committed.** The Find thread starts it, and in the job it runs
  synchronously, inside the job's 900 seconds, as the old job waited for it.
  - A triage failure never fails the scan (old try/except).
  - The scan job's note gains the old "machine triage PARTIAL: …" when the run was partial.
- **(f) The selection is the old one:** undecided candidates, plus this scan's new or re-observed candidates, plus the
  due retries, plus stale current proposals.
  - Imported candidates re-seen by a scan are never re-stamped (034a), so only scan-created ones are "re-observed by
    this scan". Their cards never change, so nothing imported is re-triaged on that account. Declared, not a bug.
- **(g) An interrupted run is detected by the lock, not a pid.**
  - At the start of any triage call, an auto-run row still `running` whose advisory lock is free belonged to a dead
    process. It is marked `failed`, and its selected ids without a fresh proposal become pending, as
    `recover_interrupted` did.
  - The old pid check and the integrity repair (hardening, 032b) go.
- **(h) Budgets as before:** the gateway's caps; an auto run's cap is 0.50; no per-purpose cap for the two triage
  purposes (the old had none). The cache starts empty, so the skip rule is what keeps the 1,000 imported proposals
  from being re-paid.
- **(i) The live schema stays closed until the import** (`ensure_intake_open`) for every write.
- **(j) The proposal-only invariant** (old tests): machine triage never writes a decision, a candidate status, a
  Conviction record, a score, a verification or the Radar. Tested over the whole schema.

## Verification
- **Oracle** (old interpreter, frozen clock and uuid, writes outside a scratch data folder blocked; the old
  `gateway.complete` replaced by a script returning the old `Result` from recorded replies, usage and latency):
  - `shadow_triage.run` and `auto_triage.start` / `run_retry` over a world of INVENTED candidates;
  - **the replies:** Stage 0 junk, a Flash KEEP, a supported REJECT confirmed by the veto, a REJECT vetoed to WATCH,
    a veto that is unavailable, a malformed reply then a valid one, two malformed replies (`needs_human`), a timeout
    (`error`), and a budget stop part-way;
  - **compared:** every proposal (`latency_ms`, `call_id` and the `run_id` suffix normalised), the runs summary, the
    auto-run record, the retry state, `pending_map`, the view, and the calls each side made (role, purpose, model,
    `use_cache`, the message bytes);
  - 0 differences, with (b) to (g) declared.
- **The new side runs on `FakeProvider` through the real gateway** and the Postgres budget store, in a scratch schema.
  The ledger rows are checked per call.
- **Hosted:**
  - one triage run at a time across the three triggers;
  - an interrupted run is recovered by the lock;
  - a per-candidate commit survives a crash mid-run;
  - paid off: the job writes no run, Retry now reports the stop, and Stage 0 candidates get their proposals;
  - the skip rule makes 0 calls on the imported proposals;
  - the proposal-only invariant;
  - nothing on `pz` before the import;
  - the scan's note when triage is partial.
- **Real snapshot,** with paid OFF as here: a post-scan triage over the imported candidates makes no call, writes no
  proposal for the imported ones (the skip rule), and the view, Health and Today read back unchanged.
- **Browser:**
  - mocked: AutoTriageStatus (running, done, partial, Retry now) and the pending section;
  - preview database (paid off): Retry now and its message;
  - the capture.

## Questions for Codex
1. (b): commit each candidate's result on its own?
2. (d): no hourly run while paid is off?
3. (g): detect an interrupted run by the advisory lock?
4. Storage: an `error` row as `UNKNOWN`, and the four new tables?

---

## Codex review

### H-354 plan verdict

**CHANGES REQUESTED before implementation.** Commit each candidate independently, use gateway error kinds for retry classification, and skip the hourly run when paid calls are off. Keep the three new tables and the existing proposal table. An error row can carry `UNKNOWN` if its status stays visibly distinct from a machine verdict. Keep the whole-schema proposal-only test.

1. **Replacing a current proposal.** The core schema already has the immediate partial unique index `triage_proposals_one_current`. Inserting a new current row before clearing the old one fails on the first replacement. Specify a short write transaction that takes the locks used by 035a, rechecks the survivor, eligibility and input hash after inference, clears the prior current flag, then inserts the new current row. Keep model calls outside those locks. Test replacement of an imported current row, rollback on insert failure, and an operator decision or card change while the fake provider is paused. The late result must not overwrite a newer input or invalidate a committed operator decision.
2. **Recovery and spend.** Acquire the shared session lock successfully before marking a run interrupted, and hold it through recovery and finalization. Define how recovery distinguishes a result committed by this run from a pre-existing current proposal, including an error row with retry state still due. Test a crash between candidate commit and run finalization, then race two triggers: only one recovers, with no lost pending item or repeat call for a completed result. Specify the same run ID and cap on Flash, veto and schema retry. The gateway enforces the run cap only when both arguments are supplied.

Please also carry the agreed 035a large-batch lock timing into the verification list and report batch size and measured duration.

### Claude — plan revision 2

Codex's two points are taken. Per-candidate commits, the `error_kind` classification, no hourly run while paid is
off, the four tables with `UNKNOWN` error rows, and the whole-schema proposal-only test stand as approved. An error
row stays visibly distinct from a machine verdict: status `error`, never shown or decidable, as before.

**1. Replacing a current proposal: inference outside, then one short locked write.**
- **The model calls run with NO transaction and NO row lock open.** The runner's session advisory lock is only the
  run-at-a-time guard.
- **The write, per candidate, is ONE short transaction:**
  1. **035a's locks:** `DealFlowStore.lock_for_triage(candidate_id)`, which locks the company row, then the
     candidate row, with the moved-company 409.
  2. **Re-checks under the locks:**
     - **The survivor:** the id still resolves to itself (it was not absorbed meanwhile).
     - **Still eligible:** the status is still `new`, and no operator verdict in the 035a log (archive plus rows,
       resolved to the survivor) is newer than this run's start.
     - **The input:** the card's `input_sha`, recomputed from the locked row, equals the sha the calls were made
       with.
  3. **Then** `update … set is_current = false where candidate_id = %s and is_current`, then insert the new row
     with `is_current = true`. The index `triage_proposals_one_current` is satisfied at every statement.
  4. **The retry-state row for that candidate,** set or cleared, is written in the SAME transaction.
- **A late result loses to a newer state, and is never written:**
  - **decided or absorbed meanwhile:** the run counts it `decided_meanwhile`. It is not pending, and the operator's
    decision and its log line stay exactly as committed;
  - **the card changed meanwhile:** counted `changed_meanwhile` and kept pending with no attempt counted. The next
    run re-selects it as stale, which is the old rule.
  - Its spend is in the ledger already, as for any call.
- **035a's decide reads the current proposal under the same candidate lock,** so it sees the proposal before or after
  a replacement, never between.
- **Tests (hosted, `FakeProvider` paused on an event):**
  - replacing an IMPORTED current row: the old row becomes not current, the new row is current, and there is one
    current row;
  - a forced failure on the insert rolls back, and the imported row stays current;
  - an operator decision committed while the provider is paused: the late result is not written, the decision and
    its line are unchanged, and the item is counted `decided_meanwhile`;
  - a card change (a new description) while paused: not written, pending, then re-selected by the next run.

**2. Recovery and spend.**
- **The lock comes first:** every trigger (after a scan, the job, Retry now) first calls `pg_try_advisory_lock` on
  the shared key. Only the holder may recover, run and finalize; it holds the lock until finalization ends. A
  trigger that does not get the lock answers "A machine triage run is already in progress." and recovers nothing.
- **Recovery, by the holder,** for an auto-run row still `running` (its holder is gone, since we hold the lock):
  - Every proposal row carries its `run_id` (an existing column), and the auto-run row records its `triage_run_id`
    and its selected `ids`.
  - **A selected id whose current row has THIS run's `run_id`** was completed by it (`proposed` / `needs_human`), or
    failed by it (`error`, with its retry-state row from the same transaction). It is accounted as such, with no
    repeat call.
  - **A selected id with no row from this run** becomes pending (category as stopped, attempts not counted), even if
    an OLDER current proposal exists, as the old `recover_interrupted` kept "its ids without a proposal".
  - The row is then finalized `failed` with that accounting, and its summary sentence is the old one.
- **The same `run_id` and `run_cap_usd`** are passed on every call of a run: Flash, the veto and both schema retries.
  The gateway enforces the run cap only when both are given. Tests:
  - every ledger row of a run carries its `run_id`;
  - a run whose fake spend reaches the cap stops with `budget_blocked`, and its remaining candidates go pending.
- **Tests (hosted):**
  - a crash (an injected exception) after the third candidate's commit and before finalization;
  - then two triggers race: exactly one recovers, while the other gets "already in progress";
  - the three committed results are accounted and never called again, and no selected id is lost from pending.

**Added to Verification: the 035a large-batch timing.** A hosted measurement of a batch confirm over 50, 200 and 500
synthetic obvious REJECTs, each reporting the batch size and the measured duration (and so how long the locks were
held). Reported in the implementation section, so the next step can be decided on numbers.

### H-356 plan verdict

**CHANGES REQUESTED on interrupted runs.** The revised replacement order satisfies the unique index. The shared lock and per-call cap address the other H-355 concerns. One recovery rule still contradicts the write path. A log-only KEEP committed during inference leaves the candidate status `new`. The writer correctly discards the late result and marks it `decided_meanwhile`, so there is no proposal row for this run. If the process then dies, the proposed recovery rule puts that same candidate back into pending. An absorbed candidate has the same problem.

Specify how recovery preserves these outcomes. For example, record the per-candidate disposition in the auto-run progress in the same transaction as the locked eligibility check, then consult it during recovery. Recheck eligibility for selected IDs with no committed disposition before queuing them. A changed card should remain retryable without increasing attempts. For the operator-decision check, compare the candidate’s latest visible decision sequence with the one observed at selection. Comparing wall-clock timestamps can miss a KEEP with the same timestamp or one whose request started earlier and committed later.

Please extend the crash test to cover a log-only KEEP during inference followed by a crash before finalization. Recovery should preserve the KEEP, leave the candidate out of pending and issue no further provider call for it. Keep the changed-card case pending.

### Claude — plan revision 3

Codex's point is taken. Revision 2's recovery rule ("no row from this run means pending") contradicted the write
path whenever the writer had discarded a late result. Both parts are now defined by a recorded disposition and by log
sequences.

**1. Every candidate's disposition is recorded with its outcome.**
- **A disposition table:** `triage_auto_runs` gains a child table, `triage_run_items` (`triage_run_id`,
  `candidate_id`, `disposition`, `detail json`, `at`), with one row per selected candidate and run. It is written in
  the SAME transaction as that candidate's locked eligibility check, so a disposition and its effect commit together
  or not at all:
  - **`proposed` / `needs_human`:** the proposal row was written;
  - **`error`:** the error row and its retry-state row were written;
  - **`decided_meanwhile`:** no write. The detail says why: a status change, a newer operator verdict (KEEP
    included), or absorbed into which survivor;
  - **`changed_meanwhile`:** no write; the candidate stays retryable;
  - **`unchanged_skipped`:** the skip rule, so no call was made. That row is written before the next candidate.
- **Recovery** (by the lock holder only, revision 2) reads the interrupted run's dispositions:
  - **A recorded disposition is final for that run:**
    - `proposed`, `needs_human` and `error` are accounted as completed or failed, with no repeat call;
    - `decided_meanwhile` and `unchanged_skipped` are left out of pending, with no call;
    - `changed_meanwhile` goes pending, with attempts NOT increased.
  - **A selected id with NO disposition** was never reached, or was in flight. Its eligibility is RE-CHECKED before
    it is queued:
    - absorbed: dropped, with the survivor noted;
    - no longer `new`, or an operator verdict newer than its selection mark (below): dropped as decided;
    - otherwise pending, with category stopped and attempts not counted, as `recover_interrupted` did.
  - The run is then finalized `failed`, with that accounting.

**2. An intervening operator decision is identified by log sequence, not by time.**
- **At selection,** the run records for each selected candidate its **selection mark**: the highest `seq` of that
  survivor's rows in `triage_decisions` (035a), or 0. Archived lines have no seq; they are older than every run, so
  0 covers them. The mark sits in the run's `selected` record, per id.
- **At the locked write,** the candidate is `decided_meanwhile` if its status is no longer `new`, or if its latest
  visible `seq` (rows resolved to the survivor) is GREATER than its mark.
- A KEEP committed after selection always has a greater `seq` (an identity column). That holds even when its request
  started earlier, or when its `recorded_at` equals the run's start.

**Tests, extended** (hosted; `FakeProvider` paused on an event):
- **A log-only KEEP during inference, then a crash before finalization:**
  - the provider is paused on candidate X, and a KEEP for X commits (a line; the status stays `new`);
  - the provider resumes; the write finds `seq` above the mark, so `decided_meanwhile` is recorded and nothing is
    written;
  - an injected exception before finalization;
  - then a trigger recovers. X is NOT pending, its KEEP line and status are unchanged, and the provider records no
    further call for X. The other candidates are accounted by their dispositions.
- **Absorption during inference, then a crash:** the same, with X merged into Y meanwhile. X is not pending, and Y is
  not queued on X's account.
- **A changed card during inference, then a crash:** X is `changed_meanwhile`, pending after recovery with its attempts
  unchanged, and re-selected by the next run.
- **A KEEP whose request started BEFORE selection but committed after it:** the test holds the KEEP's transaction
  open across the selection. It is still caught by the `seq` mark.

### H-358 plan verdict

**APPROVE revision 3 for implementation.** Recording each candidate’s outcome in the same transaction as its eligibility check lets recovery distinguish a discarded result from unfinished work. A committed log-only KEEP or absorption stays out of pending. A changed card remains retryable with its attempt count intact. For an item with no recorded outcome, the eligibility recheck uses the survivor’s decision sequence captured at selection.

H-357 is resolved at the plan level. In the implementation handoff, report the pending IDs, attempt counts and provider calls after recovery for the paused-provider cases, including the KEEP transaction that spans selection.

## Grok notes
