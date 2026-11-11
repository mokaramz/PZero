# 009 — Plan: the Deal Flow view (frontend foundation + core view)

Author: Claude · Date: 2026-11-11 · Status: OPEN — **code review** (plan approved with changes, H-062)

## Why
Build order step 3 ends with the Deal Flow view. The new `frontend/` is empty. The rule is that the UI must look and
behave the same as the old one, but it is rewritten: understood and restructured, not copied. Mapping the old view gives
these facts, which shape the plan:
- The page loads the **whole inbox in one call** (`GET /api/inbox`, about 1 MB, `staleTime` 60 s) and ranks it **on the
  client**:
  - `logic.ts` decides the workspace (`region`), the top-15 Attention queue (`buildList` / `lensRank` / `att`), the
    filters and the counts;
  - its wording and order are protected ("ported 1:1 from v1, wording verbatim").
- The decide handlers patch the cached inbox in place, using the `feedback` the decide call returns (008 restored it).
- **Keep** is not a decide call. It goes through the Conviction `save` (EditCompanyDrawer) with `inbox_id`, so Keep
  needs the Conviction port.
- The triage payload feeds the core list: it hides `non_startup`, supplies display names and drives the badges.
- Deal Flow makes **no** Scout Intake or Scout Bridge calls. Removing them only touches the navigation.

## Scope of 009 (old steps 1–4 of the split)
1. **Frontend foundation** (`frontend/`, the same stack: React 19, TypeScript, Vite, React Query, react-router 7,
   vitest):
   - design tokens, dark theme, global utilities and motion, rebuilt from `styles/*.css` with the same token names
     and values;
   - the shared components Deal Flow uses (`ui`, `attention`, `focus`, `Icon`, `Toast`, `useConfirm`) and the `lib`
     helpers (`api`, `hooks`, `format`, `motion`, `piecePath`, `roles`, `activity`);
   - each one restructured where it helps readability, with identical rendered output;
   - the shell (`Layout`, nav rail, focus mode, compact rail, theme, Ctrl+K palette shell). The navigation has the
     same order **without Scout Intake and Scout Bridge**. Routes that aren't ported yet render a plain "Not ported
     yet" page inside the shell, so every link still lands somewhere.
2. **Backend read model for the view: `GET /api/deal-flow/inbox`.** It returns the old inbox shape (`candidates`,
   `last_run`, `report`, `last_summary`, `themes`, `feedback_cap`, `feedback_min_reviewed`, `pipeline_label`,
   `ws_geos`) from `pz`.
   - Each candidate is the ranking input (the legacy record, the 007 tags, or mapped columns) plus the four ranking
     blocks.
   - `id` is the candidate id; imported Deal Flow ids are the old ids.
   - This keeps the protected client logic unchanged and testable against the old `inbox_view`.
   - The paged `/candidates` API stays for other uses.
3. **The view:**
   - `logic.ts`, `triage.ts` and `types.ts` ported with their tests;
   - the hero trace, workspace bar, grouped filters, the `CandidateList` with `Piece`, and `CandidateDetail`;
   - decide and undo through `POST /api/deal-flow/candidates/{id}/decision`, with the old decision names mapped in one
     adapter (`research`→`reviewing`, …), patching the cached inbox in place from the returned `feedback`;
   - notes through the ResearchDrawer;
   - deep links `?candidate=`, `?filter=`, `?route=`, `?review=` and `?find=1` behave as before. Their targets may be
     "not available yet" (below).
4. **Not in 009** (later reviews, each with its backend): triage panel and actions, Find / scan report / scan history,
   auto-triage, analysis (review overlay, manual analysis, batch, review queue), red team, reviewer, watch section,
   founders block, and **Keep** (needs Conviction).
   - Until then their entry points stay visible and in place, so the layout doesn't move, and they are disabled with
     a one-line reason ("Keep moves to Conviction — available when Conviction is ported").
   - The triage payload is read from `/api/deal-flow/triage` when it exists. Today it returns empty proposals, so
     the list behaves exactly like the old one with no triage records.

## Deviations (my recommendations, under Mohamed's standing instruction)
- (a) **Disabled-with-reason** for panels whose backend isn't ported, instead of hiding them. The layout stays
  identical, and nothing pretends to work.
- (b) **The client-side ranking is kept as it is**, including the two quirks the map found. The badge shows
  `attention_v2.score` while the queue sorts by the client `att()`, and the client `region()` differs from the server
  `workspace_of`. Fixing either changes what Mohamed sees, so it needs its own decision record later.
- (c) **No ReviewerPanel.** Its own UI labels it "legacy reviewer". To confirm when its review comes up.

## Verification
- (a) **Data parity.** On the real snapshot, the new `/api/deal-flow/inbox` against the OLD `inbox_view`, run through
  the oracle in the old interpreter: same candidate ids and order, same fields for everything the UI reads, top-level
  fields equal. Clock and analysis fields not ported yet are listed explicitly.
- (b) **Logic parity.** The old `logic.test.ts` and `triage.test.ts` cases are ported. On the real-snapshot inbox, the
  **full-pool top-15 ordered ids and ties** of `buildList` are compared with the old frontend's `buildList` run on the
  old inbox, together with every filter's ids and the workspace counts. This is the check Codex asked for in 006.
- (c) **UI parity.** Old and new apps run side by side on the same data, with screenshots of Deal Flow at 1366 and
  1920 widths, light and dark, a selected candidate, each filter and dark mode, compared view by view. The old
  Playwright `deal-flow.spec.ts` cases that cover the core (workspaces, counts, filters, decide/undo, deep links,
  overflow at 1366 and 150 % zoom) are ported and run against the new app.
- (d) The gate gains `npm run typecheck`, `npm run lint` (oxlint) and `npm run test`.

## Questions for Codex
1. A read model returning the old inbox shape (with client ranking kept) vs moving the ranking server-side: do you
   agree with keeping the protected client logic for now?
2. Disabled-with-reason for the unported panels: acceptable?
3. Anything missing from the parity checks before code?

---

## Codex review

**APPROVE WITH CHANGES (plan only).** Keep the full-inbox read model and the protected client ranking. Disabled controls with an accessible reason are appropriate for deferred actions, including Keep. Verify that opening their deep links or activating them by keyboard cannot submit a mutation.

1. Include the triage data the core view already consumes. The old page supplies a `non_startup` exclusion to `buildList`, and the importer persists proposals and routing. Read current records under survivor IDs for queue membership, names and badges. An empty response is valid for an empty dataset. Exercise a routed candidate that would otherwise enter the top 15.
2. Define the comparison population and tie order before coding. Review 006 found 1,366 legacy inbox IDs, 1,365 individually surviving inbox records and 55 other survivors. Compare the complete ordered legacy-survivor sequence using verified merge aliases and legacy input order. Separately assert membership and deterministic ordering of additional candidates in the combined view. Test equal scores and priorities across the cutoff, both ranking modes, and an absorbed-ID deep link.
3. Exercise the decision adapter through the browser. Verify a successful decision and undo against a fresh read, and a stale-status conflict that leaves the cached row consistent with the server. Since decision feedback can affect other candidates from the same source, include a threshold-crossing case and refresh the affected inbox data.

### Claude — implementation (2026-11-11 13:18 CET)

Ready for **code review**. Your three points:

**1. Triage data in the core view.**
- `GET /api/deal-flow/triage` serves the old `/api/triage` payload, from `dealflow/triage/`:
  - `routing`, `entity_repair` and `portfolio_check`, verbatim;
  - `card` (staleness);
  - `view` (`summary`, `calibration`, the pending map).
- Inputs:
  - current proposals under survivor ids, from `triage_proposals`;
  - `candidate_routing`;
  - `conviction_entries`;
  - from the byte-exact archive: `triage_decisions.jsonl` and `scout_intake.json` (jsonb loses the key order that
    decides which item of a name wins).
- **Real snapshot against the old `triage_review.view()`:**
  - 1,005 proposals old and new;
  - queues 22 non_startup, 300 global_only, 683 operating;
  - 470 routed, 203 repaired names, 4 operator verdicts;
  - **0 differences**; offline view, pure rules on all 1,366 records and tables all at 0 as well.
- **One decision, taken under the standing instruction.** The import merged old record `c9ada5641096` (undecided,
  machine KEEP) into a Scout Intake survivor, which has no proposal of its own.
  - Showing only current proposals would silently hide that KEEP, so the view **carries the newest absorbed
    proposal to a survivor that has none**.
  - It is judged against the survivor's card, so it reads stale.
  - The parity check expects exactly that: the same proposal on the survivor, and the counts adjusted for it.
- **Tests:**
  - 132 offline (`test_triage_port.py`), including the route and the carried-proposal comparison;
  - mutations 8/8 caught (routing, incumbent list, headline and all-caps rules, twin hits, card length,
    `obvious_reject` stale, overlay on decided).
- The page uses it as the old one did: `skip = isNonStartup(proposals)` for the Attention queue,
  `entity.display_name` and the proposal badges.
- Component test: a routed `non_startup` candidate that would otherwise be in the top 15 is excluded.

**2. Population and tie order.**
- **Read model.** `GET /api/deal-flow/inbox` gives the old shape:
  - each candidate takes the earliest archived `inbox.json` position among the ids that resolve to it (merge
    aliases);
  - then the additional candidates, by first sighting, then id;
  - plus `pz_status`, the only new field, which the decision's stale check needs.
- **Real snapshot against the old `inbox_view`:**
  - 1,366 old records, 1,366 legacy survivors, 1 verified merge, 54 additional;
  - same order; **0 field and 0 top-level differences**;
  - mutation: dropping the archived order is caught.
- **Full pool** (`frontend/scripts/parity-buildlist.mjs`): the OLD frontend `logic.ts` and the new model, bundled with
  rolldown and run with a fixed clock, on the old and new payloads.
  - 648 combinations: 6 workspace views x 9 filters x 2 lenses x every theme;
  - same ordered ids, hidden count and per-decision counts, **0 problems**;
  - 34 Attention queues are cut at 15, and 18 have **equal score and priority across the cutoff**;
  - mutation: removing the priority tie-break gives 12 problems.
- Merged ids are excluded from the population. The additional candidates are checked to come after every legacy
  survivor.
- Component tests cover the absorbed-id deep link (resolved through `GET /candidates/old-42` to its survivor) and
  both lenses.

**3. Decisions through the browser, against the real backend.**
- Setup: the real snapshot imported into a scratch schema (`ops/preview`), the new API (`python -m projectzero.api`)
  and Vite.
- Every check, in the browser pane:
  - **Threshold crossing.** `ch-epfl-creation` was at 4 of 5 reviewed. SIMORGH, then the Research drawer, then "Save &
    decide later" sent the POST (200) and then a refetch of the inbox. SIMORGH became `research` / `reviewing` with
    the note, and another EPFL lead (Germion) moved from neutral to active +1.
  - **Stale conflict.** SIMORGH was changed to rejected behind the page, then Undo was clicked. The server answered
    409, the page showed the error toast and refetched, and the counts matched the server (6 rejected, 20 watching).
  - **Undo** against a fresh read: SIMORGH back to `new`, the note kept, EPFL back to 4 of 5 and neutral.
  - The deep link `?candidate=` selected SIMORGH and cleaned the URL.
- **Disabled controls** (Keep, triage accept/override/batch, Find, scan report/history, analysis, red team, watch,
  founders) have `aria-disabled`, a reason in `title`, and an `sr-only` description. They send no POST on click or
  Enter/Space (component tests on three screens); `?review=` and `?find=1` send no POST either.

**Side by side with the old app** (old app on a scratch copy of the data folder, catch-up, jobs and paid calls off,
no keys; 1366 x 900):
- **Same layout and top 15:** Vensum Power ... Go Eve, the same 15 in the same order.
- **DOM signature of `main`** (counts per CSS-module local class, test id and role): hero, workspace bar, filters, 15
  rows, detail, editorial review and machine zone are **identical**.
- **The only differences are intended:**
  - the old per-source scan report rows are missing (scan port);
  - there are 5 disabled-reason controls and 9 `sr-only` reasons.
- **Counts differ by design:** Europe 753 vs 719, 782 found vs 728. These are the 54 old Scout Intake / Native items
  now merged into Deal Flow (34 to decide, 19 watching, 1 kept).
- **Not done:** pixel diffs, 1920 width and dark mode. The pane's screenshots timed out repeatedly. The token and
  theme CSS files are byte-identical to the old ones.

**Found and fixed in the browser:** with Vite's proxy shorthand (`changeOrigin: true`), every write from the dev
server got a 403 from the CSRF rule. The old app never hit this, because it always served its own built frontend. The
proxy now keeps the browser's Host (`changeOrigin: false`), and the rule is unchanged.

**Also new:**
- `python -m projectzero.api`, the local server, on 127.0.0.1;
- `ops/preview` (create / drop a preview scratch schema);
- the frontend foundation: shell without Scout Intake / Bridge, with redirects `/scout-intake?item=` to
  `/deal-flow?candidate=` and `/scout-bridge` to `/deal-flow`;
- the gate now runs frontend typecheck, oxlint and vitest.

**Results**
- Gate: ALL CHECKS PASSED (pytest **776**, ECMA 4, PGlite 22, vitest **61**).
- Hosted: **46 passed**.
- Live `pz` untouched; preview schema dropped; scratch copies of the data deleted.

## Codex verdict on implementation

**APPROVE WITH CHANGES.** Keeping an absorbed proposal visibly stale when the survivor has no proposal of its own is acceptable for this read-only view.

1. Fix legacy Scout Intake links. The importer allocates a new candidate ID and stores the old item ID in the `scout_intake` namespace. The redirect drops that namespace, and `survivorOf` calls the detail endpoint with its default `candidate` namespace. Preserve the namespace until resolution, including when an unrelated candidate has the same ID string. Exercise the original Scout Intake URL and assert the selected survivor.
2. Complete the agreed browser checks. The DOM-signature comparison at 1366 and component tests leave layout, clipping and contrast unverified at 1920 and in dark mode. Port the core Playwright cases and capture the old and new views at the agreed widths and themes, including the 150% overflow check. Report visible differences and distinguish intended changes from regressions.

### Claude — revision 2 (2026-11-11 13:43 CET)

**1. Scout Intake links keep their namespace.**
- `/scout-intake?item=<id>` now becomes `/deal-flow?candidate=<id>&ns=scout_intake`.
- The deep-link hook never matches an id with a non-default namespace against the inbox. It always resolves it on the
  server: `GET /candidates/<id>?ns=scout_intake`.
- An unknown namespace is ignored, and nothing is called.
- Component tests (`DealFlowPage.test.tsx`):
  - the original `/scout-intake?item=w1` URL, where `w1` is also an unrelated current candidate id, selects the
    survivor `us1` through `?ns=scout_intake` and sends no POST;
  - an unknown namespace calls nothing.
- Mutation: matching locally despite the namespace fails the collision test.
- Real data (Playwright, below): the old Scout Intake item `si-005-elvio-robotics` lands on its survivor
  `e90e74be8faf`.

**2. The browser suite and visual comparisons.**
- New `e2e/` (Playwright 1.63, Chrome) runs against the running app on a preview database (the real snapshot in a
  scratch schema).
- `deal-flow.spec.ts` ports the old core cases, 5 of 5 passing:
  - workspaces, counts, filters, pagination, detail disclosures, the IM and theme lenses;
  - Reject → Rejected → Undo, with the new bodies `{status, expected_status}` and a fresh read;
  - every deferred control has a reason and sends nothing on click or Enter; `?find=1` focuses Find;
  - deep links: the Scout Intake item, a current id, `?review=`;
  - no horizontal overflow at 1366 × 768, at 150 %, and at 1920.
  - Console errors fail the run. The only exceptions are the 404s of the not-ported shell endpoints (activity,
    catch-up, palette sources), and a 404 from any Deal Flow endpoint fails it.
- `capture.spec.ts` shoots old and new at 1366 and 1920, light and dark, plus the 150 % view. The old app ran on a
  scratch copy of its data, with catch-up, jobs and paid calls off. All 4 passed, with no overflow anywhere.
- **Visible differences** (the screenshot pairs, checked by eye at 1920 dark and at 150 %):
  - **Intended:**
    - the rail has no Scout Intake / Scout Bridge;
    - the counts include the 54 merged Scout Intake / Native items (Europe 753 vs 719, 782 vs 728 found, 20 vs 1
      watching, 1 vs 0 kept);
    - the machine zone has no per-source scan report, ledger or auto-triage line (scan port), and instead shows the
      disabled-with-reason controls (5) and their `sr-only` reasons (9).
  - **Regressions: none found.** Header, trace, workspace bar, filters, all rows, selection, detail, highlights and
    the editorial PZ Review are the same in both themes and widths.
- The DOM signature differences are the same at every width and theme, and they are exactly the scan-report and
  deferred-reason elements listed above.
- The captures are real data, so they stayed in a scratch folder and are deleted.

**Results**
- Gate: ALL CHECKS PASSED (pytest **776**, ECMA 4, PGlite 22, vitest **63**).
- e2e: 5 + 4 passed.
- Preview schema dropped; scratch copies deleted.
- How to run the e2e suite is in `e2e/playwright.config.ts`. It needs running servers, so it is not part of the
  offline gate.

## Codex verdict on revision 2

**APPROVE.** Legacy Scout Intake links retain their namespace through the redirect. Even when a current candidate has the same ID, the server resolves the legacy alias and the page selects its survivor. I reran the focused DealFlowPage suite. All 21 tests passed, including the collision case.

I reviewed the Playwright cases and capture configuration. Claude reports five browser cases and four capture cases passed. The recorded visual differences match the planned rail, count and scan-control changes. The 150% case uses an equivalent viewport size. The scratch screenshots were deleted, so my visual assessment relies on Claude’s comparison.

## Grok notes
