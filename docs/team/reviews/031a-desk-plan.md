# 031a — Plan: Investment Desk (the home read model and the page)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-297) · implementation APPROVED (H-303)

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

### Claude — implementation

**Backend**
- `home/` is the pure domain. `core.view(inputs, today, now)` is hand-ported line for line: every statement of the
  old body calls a loader or the machine clock, so no verbatim cut was possible. The expressions between those calls
  are verbatim and in the old order (the `[:6]`, `[:3]` and `[:5]` cuts, the 21-day window, `p-omar-hedeya`).
  - Instead of an AST cut, tests check two things: every string literal of `core.py` appears in the old `home()`, and
    the bodies of `readable` and `slug` are AST-identical to the old `_readable` and `radar.slug`.
  - It reuses the ported `conviction.records.safe_score` / `readable`, `conviction.operator.operator_status` (with
    `case=None`, so it reads `op.cases`, as the old `_load()["cases"]`), `dealflow.ranking.names.slug`,
    `events.plans.where_should_i_go`, `events.engine.listing` and `network.view.listing`.
- `home/inputs.load(conn, schema, now)` reads, on ONE connection:
  - the stored Conviction records (`entry_rows` + `record_of`, in stored order);
  - the people (file order), with the operator inputs from the same documents and people;
  - the Events store (`people=False`, with its pins);
  - the candidates as `ranking_input` builds them, in inbox order.
- `GET /api/home` (`api/routers/home.py`): one `snapshot_transaction` (decision c); the request clock as naive Berlin
  wall time (decision b).
- `ops/scratch_import.import_world(db_url, docs)` puts a golden world's documents through the production importer
  into a `pz_itest_*` schema. The required files a world lacks get empty collections. Today's hosted test now uses it
  too.

**Page** (`features/home/`)
- `Home.module.css` is byte-identical. The pure parts are in `model/` (`desk.ts`, `flow.ts`, plus `attention.ts`,
  `greeting.ts` and its test, verbatim). The components are `Desk`, `DecisionFlow`, `Tile`, `Card`,
  `UpcomingEvent` and `Machine`.
- **Reads:** `home`, `deal-flow/inbox`, `conviction/pipeline`, `today` and `sources`, staggered as before. There is
  no `review_queue` request.
- **The Review queue control (revision 2):**
  - it is third of the five, disabled through `useDeferred(NOT_PORTED.reviewQueue)`;
  - its `aria-describedby` points at the visible note `desk-review-note` below the controls;
  - the old `?filter=review` link is gone, and the desk renders no review link.
- **Invalidations:** `home` was added to Conviction, Network, Events, Founder Calls, the evaluator's end and trigger
  writes, and the Deal Flow decision.
- **Two typing notes, with behaviour unchanged:**
  - `omar[].feedback` is a boolean, as the old server sent it.
  - `sources[].last_ok` is a time string or `null` in both apps, so the old `last_ok === false` check never fired.
    It is kept literally.

**New declared difference (j): `new_signals` counts the merged Deal Flow.**
- On the real snapshot the old count is 1,019 (`inbox.json` with decision `new`); the new count is 1,055.
- The 36 extra are exactly the imported Scout-only candidates (`origins` within `legacy_scout00` / `legacy_native`)
  with status `new`.
- The merge (Deal Flow and Scout Intake are one) puts them in Deal Flow. The desk's own "Candidates to decide" tile,
  which reads the new inbox, counts them too. Excluding them from `new_signals` alone would make the brief and the
  tile disagree on the same page.
- The Map left such candidates out (025 (i)) because it also shows the Scout layer, so counting them would
  double-count. The desk has no Scout layer.
- The real parity checks that the difference equals that count; the golden worlds hold none.
- **Recommendation, under the standing instruction:** count them. Please challenge it.

**Finding outside this review: the importer and malformed inbox records.** An inbox record without an `id` (or a
Conviction record with no usable company) stops the import plan:
- the id-less inbox record with a `KeyError` in `map_pipeline`;
- the nameless Conviction record as a blocker.

The old readers ignored such records. The real snapshot has none, so the live import is unaffected. The hosted test
imports the worlds with such records left out (both readers drop them), and the answer still equals the old one.
Making the importer skip and report them would be a small follow-up of its own; it is not changed here.

**Verification (all pass)**
- **Goldens** (`parity_home check`): 5 invented worlds (`main`, `fallback`, `gated`, `legacy`, `empty`) against the
  old `ecosys.home()`, value by value and as text: 0 differences.
  - The inbox records now carry the markers every real Deal Flow record has (`discovery_tier`, `source_id`), so the
    importer keeps them whole. The goldens were regenerated with the oracle.
- **Real snapshot** (`parity_home real`): the importer into a throw-away schema, through the route, against the old
  view at 2026-11-13 09:00: 0 differences besides (j) (exactly 36), and all 49 tables unchanged.
- **Hosted** (`test_home_hosted.py`, 8 tests):
  - every golden world through the importer and the route equals the old answer, with every table unchanged;
  - the inbox order decides `latest_signals`;
  - a new-intake candidate counts with its tagging source name, and a Scout-only one counts (j);
  - the read is at REPEATABLE READ, READ ONLY.
- **Vitest** (66 desk tests):
  - every row branch, the summary forms, `gatedOf`, the best opportunity and its absence, the event, the tiles, the
    loading and errors;
  - the deferred control: disabled, the visible note, `aria-describedby`, a click and Enter that do nothing;
  - no review link.
- **E2e:**
  - `desk-mocked.spec.ts` (14 tests):
    - the composition, the flow trace, reduced motion;
    - every link (13 routes) and button landing on a ported route, the weekly drawer;
    - the deferred control: the note visible; a click, Enter and Space stay on `/` with no request;
    - no review link;
    - no overflow at 1366, 1920, 390 or 150 %.
  - `desk.spec.ts` (10 tests): the same checks on the preview database, GETs only.
- **Capture old vs new** (1366 and 1920, light and dark, 150 %): the same page.
  - The capture now waits for the `/api/today` answer (`settle`) before the screenshot.
  - Every difference is declared: the review rows and the "analysed" activity item (d); the retired Scout 00 card
    (030a c), so the triage mission moves up; 1,055 against 1,019 to decide (j); the shell's retired Scout entries.
- **Gate** (`scripts\check.ps1`): backend 1,790, frontend 767, PGlite: all pass. Today's hosted tests (9) pass on the
  shared import helper.

### H-298 implementation verdict

**REQUEST CHANGES before commit.** Two fixes need regression coverage.

- **Berlin date in production.** The Home router defaults to naive `datetime.now`, and `berlin_now` treats naive inputs as Berlin wall time. On a UTC server at 23:30 UTC in November, Home therefore reports the previous Berlin date and uses it for due people and event windows. The hosted route tests inject an aware clock, bypassing this branch. Use the Events router's aware Berlin default and cover the midnight boundary with no injected app clock. Today has the same fallback and can share the correction.
- **Scratch schema cleanup on exceptions.** `import_world` creates the schema before evaluating `build_plan(snapshot)`. An exception there or in `apply_plan` bypasses the cleanup for a refused result. The fixture only registers schemas after the helper returns, so teardown cannot recover this one. Drop the allocated schema on failure, preserve the original error, and exercise the raised-exception path.

**Accept difference (j).** The Home reader counts merged candidates with decision `new`, the same condition the desk tile uses. Scout origin alone gives no reason to exclude a candidate awaiting a decision. Handling malformed legacy records during import can remain a separate follow-up.

I ran the 13 backend Home tests successfully. The hosted, browser and full-suite results above are Claude's runs.

### Claude — implementation revision 2 (H-299)

Both of Codex's points are taken, and (j) is recorded as accepted.
- **The Berlin date in production.** A new `api/clock.berlin_request_now(request)` is shared by Home and Today.
  - With no injected `app.state.clock`, the instant is the aware `datetime.now(BERLIN)`, as in the Events router, so
    a UTC server answers the Berlin date.
  - An injected clock is still converted when aware, or taken as Berlin wall time when naive.
  - **Regressions:**
    - `tests/api/test_berlin_clock.py`: no clock, with the machine at 23:30 UTC on 13 November, gives 00:30 on
      14 November. Aware (UTC and another zone) and naive injected clocks give the same.
    - Hosted, with no `app.state.clock` and the machine at 23:30 UTC: `GET /api/home` answers
      `date 2026-11-14 · Saturday`, and `GET /api/today` answers `date 2026-11-14`.
  - **Finding beyond this review:** Conviction's router (`api/routers/conviction.py:_clock`) has the same naive
    `datetime.now` fallback. It is a separate, already-approved view, so it is not changed here; the fix is the same
    one-line switch to `berlin_request_now`. Please say whether to fold it in.
- **Scratch-schema cleanup.** In `ops/scratch_import.import_world`, everything after the schema is created runs
  inside one `try`. Any exception from `build_plan` or `apply_plan`, or a refused plan, drops the schema through
  `drop_schema`, and the original error is re-raised. `drop_schema` refuses any name that is not
  `pz_(itest|rehearse)_<hex8>`.
  - **Regression (hosted):** `build_plan` raising, `apply_plan` raising, and a refused plan, each with a fixed schema
    name. The caller gets the original error (the invented `Boom`, or `ValueError` for the refusal), and the schema
    no longer exists.
- **Re-run, all pass:** the desk and Today hosted tests (10 + 9); the gate (backend 1,794, frontend 767, PGlite).

### H-300 implementation revision 2 verdict

**REQUEST CHANGES to the hosted cleanup test.** Home and Today now use the Berlin clock helper, and the import helper attempts cleanup on all three reported failure paths. I ran the Home and clock unit suites (17 passing) and inspected the hosted regression cases. Claude reports the hosted suite passed.

The cleanup regression forces every run to use the same three database schema names. Two test runs sharing a hosted database can therefore operate on or drop each other's schema. Keep the production random name generation and capture the allocated name with a test spy on `_scratch_sql` that forwards to the original. Use that captured name for the absence check after each failure. Re-run the hosted cleanup case with this change.

Track Conviction's clock separately. Its helper serves both reads and writes, so check date-sensitive views and persisted timestamps together when changing that router.

### Claude — implementation revision 3 (H-301)

Codex's point is taken: the cleanup regression no longer fixes the schema names.
- The production random name (`pz_itest_` plus 8 hex digits from `secrets.token_hex`) is kept, so concurrent runs
  never share a schema.
- A spy on `scratch_import._scratch_sql` forwards to the real `db_check._scratch_sql` and captures the name the helper
  allocated, once per failure path. The test asserts that exactly one name of the scratch form was allocated, and
  that this schema no longer exists after each failure.
- Conviction's clock is tracked separately, as Codex asks: its helper serves reads and writes, so date-sensitive views
  and persisted timestamps will be checked together when that router changes. It is not changed here.
- **Re-run, all pass:** the desk hosted tests (10), the cleanup case on its own, and the gate (backend 1,794,
  frontend 767, PGlite).

### H-302 implementation revision 3 verdict

**APPROVE for commit.** I verified that the cleanup test captures the production-generated schema name and forwards it to the real migration SQL. After a planning exception, an application exception, and a refused plan, the test checks the expected error and queries the database for that case's captured schema. This resolves H-301. Claude reports that the isolated cleanup case, all 10 hosted Desk tests, and the full gate passed.

## Grok notes
