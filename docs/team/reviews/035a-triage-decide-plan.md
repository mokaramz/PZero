# 035a — Plan: machine triage, part 1 (accept / override, batch reject, the decision log)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-349) — implementation next

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

## Grok notes
