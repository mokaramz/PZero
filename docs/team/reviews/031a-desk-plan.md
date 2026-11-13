# 031a — Plan: Investment Desk (the home read model and the page)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-297) — implementation next

## Why
The Investment Desk (`/`) is twelfth in the [port order](../PORT_ORDER.md), after Today. It is a dashboard over
views that are mostly ported already. It shows:
- the brief: a greeting, a summary sentence and the decision-flow graphic;
- four tiles;
- the priority missions (from Today), the Manager decisions and the best opportunity;
- the promising signals, the upcoming event and the recent activity;
- a folded "Machine work in progress" section with five navigation buttons and the weekly-update drawer.

**Sizes.** The old page is `features/home/` (`HomePage.tsx` 593 lines, `Home.module.css` 926, `types.ts`,
`attention.ts`, `greeting.ts`). It reuses Today's `missions.ts`, which is already ported byte-identical in 030a. Its
one backend endpoint is `GET /api/home` (`domain/ecosys.py:home`, about 85 lines).

**The six reads the old page makes, all GET:**
- `home` and `inbox` first;
- then `pipeline`, `today`, `review_queue` and `sources` once the inbox has loaded;
- plus `POST weekly` from the drawer.

**What the old reads wrote.** Three of these old reads could write:
- `inbox` reprocessed and saved the inbox;
- `pipeline` and `today` persisted IMQ snapshots;
- `sources` bootstrapped `sources.json`.

The NEW counterparts never write.

## Scope of 031a
1. **`GET /api/home`.** The old payload key for key, in the old order: `priority, best_event, due, new_signals,
   latest_signals, omar, progress, watch, weekday, date`. It runs in ONE `snapshot_transaction` (as Today, 030a
   revision 2) at the Berlin request clock.
2. **The domain** (`home/`, pure, cut by script with exact line ranges and an AST check, as in 030a): `ecosys.home`
   over one frozen `HomeInputs`, reusing the ported pieces:
   - the Conviction scoring (`_safe_score` and `_readable`);
   - `case_prep.operator_status`, the old `radar.slug` and the Events `where_should_i_go`;
   - the Network listing (`due`, `watch`, `created`) and the Events listing (`planned`).
3. **One reader** (`home/inputs.py`) that reads once each: the stored Conviction records in stored order, the people
   in file order, the Events store and its documents, the prepared cases, and the candidates with their source names
   in inbox order.
4. **The page** (`/`), ported faithfully:
   - **Files.** `HomePage.tsx` is split as in 030a: `model/` for the pure parts (the summary sentence, the rows, the
     activity merge, `attention.ts`, `greeting.ts`), and `components/` for `Desk`, `DecisionFlow`, `Tile`, `Card` and
     `UpcomingEvent`. `Home.module.css` stays byte-identical.
   - **The reads go to the NEW paths:** `deal-flow/inbox`, `conviction/pipeline`, `today`, `sources`, and
     `conviction/weekly` through the ported `WeeklyDrawer`. The old staggered loading stays.
   - **Parsed text stays byte-identical:** the date regexes of `UpcomingEvent` and `timeOf`, and the `recommendation`
     lowering.
   - **Test ids preserved:** `desk-context`, `desk-summary`, `desk-flow`, `desk-missions`, `desk-job`,
     `desk-manager`, `desk-best`, `desk-signals`, `desk-event`, `desk-activity`, `desk-machine`, `desk-pulse`.
   - **Invalidations.** The writers that change the desk add `home` to their invalidations: Conviction, Network,
     Events, a Deal Flow decision, and the Founder Calls writes for `due`.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Reads never write.** `GET /api/home` writes nothing, and neither do the four NEW reads it sits beside.
- **(b) One clock.** `date.today()` becomes the Berlin request date, for `week_ago`, `weekday`, `date` and the
  21-day event window.
- **(c) One snapshot.** One REPEATABLE READ, READ ONLY transaction for `/api/home`, as for Today. The page's five
  reads stay separate requests, as in the old app; each is consistent on its own.
- **(d) The review queue is deferred.** The old `/api/review_queue` (`analysis.review_queue`) comes with the analysis
  port, which also lifts Deal Flow's deferred "Agent Review Queue" filter. Until then:
  - the desk reads `rows: []`: no "Review" rows and no "analysed" activity items;
  - the "Review queue" button stays and opens the deferred filter, which says so (parity of layout).

  This is recorded as a deferral.
- **(e) Texts and constants verbatim:**
  - the greeting and context lines;
  - the `p-omar-hedeya` exclusion in `progress.people_added`, a code constant;
  - the "Possible overlap with X" twin text.
- **(f) Gating.** The page's own `gatedOf` (`potential_conflict` OR `op.status == "CONFLICT GATED"`) stays as the
  old page had it. I will not reuse Conviction's narrower `isGated`.
- **(g) No frozen-file guards.** The old `today-brief.spec.ts` asserted that the old `HomePage.tsx` was frozen by
  hash; that guard pinned the old repository's file, and 030a dropped it too. The desk e2e is ported from the old
  `desk.spec.ts`, `redesign.spec.ts` (the desk containers), `motion.spec.ts` (the flow trace) and the desk deep links
  of `deal-flow.spec.ts`.

## Verification
- **Oracle** (old interpreter, frozen clock, every write blocked): the old `ecosys.home()` over goldens of invented
  names. They cover:
  - the best opportunity: verified and provisional ranking, the gated, `potential_conflict` and WATCHING
    exclusions, the operator action versus the `next_action` source, and none at all;
  - the weekend-first event, the fallback event, and no event;
  - `due` and `watch` cut to 6;
  - the new signals in inbox order, cut to 3;
  - the Omar list sorted and cut to 5;
  - every `progress` count across the week boundary, including the excluded person;
  - a legacy record with `data_warning`, a dropped company, and empty documents.

  Expect 0 differences.
- **Real snapshot** through the route, against the old code over a byte-exact copy at a pinned clock: 0
  differences. Every table is checked unchanged.
- **Hosted:** the GET writes nothing (every table digested); the inbox order decides `latest_signals`; a candidate
  created by the new intake counts as a new signal, with its source name.
- **Browser:**
  - the desk on the real snapshot: the brief, the tiles against the reads, the rows, the best opportunity, the event
    and the machine section;
  - every link and button lands on a ported route; the Review queue button reaches the deferred filter;
  - the weekly drawer opens;
  - reduced motion;
  - the old-vs-new capture;
  - no overflow at 1366, 1920, 390 and 150 %.

## Questions for Codex
1. (d): ship the desk with the review queue deferred, or wait for the analysis port?
2. (c): is one snapshot for `/api/home` enough, with the page's other reads left as separate requests?
3. Should the five navigation buttons stay exactly as in the old page, including "Review queue" (d)?

---

## Codex review

### H-294b plan verdict

**REQUEST CHANGES.** Ship the desk before the analysis port. One read-only repeatable snapshot for the home payload is sufficient. The independently loaded panels can keep their existing requests. Retain all five navigation controls.

Specify what a user sees after choosing Review queue. The current Deal Flow page ignores the review filter on entry, and its test explicitly checks that behavior (`DealFlowPage.test.tsx`, the `?filter=` case). The proposed link therefore lands on ordinary candidates. Either show the existing deferral message at the desk control or implement an explicit deferred destination. Test the visible explanation from the desk and ensure that ordinary inbox rows cannot be mistaken for review results. The queue can remain deferred in either design.

### Claude — plan revision 2

Codex's point is taken: Deal Flow ignores `?filter=review` on entry, so the link would land on ordinary candidates.
The desk control now carries the deferral itself (Codex's first option), and no link to Deal Flow can be mistaken for
review results.
- **The Review queue control.** It keeps its place, label and order among the five Machine-work controls, but it is
  disabled through the shared `components/Deferred/useDeferred` (`aria-disabled`, the `data-deferred` mark, an inert
  click).
  - Its reason is visible text right below the controls: "The Agent Review Queue arrives with the analysis port"
    (`NOT_PORTED.reviewQueue`, the same sentence Deal Flow's disabled chip uses). The control's
    `aria-describedby` points at it.
  - Activating the control by click or keyboard does nothing: no navigation, and no request.
- **No review links anywhere on the desk.** The deferred `review_queue` is `rows: []`, so the desk builds no
  `?review=` or `?filter=review` link. It shows no "Review" mission rows and no "analysed" activity items.
  - A unit test and the mocked e2e assert that no `href` on the desk contains `review=` or `filter=review`.
- **The other four controls are unchanged:** Find (`/deal-flow?find=1`), Deal Flow, Conviction, and the weekly
  drawer.
- **Tests from the desk:**
  - **Vitest:** the disabled control, its visible note, its `aria-describedby`, and a click that does not navigate.
  - **Mocked e2e:** the note is visible inside the opened Machine section; a click and an Enter on the control stay
    on `/` with no request; no review link exists.
  - **Preview e2e:** the same on the real snapshot.
- **Unchanged from revision 1:** the desk ships before the analysis port, one snapshot for `/api/home`, and the
  separately loaded panels.

### H-296 revision 2 verdict

**APPROVE for implementation.** Revision 2 resolves H-295. The visible explanation and its accessible description tell users why Review queue is unavailable from the desk. The planned browser checks cover mouse and keyboard activation, navigation and requests. They also verify that the desk generates no review links while the queue is deferred.

## Grok notes
