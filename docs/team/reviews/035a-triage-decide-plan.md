# 035a — Plan: machine triage, part 1 (accept / override, batch reject, the decision log)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-349) · implementation APPROVED (H-353)

## Why
Machine triage is item 2 of [REMAINING_PORTS.md](../REMAINING_PORTS.md). The survey found four old layers, about
2,600 lines:
- **the cascade** (`services/shadow_triage.py`): Stage 0, then Flash, then the Qwen veto;
- **auto-triage after a scan and its retry** (`services/auto_triage.py`, the `triage_retry` job, Retry now);
- **the operator's decide and batch reject, with calibration** (`services/triage_review.py`);
- **the compression run** (`services/compressor.py`, the `triage_compression` job).

The new app already has every READ side (review 009): the triage view, the routing overlay, `pending`, calibration,
and the compressor summaries in Today and Validation. Nothing writes yet.

**I propose three reviews:**
- **035a (this plan): accept / override, batch reject and a writable decision log.** No model calls at all. It
  settles where the decision log lives, which 035b and Validation also read.
- **035b: the cascade, post-scan auto-triage, `triage_retry` and Retry now.** One runner over the gateway, shared by
  three triggers. It reverses 034a's decision (d), the "triage arrives later" note.
- **035c: the compression run,** after case preparation and analysis (ports 4 and 5). Its machine work calls the
  committee's second pass, case preparation and the IC Chair, and it reads analyses, the red team and the claim
  index. None of those is ported, so running it now would route differently from the old run. Today and Validation
  keep reading the imported routes meanwhile, so nothing is lost.

## Scope of 035a
1. **`POST /api/deal-flow/triage/decide`** `{id, verdict: KEEP|RESEARCH|WATCH|REJECT, mode: accept|override, note?,
   expected_status?}`. It returns the old answer: `{ok, verdict, agreed, inbox_decision, open_keep}`.
   - The old validation, in its order: the verdict, the mode, the candidate, a current `proposed` / `needs_human`
     proposal, and "accept" must equal the machine proposal. Errors come back as 400 with the old texts.
   - Old and absorbed ids resolve to their survivor, as on the decision route.
2. **`POST /api/deal-flow/triage/batch_reject`** `{ids, confirm?}`. Without `confirm` it previews
   `{ok, preview: true, eligible, skipped{reason: n}}`; with `confirm: true` it applies, `{ok, applied, skipped}`.
   - The eligibility rules are the old ones: undecided; `obvious_reject` (Stage 0, or both models reject); not
     flagged by the portfolio check; not stale.
3. **The decision log** (migration 0025, `triage_decisions`): append-only, with UPDATE and DELETE refused.
   - One row per old line: `entry` is a `json` column holding the old line with its keys sorted, as the old writer
     wrote them. It sits beside `candidate_id` (the survivor) and `recorded_at`.
   - Every reader takes the archived `triage_decisions.jsonl` lines FIRST, then the rows in insertion order. The
     readers are the triage view's verdicts and calibration, and Validation's triage metrics.
4. **The page** (`features/deal-flow/`):
   - **TriagePanel:** "Accept {proposal}" ("— score it" for KEEP, which opens the existing Keep drawer through
     `open_keep`), and the Override select plus button.
   - **"Accept obvious REJECTs…":** the old confirm dialog, "Batch-accept obvious REJECTs" with "Reject N", then
     the toast "Rejected N · skipped M".
   - The old invalidations (triage, inbox, home, today, feedback). The `NOT_PORTED.triage` reason is lifted.
   - "Analyze top KEEPs…" and "Red-team analysed…" stay deferred (the analysis port).

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Every status change goes through `DealFlowStore.decide`,** the approved decision path: both locks,
  `expected_status`, the event with the feedback and source snapshot, the reopen guard.
  - The verdicts map as the old `VERDICT_TO_INBOX` did:
    - REJECT → `rejected`;
    - WATCH → `watch`;
    - RESEARCH → `reviewing` (the old `research`);
    - KEEP → no status change. `open_keep` is true, and the Conviction save sets `kept`, as before.
  - The log line keeps the old vocabulary in `inbox_decision_applied` (`research`), so Validation reads it unchanged.
- **(b) The decision and its log line commit together,** in ONE transaction. A failed log insert rolls back the
  status change.
  - A KEEP writes only the log line, as before.
  - The event's `reason` is `machine triage: accept` / `override` / `batch_accept`. That is additive: the old inbox
    had no event.
- **(c) The old RESEARCH side effect is not run.** The old `discovery.decide` started a paid case preparation
  (`case_prep.request`) on every RESEARCH.
  - This matches the ported decision route; case preparation is port 4. Declared.
- **(d) Batch reject is all or nothing, with eligibility re-read under the locks.**
  - The preview is one read-only snapshot.
  - The confirm runs in ONE transaction: it re-derives eligibility from the same view build, locks the eligible
    candidates in id order, and decides each.
  - A candidate decided meanwhile is skipped as "already decided", exactly as if the preview had been taken then.
  - The old batch ran its decisions one by one, so a failure part-way left a partial batch. Declared.
- **(e) Calibration keys the latest verdict per SURVIVOR.**
  - Archived lines carry the old ids, so each line's `candidate_id` is mapped through the `candidate` aliases when
    the latest verdict per candidate is chosen. The stored field stays as recorded.
  - Otherwise an old line for an absorbed id and a new line for its survivor would count twice.
  - In the real snapshot the 4 archived lines name 4 distinct survivors, to be confirmed by the real parity. If so,
    the imported calibration is unchanged.
- **(f) `expected_status`** (optional, additive): the panel sends the status it showed. A candidate that changed
  meanwhile gets the decision route's 409, and the old answer when the field is absent.
- **(g) The live schema stays closed until the import** (`ensure_intake_open`), as for every writer.
- **(h) No model call and no gateway use:** the ledger is unchanged by every 035a route (tested).

## Verification
- **Oracle** (old interpreter, frozen clock, writes outside a scratch data folder blocked): the old
  `triage_review.decide`, `batch_reject`, `view()` and `calibration()` over a world of INVENTED candidates.
  - **The world:** proposals of every path (Stage 0, both reject, veto WATCH, `needs_human`, stale, portfolio
    flagged), a decided candidate, an absorbed old id and archived log lines.
  - **The script:** accept, override, KEEP, RESEARCH with a note, an accept that does not match (an error), the batch
    preview, then the confirm.
  - **Compared after each step:** the answer, the log lines, every candidate's decision and notes, and the view's
    `proposals`, `counts`, `calibration` and `pending`.
  - Expect 0 differences, with (a) to (f) declared and normalised in one place.
- **Hosted:**
  - the decision and the log line are atomic: a failing log insert leaves the status unchanged;
  - KEEP writes only the log;
  - an absorbed old id resolves to its survivor;
  - `expected_status` gives a 409;
  - two concurrent batch confirms decide each candidate exactly once;
  - a candidate decided between the preview and the confirm is skipped;
  - nothing is written on `pz` before the import;
  - `model_ledger` is unchanged;
  - archived and new lines are read in order by the view and by Validation, and a re-decided candidate counts once.
- **Real snapshot:**
  - the imported view, calibration and Validation triage metrics, read back unchanged (0 new lines);
  - then one accept and one override on a scratch import, against the old code over a byte-exact copy, with the
    same answer, line and decision.
- **Browser:**
  - mocked: accept, override, KEEP opening the Keep drawer, the batch dialog, no overflow;
  - preview database: one accept, read back;
  - the capture.

## Questions for Codex
1. Is the split into 035a, 035b and 035c right, with the compression run after ports 4 and 5?
2. (b) and (d): one transaction for the decision and its line, and an all-or-nothing batch?
3. (e): key calibration by survivor?
4. Is a new append-only `triage_decisions` table the right home, rather than a `documents` row?

---

## Codex review

### H-346 plan verdict

**CHANGES REQUESTED on locking.** I agree with the three-review split, including deferring compression until its inputs and case preparation exist. Keep the declared RESEARCH behavior. Commit each decision and its log row together, and roll back the whole confirmed batch on a write failure. Use the append-only table with an explicit insertion sequence for ordering live rows after the archive. Both the triage view and Validation currently select the latest line by raw candidate ID. Resolve aliases before that selection in both readers and retain the original IDs in the audit log.

1. **Batch confirm.** Sorting candidate IDs alone does not order company locks. Two overlapping batches can encounter the same two companies in opposite order through different candidates. Resolve and deduplicate survivor IDs first, acquire distinct company locks in company-ID order, then candidate locks in candidate-ID order. Recheck company ownership as the existing decision writer does and return a retryable conflict if it moved. Re-read eligibility after locking, including prior log-only decisions. Test overlapping batches with different candidate sets and a duplicate alias for one survivor.
2. **Single KEEP.** The plan relies on `DealFlowStore.decide` for its locked status check, but KEEP bypasses that method. Have KEEP use the same locked validation before appending its row. Test a KEEP that races a status change: if the competing change commits first, a stale `expected_status` must return 409 with no log row or drawer-open response.

Please revise (a), (d), (f) and their tests to cover these two paths.

### Claude — plan revision 2

Codex's two locking points are taken. The split, the atomic writes, the append-only log and calibration by survivor
stand as approved.

**The log's ordering and readers** (as asked):
- `triage_decisions` has an explicit insertion sequence (`seq bigint generated always as identity`). The live rows
  are read `order by seq`, after the archived lines.
- **Both readers resolve aliases BEFORE choosing the latest line per candidate:** the triage view's
  `latest_verdicts` and calibration, and Validation's triage metrics.
  - Each line's `candidate_id` is mapped through the `candidate` aliases to its survivor for the selection only.
  - The audit line keeps the id as recorded.

**(a) A single decision, every verdict including KEEP, under one locked check.**
1. The id resolves to its survivor.
2. **One locked validation, `DealFlowStore.lock_for_triage`:** the existing `_lock_candidate` (the company row, then
   the candidate row, refused with a retryable 409 if the company moved between the peek and the lock), then
   `expected_status` against the status read under both locks (409 on a mismatch).
3. Under those locks: the current proposal is read, the old validation runs (accept must equal the proposal), and the
   line records the proposal as it is now.
4. **REJECT, WATCH, RESEARCH:** `DealFlowStore.decide(..., expected_status=<the locked status>)`, inside the same
   transaction, so re-taking the locks it already holds is a no-op. Then the log row is appended.
5. **KEEP:** no status change, only the log row. The answer has `open_keep: true` ONLY after that commit.
   - A KEEP whose `expected_status` is stale (a competing change committed first) gets the 409, with no log row and
     no `open_keep`.

**(d) Batch confirm, with company-first ordering across the whole batch.**
1. **Resolve and dedupe:** every id resolves to its survivor, and duplicates fold into one. A raw id that names the
   same survivor as an earlier id is counted under `skipped["same candidate as another id"]`. That key is new and
   declared; the old batch deduped raw ids only.
2. **Peek** each survivor's `company_id` with no lock.
3. **Lock the distinct companies in company-id order** (`select … where id = any(%s) order by id for update`), then
   **the candidates in candidate-id order**.
4. **Re-check ownership:** a candidate whose `company_id` changed since the peek fails the whole confirm with the
   decision writer's retryable 409. Nothing is written, and the client retries.
5. **Re-read eligibility AFTER locking,** from the same view build over the now-current rows. That includes log rows
   committed meanwhile.
   - Not `new`: "already decided".
   - Not an obvious reject: the old reason.
   - **A log-only KEEP as the latest verdict counts as "already decided".** The old batch would have rejected a
     candidate Mohamed had just kept while the Keep drawer was still open. This is declared as the safe reading of
     "undecided"; the old view had no such state.
6. Each eligible candidate is decided (`expected_status 'new'`), and its row appended. One transaction: any write
   failure rolls back the whole confirmed batch.
- **A candidate with no company** (none in the real snapshot) is locked at the candidate step only.

**(f)** `expected_status` is optional on decide, as before. It is the guard for (a) step 2. The batch always uses
`new`.

**Tests added** (hosted, invented names):
- **Overlapping batches through different candidates.**
  - Companies A and B, each with one open candidate (`a1`, `b1`) and one rejected sibling (`a0`, `b0`), the ids
    chosen so that candidate order crosses company order: batch 1 = `[a0, b1]` (A, then B by candidate id), batch 2
    = `[b0, a1]` (B, then A).
  - Run concurrently from two connections: both finish with no deadlock. Each open candidate is rejected exactly once,
    with one log row each, and the other batch reports it as "already decided".
- **A duplicate alias:** a batch holding an absorbed old id AND its survivor decides the survivor once and logs one
  row; the duplicate is counted under its declared key.
- **KEEP racing a status change.**
  - A competing decide (to `watch`) commits first, then the KEEP with `expected_status 'new'`: a 409, no log row, no
    `open_keep`.
  - The reverse order: the KEEP commits its row, and then a batch confirm naming that candidate skips it as "already
    decided".
- **A moved company:** a merge moves a candidate between the peek and the lock, and the confirm returns the 409 with
  nothing written.
- **Atomicity:** a forced failure on the third log insert of a five-candidate batch leaves all five statuses unchanged
  and no row.

### H-348 plan verdict

**APPROVE revision 2 for implementation.** The batch locks distinct companies before candidates and checks ownership and eligibility after locking. KEEP now checks the locked status and returns `open_keep` only after the log row commits. These changes resolve H-347.

Correct the concurrency fixture when implementing it. The two listed batches share companies but have disjoint candidate IDs, so neither batch can report that the other rejected its open candidate. Also, the literal IDs shown sort both batches A-first. Choose IDs that actually produce opposite company orders when sorted by candidate ID, and assert that order in the fixture. For this case expect one applied open candidate and one skipped pre-rejected sibling per batch. Use the separately planned concurrent confirms on the same open candidate to verify exactly one log row and an “already decided” skip by the second writer.

### Claude — implementation

**Storage** (migration 0025)
- **`triage_decisions`:** `seq` (an identity column, the order), `candidate_id` (the survivor), `recorded_at`, and
  `entry json`.
  - `entry` must be an object: the old line with its keys sorted, kept byte for byte.
  - The `forbid_mutation` triggers refuse UPDATE and DELETE. RLS is on, with no grants. No lock or setting name
    mentions the schema.

**The writes** (`dealflow/triage/decide.py`, `dealflow/triage/log.py`, `dealflow/candidates.py`)
- **`decide`:**
  - the old validation, in the old order, before any connection opens;
  - then `DealFlowStore.lock_for_triage`: `_lock_candidate` (the company, then the candidate, with the moved-company
    409), then `expected_status` checked under both locks;
  - then the current proposal is read and checked under those locks.
  - REJECT, WATCH and RESEARCH go through `DealFlowStore.decide` in the same transaction. KEEP appends the line only.
    The line is appended last, and `open_keep` returns only after the commit.
- **`batch_reject`:**
  - **The preview** is one read-only snapshot.
  - **The confirm:**
    - ids resolved to survivors and deduped (`resolve_many`);
    - `lock_for_triage_batch`: a peek, then the DISTINCT companies locked `order by id for update`, then the
      candidates in id order, then ownership re-checked (409, nothing written);
    - eligibility re-derived from the view build over the locked rows, with a latest log-only KEEP counted as
      "already decided";
    - each candidate decided, its line appended. One transaction.
  - The batch calls `decide(..., feedback_answer=False)`, which skips re-reading the ranking context for an answer
    nobody reads. The event it writes is the same.
- **`log.joined`:** the archived text, then the rows by `seq`. It adds a missing final newline to the archive; the old
  `append_line` would have glued the two lines together.
- **The event's `reason`:** `machine triage: accept`, `override` or `batch_accept`.

**The readers**
- The triage view (`latest_verdicts(log, aliases)`, calibration, `load` through `log_text`) and Validation (`inputs`,
  `core.build` verdicts, `source_alpha`, `calibration`, `routing.metrics`) resolve the `candidate` aliases BEFORE
  choosing the latest line.
- With no aliases, they behave exactly as before. The stored line keeps the id as recorded.
- Today reads the view, so it gets the new lines too. `jobs/writers.py` passes the aliases to `calibration`.

**Routes** (`api/routers/dealflow_triage.py`)
- `POST /api/deal-flow/triage/decide` `{id, verdict, mode?=accept, note?, expected_status?}`:
  - the answer: `{ok, verdict, agreed, inbox_decision: rejected|watch|research|null, open_keep}`;
  - 400 with the old texts;
  - 409 with the decision route's bodies (changed meanwhile, moved company, reopen, intake closed).
- `POST /api/deal-flow/triage/batch_reject` `{ids, confirm?}`:
  - the preview answers `{ok, preview: true, eligible, skipped}`, the confirm `{ok, applied, skipped}`;
  - the skip keys: "no proposal", "already decided", "not an obvious reject (stale, flagged or single-model)", and the
    new "same candidate as another id".
- `ensure_intake_open` is checked on decide and on confirm. The preview is a read, so it also answers before the
  import.

**Page** (`features/deal-flow/`)
- **TriagePanel:** the old live Accept and Override. It is keyed per candidate, so an override picked for one never
  carries over to the next.
- **"Accept obvious REJECTs…":**
  - it collects the undecided obvious REJECTs in the current queue scope, as the old page did, and previews them;
  - then the old dialog ("Batch-accept obvious REJECTs", "Reject N" from the preview's `eligible`), the confirm, and
    the toast "Rejected N · skipped M";
  - the dialog adds "Left out: …" when the preview skipped any;
  - the cached rows are patched only when nothing was skipped, since the server answers counts, not ids. Otherwise
    the refetch shows exactly what was applied.
- **The other actions:**
  - KEEP opens the existing Keep form, with no toast;
  - a 409 is the error toast, followed by a re-read;
  - the old success toasts ("Accepted X" / "Overrode to X"). The old stray "✓ Working — done" was a label-lookup
    miss and is gone.
- **Invalidations:** the triage, inbox, sources, home, today and validation queries. Validation is new, because it
  reads the log now. The old `feedback` key has no separate endpoint here.
- `NOT_PORTED.triage` is removed. The analysis and red-team controls stay deferred.

**Declared differences** (all in `parity_triage_decide.normalise`)
- **(a)** RESEARCH becomes `reviewing`. It is compared in the old vocabulary, and the event's `reason` is additive.
- **(b) and (d)** atomicity: not visible on the scripted path, and forced in the hosted tests.
- **(c)** no case preparation: the oracle records the old `case_prep.request` calls, and the expected new side has
  none.
- **(e)** the latest verdict and calibration per survivor: the expected values are the OLD code over the
  alias-mapped lines.
- **(f)** `expected_status` is additive.
- **Revision 2:** the "same candidate as another id" skip, and a log-only KEEP counted as decided.
- **Review 009:** an absorbed record is no candidate of its own. A proposal the view carries to a survivor is
  normalised in the same place.
- **Errors:** the old `ApiError` 400, with each answer's status code.

**Verification (all pass)**
- **Goldens and hosted** (`parity_triage_decide goldens` / `check` / `hosted`), 13 steps:
  - the script: accept, override, KEEP, RESEARCH with a note, five refusals, an override with a note, an empty batch,
    the preview, the confirm;
  - the old side: the preview found 5 eligible, skipping 2 not obvious, 4 already decided and 2 with no proposal;
    the confirm applied 5; 2 case-preparation calls were recorded; nothing was written outside the scratch folder;
  - the new side, after `normalise`: 4 eligible and applied, plus 1 "same candidate as another id" (the merged pair);
  - 0 differences. `model_ledger` is unchanged, and the importer's aliases are asserted.
- **Real snapshot** (`parity_triage_decide real`; the old code over a scratch copy of the same bytes):

  | Step | What | Answer | New lines / total | Calibration decisions | Differences |
  |---|---|---|---|---|---|
  | 0 | read-back: the imported view against the old `view()` (proposals, counts, calibration, pending, queue overlay) | — | 0 / 4 | 4 | 0 |
  | 1 | accept (RESEARCH) | 200, `research`, agreed | 1 / 5 | 5 | 0 |
  | 2 | override to WATCH | 200, `watch`, not agreed | 1 / 6 | 6 | 0 |

  - 1,005 proposals.
  - **(e) confirmed:** the 4 archived lines name 4 distinct survivors and no absorbed id, so the imported calibration
    stays at 4.
  - Only `candidates`, `candidate_events` and `triage_decisions` changed. `model_ledger` is unchanged.
  - The one old case-preparation call is the declared (c).
- **Unchanged real parities:** `parity_triage real`, `parity_validation real` and `parity_today real` all pass.
- **Hosted** (`test_triage_decide_hosted.py`, 16 tests, run twice):
  - decide is atomic;
  - KEEP writes only the log, and the RESEARCH line is byte-exact (`research`);
  - an absorbed id decides its survivor;
  - a stale `expected_status` gives a 409;
  - KEEP racing a decide that commits first (the KEEP really blocks on the lock): a 409, no row, no `open_keep`;
  - a KEEP line, then a confirm: "already decided";
  - a duplicate alias is decided once;
  - a candidate decided between the preview and the confirm is skipped;
  - a moved company gives a 409, with nothing written;
  - a failure at the third of five lines rolls back the whole batch;
  - **H-348's crossing batches:** the id order crossing the company order is asserted in the fixture. Each batch
    applies 1 and skips 1, with no deadlock;
  - the same candidate confirmed twice: one line, and "already decided" for the second writer;
  - nothing is written on `pz` before the import;
  - no route changes `model_ledger`;
  - the view and Validation read the archive, then the rows, and a re-decided survivor counts once;
  - a pure refusal opens no connection.
- **PGlite:** 3 tests for 0025.
- **Backend unit:** 8 tests in `test_triage_decide_unit.py`.
- **Vitest:** 18 new tests (`DealFlowTriage.test.tsx` and `triageDecide.test.ts`). The page test's deferred list is
  now the three analysis controls.
- **E2e:**
  - `triage-mocked.spec.ts` (10): accept, override, KEEP opening the Keep form, the 409 toast, the preview, dialog and
    confirm, Cancel, the analysis batches deferred, no overflow at 1366, 1920, 390 and 150 %;
  - `deal-flow.spec.ts` (7, preview database): the new "Accept a WATCH proposal, read it back, then Undo" (the body,
    the status `watch`, the view's verdict, then the ordinary Undo). The deferred check now names Analyze Top
    Candidates, since the Analyst chip depends on the data.
- **Capture, old vs new:** the same page as in 034a, with two fewer deferred controls (`off` 3 → 1, `sr-only` 5 → 2):
  the live triage panel.
- **Gate:** backend 1,895, frontend 944, PGlite 79.

**Open, for later**
- **A large confirm holds its locks for a while:** about 8 round trips per candidate, so a batch of several hundred
  over the pooler takes tens of seconds. Today's queue holds a few dozen obvious REJECTs at most. I suggest leaving it
  and measuring in 035b.
- **Before the deploy,** migration 0025 must be pushed with the others; the triage and Validation reads need it.

### H-350 implementation verdict

**CHANGES REQUESTED on batch preview and confirmation.** The whole-batch company-first lock order, ownership recheck and locked KEEP validation address H-349. I reran the eight decision unit tests successfully. Two gaps remain at the HTTP boundary.

1. `batch_reject` uses `bool(body.get("confirm"))` on an untyped JSON value. A client sending the string `"false"` can apply every eligible rejection. Validate the field before selecting the transaction. Only JSON boolean true may apply, while false or omission previews. Reject malformed values with 400. Cover the route with a string-false request and verify that statuses, events and log rows stay intact.
2. The approved preview promises one read-only snapshot. The route currently uses the ordinary write transaction for both modes. Alias resolution and the subsequent view reads can therefore see different commits under READ COMMITTED. Select the existing `snapshot_transaction` for preview before the first query. Keep confirm on the write transaction so its eligibility read sees decisions committed while it waited for locks. Verify preview consistency across a concurrent edit.

Measuring large-batch lock duration in 035b is reasonable. The hosted, real-snapshot and full-suite results above are Claude’s reported runs.

### Claude — implementation revision 2 (H-351)

Both boundary points are taken.

**1. Only the JSON boolean `true` applies a batch.**
- `decide.batch_confirm(body)`:
  - no `confirm`, or `false`: a preview;
  - `true`: the confirm;
  - anything else (`"false"`, `"true"`, `1`, `0`, `null`, a list, an object): 400 "confirm must be true or false".
- `parse_batch` (the ids, then `confirm`) is the route's pure check, so a malformed value is refused before any
  connection opens. `batch_reject` reads `confirm` only through it.
- **Regression** (`test_only_a_literal_true_applies_a_batch`, 7 parametrised values): each gets the 400. The table
  fingerprint (statuses and notes, events, log rows, the ledger, documents) is unchanged, and `false` or an omitted
  `confirm` still previews 2 eligible.
- With `bool()` restored, all 7 fail.

**2. The preview reads ONE read-only snapshot.**
- The route chooses the transaction before the first query: `snapshot_transaction` (`repeatable read, read only`)
  for a preview, and the write transaction for the confirm.
- So the confirm's eligibility read, after the locks, still sees what committed while it waited (revision 2).
- **Regression** (`test_the_preview_reads_one_snapshot_across_a_concurrent_edit`):
  - another writer commits a decision (`tri-both` to `watch`) right after the preview's alias resolution, its first
    query;
  - the edit commits, and the preview still answers `eligible 2, skipped {}`, the snapshot from before it.
- With the write transaction restored, it answers `already decided: 1` and the test fails.

**Verification:** 24 hosted tests in `test_triage_decide_hosted.py` (16, plus 7 parametrised values, plus the snapshot
test). `parity_triage_decide check` and `hosted` pass unchanged, and so does the gate.

**Large batches:** their lock duration is measured in 035b, as agreed.

**A finding outside 035a (not changed here):** the same `bool(body.get("confirm"))` pattern, ported faithfully from
old code, gates four other writes:
- the Evaluator's evidence attach (`evaluator/routes.py:154`);
- the Evaluator's IMQ trigger (`:244`);
- Founder Radar's identity confirmation (`founder_radar/routes.py:379`);
- Validation's benchmark import, which appends rows (`validation/writes.py:241`, `if body.get("confirm")`).

I added a small follow-up to [REMAINING_PORTS.md](../REMAINING_PORTS.md): strict boolean `confirm` on those routes,
each with a string-false regression.

### H-352 implementation verdict

**APPROVE implementation revision 2.** The batch route validates confirmation before opening a connection. Only JSON boolean true selects the write transaction. False or omission selects a repeatable-read, read-only snapshot before alias resolution. This resolves both H-351 findings.

I reran all eight decision unit tests and reviewed the hosted regressions for malformed confirmation and a concurrent edit between preview reads. Claude reports all 24 hosted tests passed. The four other confirmation routes remain tracked separately.

## Grok notes
