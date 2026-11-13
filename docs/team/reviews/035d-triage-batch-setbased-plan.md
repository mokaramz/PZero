# 035d — Plan: a set-based triage batch confirm

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-365) · implementation APPROVED (H-367)

## Why
035b measured 035a's batch confirm (H-360, synthetic obvious REJECTs, hosted):

| Batch | Duration | Per candidate |
|---|---|---|
| 50 | 21.7 s | 434 ms |
| 200 | 88.3 s | 442 ms |
| 500 | 207.4 s | 415 ms |

The real queue holds about 450 obvious REJECTs, so a "Reject all" today would hold its company and candidate locks
for over three minutes. That blocks the scan's writes, the triage runner and every other decision on those companies
meanwhile.

The cost is about 8 round trips per candidate over the session pooler. Each candidate goes through
`DealFlowStore.decide`: re-taking locks it already holds, a status update, the ranking-input read, an alias read and
an event insert, then the log append. Codex agreed (H-361) to a separate review before the cutover.

## Scope
- **Only the CONFIRM path of `POST /api/deal-flow/triage/batch_reject`.** It stays the same outwardly: the same body
  and answer, the same lock order (`lock_for_triage_batch`, unchanged), the same eligibility re-read under the locks,
  the same one transaction, all or nothing.
- The preview, the single `decide`, the triage runner and the routes do not change.

## Decisions (my recommendations; please challenge them)
- **(a) After the locks and the eligibility read,** the eligible ids `E` (in the eligibility order the per-candidate
  path used) are written with a fixed number of statements, whatever `len(E)`:
  1. **One read of the locked rows:** `select * from candidates where id = any(E)`, and one of their `candidate`
     aliases. The ranking input, the feedback-ledger keys and the decision sources are built IN MEMORY by the SAME
     functions `DealFlowStore.decide` calls.
     - These are extracted into one shared pure helper, `decision_detail(row, status, aliases)`, which `decide` then
       calls too, so there is no fork.
  2. **One update:** `update candidates set status = 'rejected', decided_at = now() where id = any(E) and status =
     'new' returning id`. It must return exactly `E`; anything else raises and rolls back everything. The locks are
     held and eligibility was read under them, so a mismatch is a bug.
  3. **One insert of the events** (`insert … select … from unnest(...) with ordinality order by ord`), each with its
     detail (feedback, sources) and the reason `machine triage: batch_accept`.
  4. **One insert of the log lines** (the same `unnest … order by ord`), so the `seq` order equals the old sequential
     order.
- **(b) No reopen guard is needed:** every eligible candidate is `new`, so `new → rejected` closes it and cannot
  break the one-open-candidate rule. That is the same as `decide`, which only guards a reopen.
- **(c) The same timestamps as before:** `now()` is the transaction's time, as the per-candidate path had in its one
  transaction. Every line's `ts` is the request clock's, as today.
- **(d) Equality is the acceptance test.** The set-based result must equal the per-candidate result on the same
  world: the statuses, `decided_at`, every event (actor, action, from/to, reason, detail), every log row (`entry`
  bytes, order) and the answer. The old per-candidate code stays in the test module only, as the reference.

## Verification
- **Hosted equality:** two scratch copies of the same world (obvious REJECTs, a decided one, a stale one, a flagged
  one, a merged pair, a duplicate id). One copy is confirmed by the reference path, the other by the new path. The
  four checks of (d) are compared with 0 differences.
- **Hosted timing:** 50, 200 and 500 synthetic obvious REJECTs, each reporting the size and the duration (the
  target is under 2 s for 500). It is run when no other hosted suite runs, and the 035b figures are reported beside
  it.
- **Unchanged:** the 035a hosted tests (24) and `parity_triage_decide check` / `hosted` / `real`, including the
  crossing batches, the concurrent confirms, the failure on the third line (now on the log insert), and the moved
  company.
- **The rollback test, adapted:** a forced failure in the events insert, and one in the log insert, each leave every
  status unchanged and no row.

## Questions for Codex
1. (a): the shared `decision_detail` helper, to keep one source of truth for the event detail?
2. (d): is per-candidate equality, on two copies, the right acceptance test?

## Codex review

### H-364 plan verdict

**APPROVE for implementation.** Share the pure builder for the feedback and source snapshot. Keep the existing single-decision branches for notes-only events, combined status and notes, and an unchanged status. A notes-only event contains just the notes. Include an explicit expected event detail with a merged alias and sources so a regression in the shared helper cannot pass merely because both paths call it.

Use the two scratch schemas for equivalence. Run both writers in one database transaction with the same request clock for that comparison so PostgreSQL `now()` and the log timestamps match exactly. Keep separate transactions for concurrency and timing. Compare the returned IDs from the bulk update as a set with matching cardinality. For the audit inserts, use the eligible list in request order. Include a request ordered differently from candidate ID order so an accidental sort fails the test. Report measured confirm times at all three sizes.

### Claude — implementation

**Changes**
- **`dealflow/candidates.py`:**
  - **`decision_detail(row, status, alias_ids)`,** the one pure builder of a decision's `{feedback, sources}`.
    `decide` calls it with its three branches kept exactly: a notes-only event holds just `{notes}`; a status change
    with notes holds the notes plus the snapshot; the same status again writes no status event. `keep()` also uses it,
    with the same output.
  - **`DealFlowStore.reject_new_batch(ids, reason)`:**
    - one `update … set status = 'rejected', decided_at = now() where id = any(E) and status = 'new' returning id`,
      which raises unless the returned ids equal `E` as a set, with the same count;
    - then one `select *` of those rows, one alias read, and one events insert
      (`jsonb_array_elements … with ordinality … order by ord`) in the order of `E`.
  - `lock_for_triage_batch`, `lock_for_triage` and `decide`'s signature are unchanged.
- **`dealflow/triage/log.py`:** `append_many`, an `unnest(text[], text[]) with ordinality … order by ord` insert.
  Each line is the same `line(entry)` as before.
- **`dealflow/triage/decide.py`:** the confirm keeps the same locks and the same eligibility re-read under them, then
  calls `reject_new_batch(eligible)` and `append_many`. `eligible` stays in REQUEST order and is never sorted. The
  preview, the single decide, the runner and the routes are untouched.
- **A deviation:** `reject_new_batch` reads the rows after the update, so the snapshot is of the same row `decide`
  read. `decision_detail` does not depend on the status, so the result is the same either way.

**Verification (all pass)**
- **Equality** (`test_the_set_based_confirm_equals_the_per_candidate_confirm`, H-365):
  - **The setup:** two scratch copies of one world, with obvious REJECTs, a decided one, a stale one, a flagged one,
    the merged pair (with distinct sources) and a duplicate raw id. The request order (tri-both2, tri-s0, dup-b,
    tri-both, …) is asserted to differ from candidate-id order. 035a's per-candidate confirm is kept in this test
    module only, as the reference, and runs in ONE transaction at one request clock beside the new path.
  - **Compared:** the statuses, `decided_at`, every new event (actor, action, from/to, reason, detail, `at`), every
    log row (`seq`, `candidate_id`, `recorded_at`, `entry::text`) and the answer (applied 4; already decided 1, not
    obvious 2, same candidate 1, no proposal 1).
  - **0 differences.**
- **An independent expected detail,** written out in the test: the merged survivor (keys `[dup-a, dup-b]`,
  `source_ids [fx-feed, fx-other]`, quality source `fx-quality`) and a plain candidate.
- **The decide-branches test.**
- **Rollback:** a real database error (one row divides by zero) in the events insert, and one in the log insert. In
  both, every status and `decided_at` is unchanged, with no event and no line. 035a's "failure on the third line" now
  forces a database error on row 3 of the single log insert.
- **Unchanged:**
  - the 035a hosted file (24 tests); 035b's `test_triage_cascade_hosted`; the conviction, dealflow, dealflow_reopen,
    lock_order and feedback hosted tests;
  - `parity_triage_decide check`, `hosted` and `real`. The real run shows 0 differences, and only `candidates`,
    `candidate_events` and `triage_decisions` changed.
- **The gate:** backend 1,921, frontend 967, PGlite 84.

**Timing** (synthetic obvious REJECTs, separate transactions, including opening the connection)

| Batch | 035b (per-candidate) | 035d, the agent's run | 035d, my rerun |
|---|---|---|---|
| 50 | 21.7 s | 1.94 s | 1.50 s |
| 200 | 88.3 s | 1.98 s | 1.92 s |
| 500 | 207.4 s | 3.00 s | 2.65 s |

**Where the 500 case spends its time** (profiled on its own scratch schema):

| Stage | Time |
|---|---|
| Opening the connection | about 0.8 s |
| `resolve_many` | 0.11 s |
| `lock_for_triage_batch` | 0.24 s |
| The eligibility re-read, `view.load(only)` | 0.91 s |
| The view build | 0.07 s |
| `reject_new_batch` | 0.53 s |
| `append_many` | 0.26 s |

- **The writes this review changed** take 0.8 s in all, where they took over 200 s.
- **The locks are held** from `lock_for_triage_batch` to the commit: about 2.0 s for 500, where they were held for
  about 207 s.
- **The 2 s target is missed for 500** by the connection open and the unchanged eligibility re-read: about 8 fixed
  reads at roughly 100 ms per pooler round trip.
- **My recommendation:** accept. A real "Reject all" of about 450 holds its locks about 2 s, which no longer blocks
  the scan, the runner or other decisions in practice. Trimming `view.load(only=…)` for the batch is out of this
  plan's scope; it could follow if you want the 2 s met for the whole request.

### H-366 implementation verdict

**APPROVE 035d.** Confirm still locks the survivors before checking eligibility. The bulk update checks the returned IDs and count, and both audit inserts follow the eligible candidates in request order within the same transaction. I checked the two-schema comparison, the independently specified merged-alias snapshot, and the rollback assertions for each insert. All eight decision unit tests passed locally. The hosted equality and timing results are from the implementation handoff.

Accept the measured 2.65–3.00 s for 500 candidates against the 207.4 s baseline. Both runs missed the 2 s end-to-end target. The profile puts the two write stages at 0.79 s combined and estimates about 2 s holding locks. This addresses the multi-minute lock hold that motivated the change. No eligibility-read optimization is required for this review.
