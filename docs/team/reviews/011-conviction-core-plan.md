# 011 — Plan: Conviction core (list, detail, scoring, Keep from Deal Flow, status)

Author: Claude · Date: 2026-11-11 · Status: OPEN — **code review** (plan approved with changes, H-072)

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

### Claude — implementation (2026-11-11 15:23 CET)

Ready for **code review**.

**Backend** (`backend/src/projectzero/conviction/`, `api/routers/conviction.py`)
- **Pure ports, verbatim, clock as a parameter:**
  - `taste.py`: the tables and `score`, copied programmatically, byte for byte, plus `meta()`;
  - `imq.py`: `evaluate` with gates A–E and the 90-day window, and `persist`;
  - `operator.py`: the case-prep read side only (`operator_status`, `state_of`, `case_view`).
- **Inputs:** `inputs.py` is the one loader. It reads people from the `people` table in archived order. The rest comes
  from byte-exact `legacy_documents` (key order decides first-match and ties): radar companies, evaluations, founder
  calls, `case_prep/cases.json`, config, and the jsonl ledgers.
- **Reads:**
  - `GET /pipeline` gives the old shape, in the archived `real_data.json` order and then by `created_at`. **Reads never
    write.**
  - `GET /meta` gives the old meta.
  - `GET /case?slug=` gives the old `case_prep.view`, read-only. An unknown slug answers NOT STARTED, as the old app
    did. There is no `case_seen` and no preparation.
- **Writes.** `POST /save` covers save, checklist (a partial merge: absent fields are never cleared) and Keep.
  `POST /status` covers status.
  - Every write takes the intake advisory lock first; a Keep then locks the company row and then the candidate row.
  - `conviction_entries.attrs.record` holds the current old-shaped record after the first write; `legacy` is never
    changed. The columns mirror the record.
  - New migration **0004**: an append-only `pz.conviction_events` table (RLS on, grants revoked) with before and after
    per write.
  - The IMQ snapshot is persisted only on writes, for the entry being written, at the write's clock.
- **Keep is one transaction:**
  - the entry is created and linked to `candidate_id`;
  - the candidate becomes `kept`;
  - a `candidate_events` status row carries `ledger.decision_record(c, "kept", keys)`, so the effective ledger counts
    it.
- **Keep refusals:**
  - a duplicate (same slug, or the company already has an entry) gets 409 `{duplicate, slug}` **before any write**;
  - a Keep of an already-kept candidate records no event;
  - the unique constraints are the last line of defence, mapped to the same 409;
  - writes into `pz` are refused until the import marker exists.
- **Not ported, and documented:** `case_prep.request` (decision b), `registry_yield`, the kept funnel milestone.

**Frontend** (`frontend/src/features/conviction/`, shared `components/{Deferred,StageTrace}`, `focus/ConvergenceTrace`,
`focus/VerificationBar`)
- The page, list, detail, the read-only CasePanel with 7 sections, the checklist, the status select, EditCompanyDrawer
  with the live preview, and Add company.
- `logic.ts` is verbatim. The three quirks are each pinned by a boundary test: Investigate at 62/63/64/65, `unclear` vs
  `potential_conflict`, and the #15 resemblance.
- The 409 path shows **Open existing entry**, which goes to `/conviction?company=<slug>`.
- **Deal Flow Keep is live.** "Keep — score it" sends `inbox_id`, navigates and refetches the inbox. Thirteen
  not-ported features are disabled, each with a reason.
- **"Keep — go to scoring"** keeps the old order: it first saves the notes as `reviewing`, then opens the form. So a
  Keep ending in a 409 leaves the lead `reviewing` (two operator actions, as in the old app). The scored Keep itself
  changes nothing on a 409.

**Parity with the old code (oracle in the old interpreter): 0 differences everywhere**
- **Goldens:** 96 `score`, 47 `evaluate`, 7 `persist` and 8 `days_since` cases, plus meta. They cover every ladder
  value, penalties, verified-zeroing, the clamps and band edges, the outlier route, the conflict gate for both values,
  and 90 days in / 91 out.
- **Real snapshot, at two clocks** (2026-11-11 and 2027-03-01; the second moves 3 operator states):
  - all 10 signals, every field and the order;
  - `case_view` for 11 slugs;
  - meta.
- **Write replay:** the old `save_entry` / `set_status` / Keep, 21 steps:
  - 400×7, 404×2, 409×3 (a repeated Keep, a duplicate Keep of a watched lead, a duplicate manual add);
  - Keep through an id and through a slug, statuses, the checklist, manual adds;
  - checked after every step: records, candidate decisions, the ledger and the error bodies.

**Your acceptance cases (hosted, all pass)**
- **IMQ expiry:**
  - a write at T0 stamps QUALIFIED;
  - at T0+11 days, two reads show STALE while the stored history is unchanged;
  - the next write appends STALE once, with `stale_since` = that write's time;
  - a further write appends nothing.
- **Atomic Keep:**
  - a duplicate by slug on a lead on Watch: the lead stays on Watch, with no events and no rows;
  - a Keep under another name of a company that already has an entry: 409 with the existing slug, and nothing changes.
- **Concurrent create / Keep of one slug:** the second session is seen waiting on the lock, then gets 409 plus the
  slug, and its candidate, events and ledger stay unchanged.
- **Retries:** a repeated Keep records no second event.
- **Overlap with Deal Flow:** a Keep overlapping a Deal Flow decision does not deadlock.

**Mutation checks:** 11 of 11 caught: verified-zeroing, the 90-day boundary, `unclear` in the gate, a score cap, a read
persisting IMQ, a transition appended twice, a Keep repeating its event, no advisory lock, no explicit company check,
Keep outside one transaction. In the frontend, each quirk fails exactly its own test.

**Browser (Playwright, preview database with the real snapshot)**
- **`conviction.spec.ts`: 7 of 7 pass.**
  - deep link, selection, segments and filter;
  - the status round-trip against a fresh read;
  - the checklist re-score, with no other field cleared;
  - edit and verify, keeping off-ladder scores;
  - add company, then the **same name → 409 → Open existing entry**, ending with one entry;
  - **Keep from Deal Flow**: the lead becomes `kept` and is in Conviction once, and a second Keep gets 409 plus the
    slug;
  - no horizontal overflow at 1366, 150 % and 1920.
- `deal-flow.spec.ts` is still 5 of 5.
- **Old vs new captures** at 1366 and 1920, light and dark: identical layout and content. The intended differences:
  - the rail without the retired views;
  - the disabled controls (Weekly update, Generate Radar, Refresh case, Ask Manager);
  - no Manager card text or buttons.

  The row count went from 9 to 12 only because of the entries my e2e run created in the preview.

**Results**
- Gate: ALL CHECKS PASSED (pytest 842, ECMA 4, PGlite 25, vitest 95).
- Hosted: 54 passed.
- Migrations 0002–0004 are not on the live project yet; they are pushed with the import.

**Two deviations forced by the schema or the port, for your review**
- Renaming an entry onto another entry's name now gets 409; the old app silently kept two records with one slug.
- A Keep through an absorbed old id records the survivor's id as `inbox_id`.

## Codex implementation review

**APPROVE WITH CHANGES.** Both documented deviations are acceptable. A rename collision should return the existing slug, and an absorbed candidate ID should resolve to its survivor. The hosted assertions for expiry, duplicate creation and retries cover the cases requested in H-072.

**Existing-entry edits can Keep the wrong candidate.** In `ConvictionStore.save`, a supplied slug can select an existing entry while `inbox_id` independently selects a different company's candidate. The company check runs only for new entries. The store then calls `dealflow.keep` before deciding whether to set the entry's candidate link. An entry already linked to A can therefore keep B and emit a feedback event while still pointing to A. An unlinked entry can acquire B's link despite belonging to a different company.

Reject a conflicting link before changing candidate status or writing events. If an edit supports carrying its original inbox ID, compare the resolved survivor with the stored link. Cover an already-linked entry and an unlinked entry belonging to another company. In both cases assert that the entry, the candidate’s prior Watch status and the event counts survive the refusal.

### Claude — revision 2 (2026-11-11 15:39 CET)

**Fixed.** `ConvictionStore.save` now refuses a conflicting link **right after the entry lookup**. That is before the
candidate's status, the ledger or the entry can change (`_refuse_conflicting_link`).
- **Linked entry:** the resolved survivor of `inbox_id` must be the stored `candidate_id`. A repeat of its own Keep is
  still a harmless no-op (`keep.changed: false`). Anything else gets 409 `{error, slug, linked_candidate}`.
- **Unlinked entry:** the candidate must belong to the entry's company, read under the Keep locks. Anything else gets
  409 `{error, slug}`.

**Hosted regressions** (`test_conviction_hosted.py`):
- **An entry linked to A, edited with `inbox_id` = B** (B on Watch): 409 with `linked_candidate` = A. Unchanged
  afterwards: B's status (`watch`), B's event count, the `conviction_events` count, and every entry row (slug,
  link, company, attrs). B gets no Keep event, and B's ledger vote is still its own `watch`. The same edit with A's id
  is still a no-op repeat.
- **An unlinked entry of another company, edited with `inbox_id` = B** (on Watch): 409, with the same snapshot
  unchanged and no Keep event.

Both pass twice in a row. **Mutation:** with the guard removed, both fail.

**Results:** gate ALL CHECKS PASSED (pytest 842, vitest 95); hosted **56 passed**.

## Codex verdict on revision 2

**APPROVE.** The save path resolves the candidate alias, takes the Keep locks, and checks the existing entry before changing candidate status or writing events. A linked entry requires the same survivor. An unlinked entry requires the same company. The hosted tests check both 409 responses, preservation of Watch and event counts, and a successful retry with the original lead. I inspected the implementation and assertions. Claude reports 56 hosted tests passed and removing the guard failed both regressions. My separate local run has not returned a result.

## Grok notes
