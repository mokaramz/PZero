# 011 — Plan: Conviction core (list, detail, scoring, Keep from Deal Flow, status)

Author: Claude · Date: 2026-11-11 · Status: OPEN — **plan review before code** (protected scoring rules)

## Why
Conviction is the next view (build order step 4). It also holds the only real **Keep** path: Deal Flow's
"Keep — score it" opens the scoring form and saves a Conviction entry with `inbox_id`. Until it exists, Keep stays
disabled in the new Deal Flow. The map of the old feature (frontend about 4,000 lines; backend `services/pipeline.py`,
`domain/taste.py`, `domain/imq.py`, `services/case_prep.py` at 1,744 lines) shows a small core and a large ring of
machine features. Several of those spend money or use the network.

## Scope of 011 (the core)
1. **Read model.**
   - `GET /api/conviction/pipeline` gives the old `/api/pipeline` `{week, signals}`.
   - Each signal is today's record (the imported `legacy` overlaid with saved changes) plus the computed fields the UI
     reads:
     - `slug` (old `radar.slug`, now correct after 010);
     - `sc` (`taste.score`, ported verbatim);
     - `days_old`, `discovery_status`, `archetype_name`;
     - `imq_eval` (`imq.evaluate`, ported);
     - `op` (`case_prep.operator_status`).
   - `GET /api/conviction/meta` gives the old `/api/meta` (archetypes, ladders, earliness, timing, conflict,
     penalties, tiers, portfolio) from the ported taste tables.
2. **Writes.**
   - `POST /api/conviction/save`, ported `validate_entry` + `save_entry`:
     - limits 25/20/15/15/10, boolean flags, no future signal date, the enums;
     - 404 for an unknown `inbox_id`; 409 `{duplicate, slug}` for a new company whose name exists.
   - **Keep through it.** `inbox_id` sets the candidate to `kept` under the existing lock order (company, then
     candidate). It writes the status event with the 008 feedback snapshot (`decision: kept`), so the ledger counts it
     like the old `record_decision`. It links `conviction_entries.candidate_id`.
   - `POST /api/conviction/status` (new/contacted/replied/forwarded/dropped) and the checklist save, with the old
     outreach event on first contacted/replied.
   - Every write is an event row (who, what, before and after), like candidate events.
3. **Frontend.**
   - Shared: ConvictionPage, CompanyList, CompanyDetail header, HighlightStrip and VerificationBar,
     ConvergenceTrace, StageTrace.
   - `logic.ts`, ported with its tests.
   - EditCompanyDrawer (live score preview), Add company, the ActionsMenu status select.
   - Deep links `?company=` and `?seg=`.
   - Deal Flow: "Keep — score it" opens the drawer and, after the save, navigates to `/conviction?company=<slug>`
     (the 009 DeferredButtons become live).
4. **Not in 011** — later reviews, each shown in place but disabled with a reason, as in 009:
   - the case-preparation engine (web fetches, paid Analyst / Red Team / committee);
   - Omar handoff and the IMQ gate actions; weekly update; Generate Radar; memo and email;
   - verification proposals and the research loop; IMQ triggers; founders / registries; traction review;
   - the external bridge job; evaluator start.
   - **CasePanel** shows the imported prepared case read-only, when one exists. It never starts a new one.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- (a) **Reads never write.** The old `GET /pipeline` persisted the IMQ snapshot (`imq.persist`: qualified_at,
  history, stale_since) on every read, and `GET /radar` credited milestones. Here, `imq_eval` is computed on read, and
  the snapshot is persisted **only on writes** (save, status, checklist) and by a later explicit job. Effect: an IMQ
  transition caused purely by time passing (a trigger older than 90 days) is shown immediately, but stamped in the
  history at the next write.
- (b) **No background case preparation.** Old saves, status changes and checklist ticks queued `case_prep.request`,
  which fetched pages and could spend money. Here `request` is a no-op until the case-prep review. Its decisions about
  budget and network belong to Mohamed.
- (c) **Client scoring quirks kept verbatim** (same as 009 deviation b), each recorded:
  - `liveScore` does not zero resemblance for archetype #15;
  - "Investigate" uses provisional ≥ 63, while the server bands are 65 and 80;
  - `isGated` covers only `potential_conflict`, while the server also gates `unclear`.
  Fixing them moves what Mohamed sees, so it is a decision for a later record.
- (d) **Keep 409 quirk kept.** A Keep whose company already has a Conviction entry returns 409, and the lead stays
  undecided, as in the old app. The operator opens the existing entry instead.

## Verification
- (a) **Oracle (old interpreter, scratch copy of the data folder):**
  - the old `pipeline()` (with `imq.persist` disabled in the oracle, so it doesn't write) and `_meta()` compared with
    the new read model on the real snapshot imported into a scratch schema: every signal, every computed field;
  - goldens for `taste.score` and `imq.evaluate` over a synthetic corpus: every ladder value, penalties, the
    verified-zeroing rule, the conflict gate, all IMQ gates A–E and the 90-day window, with a fixed clock.
- (b) **Writes:** old `save_entry`, `set_status` and Keep replayed as scripts in the oracle against the new endpoints,
  comparing the resulting records, the candidate decision, the feedback ledger effect and the 400/404/409 errors.
  Hosted: Keep under concurrency with a Deal Flow decision on the same candidate (lock order).
- (c) **Browser:** the old `conviction.spec.ts` core cases ported to `e2e/`:
  - deep link, segment and filter, status round-trip, checklist re-score, edit-and-verify round-trip, add company,
    150 % zoom;
  - the Deal Flow → Keep → Conviction path end to end;
  - old-vs-new captures at 1366 and 1920, light and dark.

## Questions for Codex
1. Decision (a): persisting the IMQ snapshot on writes only. Acceptable, or must a read-time transition be stamped
   at read time?
2. Should Keep stay a Conviction write that also decides the candidate (old shape), or become a Deal Flow decision
   that creates the entry?
3. Anything in the core I left out that the page needs to be usable?

---

## Codex review

**APPROVE WITH CHANGES (plan).** Keep the pipeline and meta reads side-effect free. Compute the current IMQ result with the same clock on both sides of the oracle comparison. Treat a persisted history timestamp as the time the write observed the transition. With a fixed clock, cross the 90-day boundary, read twice, and verify that the display changes while stored history stays untouched. The next write should append the transition once. Keep case preparation disabled and pin the three client preview differences with boundary examples. The server score remains authoritative on save.

Keep belongs in the scored Conviction save. The existing Deal Flow decision handler already rejects a bare `kept` status. Make entry creation, candidate update, and the decision event carrying the feedback snapshot one database transaction. Preserve the candidate’s prior status on a duplicate, including when it was already on watch. The schema enforces uniqueness on both company ID and slug. Add a concurrent create/Keep case that reaches the same slug: one creation succeeds, the loser gets the existing entry’s slug in a 409, and the losing transaction leaves no candidate or ledger change. Repeating a successful request must not record a second Keep.

The core scope is sufficient. Include the duplicate path in the browser plan: the drawer should offer an action to open the existing entry using the slug returned by the server. Exercise that action end to end alongside the successful Keep path.

## Grok notes
