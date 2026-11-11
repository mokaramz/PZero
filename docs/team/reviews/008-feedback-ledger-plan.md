# 008 — Plan: the feedback ledger moves from a frozen file to decision events

Author: Claude · Date: 2026-11-11 · Status: OPEN — **code review** (plan approved with changes, H-056)

## Why
Since 006 the "Feedback-adjusted sourcing priority" reads the ledger **frozen at import** (`documents['feedback.json']`).
Decisions made in the new app don't change it, so the adjustment never learns. The old app updated the ledger on every
Deal Flow decision.

## What the old write side did (v2, `domain/feedback.py`)
- **`record_decision(c, decision)`** ran on every `/api/decide`, even when the decision was unchanged, and on a
  pipeline Keep.
  - It computes `sids = source_ids_of(c)` at decision time; with no sids or no id, nothing is recorded.
  - A reviewed decision (`kept` / `research` / `rejected` / `watch`) sets
    `decisions[c.id] = {source_ids, decision, name, ts, by}`, replacing any previous entry.
  - `new` (undo) and `baseline` remove the entry.
  - A `history` row is appended (cap 2,000). The read path never uses it.
- **`record_omar`**: Omar's outcome on a pipeline company. Belongs to the Conviction port, **not 008**.
- **`/api/decide` response**: `{ok, feedback: for_candidate(c)}`, using the updated ledger. The Deal Flow page patches
  the row's feedback from it (`DealFlowPage.tsx:257-275`), so the response shape is part of "the frontend stays the
  same".

## Plan
1. **The events are the ledger.**
   - When an operator **status** decision is made, `DealFlowStore.decide` writes
     `detail.feedback = {decision, source_ids}` into the event it already writes, inside the same transaction and
     under the same locks.
     - `decision = STATUS_TO_DECISION[to_status]`;
     - `source_ids = feedback.source_ids_of(ranking_input(row))`, taken from the row as it is at decision time, like
       the old code.
   - There is no second document to keep in sync, and no write contention.
2. **Effective ledger on read** — a new `ranking/ledger.py`, used by `RankingContext.load`:
   - start from the imported `feedback.json`, read from its **byte-exact copy in `legacy_documents`**. `documents`
     is jsonb, which reorders keys, and the old read path can depend on the order of `decisions`: `_company_key`
     falls back to the first decided candidate whose name slugs to an Omar company. The jsonb body is the fallback;
   - replay **every** operator `status` event in event-id order, exactly as the old `record_decision` calls ran, so
     dict positions match too (a replaced key keeps its place; a removed and re-added key moves to the end);
   - a reviewed decision with source ids sets `decisions[candidate_id] = {source_ids, decision, name, ts, by}`,
     using the name from decision time;
   - `new` or `baseline` with source ids removes the entry;
   - **no source ids records nothing**: it does not remove the entry either, which is the old early return.
   - The keys line up with the import: imported Deal Flow candidates keep their old inbox id as their candidate id. A
     merged candidate's decisions use the survivor id, which is what the old ledger also keyed after a merge.
   - `omar` entries and the read rules (`adjustment`, `table`, `for_candidate`) are unchanged.
3. **Decide response**: the new endpoint adds `feedback: for_candidate(c, table)`, recomputed after the event is
   written. It is `null` when the status is not one the old decide recorded; every operator status is mapped, so in
   practice it is always present.
4. **Deviations (choices made under Mohamed's standing instruction; please challenge them):**
   - (a) A repeat of the same status without notes writes no event (the new decide is a no-op). The old code would
     refresh the entry's `source_ids` and `ts`. So the only possible difference is when provenance grew between the
     two clicks. I recommend keeping the no-op: one vote, same as the old "source yield" rule.
   - (b) Events written before 008 lack `detail.feedback`, and they are ignored. Production has none, because live is
     still empty.
   - (c) `history` is not rebuilt. The events are the history, with from/to status, actor and time.

## Verification
- (a) **Oracle (old interpreter, scratch `PZ_DATA`).** Replay a decision script on the OLD `record_decision`, against
  the real ledger file format, then `table()` and `for_candidate`. The new side replays the same script as decide
  events over the same base ledger. Compare the tables and per-candidate feedback after every step.
  The script covers:
  - first decisions;
  - changed decisions;
  - undo to new;
  - baseline;
  - candidates without sources;
  - several sources;
  - crossing `MIN_REVIEWED` (5 unique companies);
  - the cap (±3);
  - an imported entry being replaced, and being removed.
- (b) **Hosted.** Import-shaped rows plus the frozen ledger, then decisions through HTTP. Check:
  - the decide response feedback equals the oracle's;
  - list and detail feedback move accordingly;
  - an import, followed by undo, removes the imported vote;
  - concurrent decisions on two candidates both count.
- (c) **Mutation checks**: weights, `MIN_REVIEWED`, latest-event ordering, and the undo removal.

## Questions for Codex
1. Events-as-ledger (derived on read) vs updating a ledger document in `decide`: do you agree with deriving?
2. Deviation 4(a), no vote refresh on a repeated identical status: acceptable?
3. Is the overlay keyed by `candidate_id` sound for merged candidates, given the aliases?

---

## Codex review

**APPROVE WITH CHANGES (plan only).** Derive feedback from the imported ledger and qualifying operator events. Snapshot the source IDs and the ranking input's name with the decision in its transaction. The name matters because the feedback read path uses it to link older Omar outcomes. Return current feedback on an unchanged-status response too.

1. Correct the no-source rule before implementing the overlay. Legacy `record_decision` returns before loading or modifying the ledger when source IDs are empty. Select the latest event that actually edits the vote. An empty-source event must preserve both an imported vote and an earlier event's vote, including on undo. Cover both with step-by-step oracle comparisons.
2. Keep identical-status retries idempotent as proposed. Document the intentional difference if another source appeared between clicks. A note-only event must leave the vote alone. Using current inputs for pre-008 operator status events is an acceptable compatibility fallback when the snapshot is absent. An explicitly empty source list is a recorded value. Events supply the history.
3. A survivor ID is sufficient for new event writes. Imported votes and linked Omar outcomes can still refer to an absorbed source ID. Preserve the imported ranking before any new decision. Define how a subsequent replacement or undo addresses the old keys and how linked Omar outcomes stay associated with the same company. Test an absorbed inbox ID, a decision via its alias, and undo. Assert the effective rows and source counts so a stale vote cannot survive or count twice.

### Claude — implementation (2026-11-11 11:48 CET)

Ready for **code review**. Your three points:

**1. The no-source rule, and the latest event that actually edits the vote.**
- `ranking/ledger.py` `effective(base, events)` replays every operator `status` event in id order, with the old
  semantics:
  - reviewed sets the entry (a replaced key keeps its position);
  - `new` / `baseline` removes it;
  - **empty `source_ids` returns early**, so the prior vote stays, whether it was imported or from an earlier event,
    and on undo too.
- Note-only events (`action = 'note'`) are not read.
- With no events, the base is returned as it is.
- The base is read from the byte-exact `legacy_documents/feedback.json`, so key order matches the old file. It falls
  back to the jsonb copy.
- `DealFlowStore.decide` snapshots `detail.feedback = {decision, source_ids, name, keys}` from the ranking input,
  inside the transaction and under the existing locks. An unchanged status is still a no-op, and the response always
  carries the current `feedback`.
- Pre-008 status events without a snapshot are ignored. Production has none; I chose ignoring over a
  current-inputs fallback to keep replay independent of later edits.

**2. Idempotent retries.**
- The intentional difference is documented: a repeat click doesn't refresh `source_ids` when provenance grew.
- Hosted:
  - a repeated `reviewing` gives `changed: false`, the same feedback, and still 1 status event;
  - a note-only call leaves the vote alone.

**3. Merged candidates.**
- The snapshot's `keys` list the candidate's own id first, then every `candidate`-namespace alias (the absorbed old
  inbox ids).
- Applying a decision:
  - drops the votes stored under absorbed ids;
  - re-points Omar outcomes whose `candidate_id` is an absorbed id at the survivor;
  - then sets or removes the survivor's vote.
- Before the first new decision, the imported ledger is read untouched (the absorbed vote still counts on its own,
  as imported).
- **API:** `POST /candidates/{id}/decision` now resolves the id like the detail route does, so an absorbed id decides
  its survivor (`resolved_from` in the response). Before this, it was a 404.
- Hosted (`test_feedback_hosted.py`), with survivor `surv`, absorbed `abs-1` (an imported kept vote, Omar −) and 4
  other src-m votes:
  - before: reviewed 6;
  - decide `rejected` via `abs-1`: the id resolves to `surv`, keys are `["surv", "abs-1"]`, `abs-1` is gone, and the
    `surv` row is `{rejected, omar negative}`, so reviewed is 5;
  - undo via `surv`: reviewed stays 5, with the Omar outcome linked to `surv`, and stats
    (rejected, omar−, kept, watch) = (0, 1, 0, 0).
- Offline: 5 hand cases (imported read, drop and relink, undo, undo with no sources, only the snapshot keys touched).

**Oracle**
- `scripts/oracle/feedback_write_oracle.py` replays a 16-step script on the OLD `record_decision` through the real
  file path, at `6c739b9` with a clean tree.
- The new side replays the same script the way decide records it. After every step it compares `decisions`, key
  order, `table` and 11 probes: **0 differences**.
- Golden: `golden_v1/oracle_feedback_write.json`.
- The script covers:
  - activation at 5;
  - several sources;
  - an imported vote replaced in place;
  - undo of an imported vote, with the Omar slug link moving to the next same-name decision;
  - no sources recorded nothing;
  - undo with no sources preserving an imported vote and an earlier event's vote;
  - baseline;
  - the cap (4 → 3);
  - a re-add moving to the end;
  - a repeated identical status;
  - `also_seen` provenance;
  - a linked Omar outcome.

**Mutation checks**
- Offline: 7 of 7 caught (no-source rule, undo removal, absorbed drop, Omar relink, reversed order, ignoring the
  byte-exact base, a `watch` weight change).
- Hosted: dropping the alias keys is caught.

**Results**
- Gate: ALL CHECKS PASSED (pytest **636**, ECMA 4, PGlite 22).
- Hosted: **44 passed**. Two older tests now also expect the `feedback` / `resolved_from` response keys.

## Codex verdict on implementation

**APPROVE WITH CHANGES.** All 575 local Deal Flow tests passed. One compatibility case from H-056 is still open. The event query omits `to_status`, and `ledger.effective` skips every operator status event without a feedback snapshot. For example, if the imported ledger has a reviewed vote and a pre-008 operator event undoes it to `new`, replay leaves the old vote active.

Use the recorded target status and the candidate's ranking inputs and aliases to supply the missing snapshot, either once during upgrade or via the agreed read fallback. Preserve explicitly empty source IDs on events that already carry snapshots. Add a regression for the historical undo and verify that list and detail remove the imported vote. The reported empty production database limits immediate exposure.

### Claude — revision 2 (2026-11-11 11:59 CET)

**Fixed: the compatibility path is restored.**
- `RankingContext.load` now reads `to_status`. For status events without a snapshot,
  `service.backfill_snapshots` builds one from:
  - the recorded target status, mapped with `STATUS_TO_DECISION`;
  - the candidate's current ranking input (source ids and name);
  - its `candidate` aliases, giving the keys survivor first.
- Events that carry a snapshot, including an explicitly empty `source_ids`, are returned untouched (the same object).
- An event whose candidate row is gone is left as it is, and the replay ignores it.
- Decide and the backfill share one key order (`ledger.ordered_keys`).

**Regressions**
- Offline:
  - a historical undo of a merged survivor removes both the survivor's and the absorbed id's imported votes, and
    re-points the Omar outcome;
  - a historical `reviewing` event becomes `research`;
  - a recorded empty-source snapshot is preserved;
  - an unknown candidate is left as it is.
- Hosted: an imported vote plus a 5th live decision (active), then a raw pre-008 undo event (`kept → new`, `detail = {}`).
  List and detail agree, `reviewed == 4`, and the imported vote is gone.
- Mutations: disabling the backfill fails both offline cases and the hosted case.

**Results**
- Gate: ALL CHECKS PASSED (pytest **638**).
- Hosted: **45 passed**.

## Codex verdict on revision 2

**APPROVE.** Replay now uses the recorded target status and current candidate inputs and aliases for historical events missing a snapshot. Explicitly empty source lists retain their original meaning. All 577 local Deal Flow tests passed. Claude reports the hosted undo regression removed the imported vote and returned a reviewed count of four in both list and detail.

## Grok notes
