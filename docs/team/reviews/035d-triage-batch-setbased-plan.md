# 035d — Plan: a set-based triage batch confirm

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-365) — implementation next

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
