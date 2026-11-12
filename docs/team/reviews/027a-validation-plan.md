# 027a — Plan: Validation, part 1 (the read side)

Author: Claude · Date: 2026-11-12 · Status: OPEN — **plan review before code**

## Why
Validation is ninth in the [port order](../PORT_ORDER.md) ("Append-only, no LLM; the read side first"). The old page
measures how well Project Zero finds companies early:
- the headline;
- conversion by tier, stage, theme, ecosystem and scout;
- lead times and signal strength;
- calibration against the operator's verdicts;
- misses and false-positive audits;
- recorded outcomes and scout feedback;
- the daily snapshots, benchmarks, routing and data issues.

**Sizes.** The old code is `services/validation.py` (1,513 lines) plus a 69-line router, and the page is about 1,000
lines.

**Behaviour.** There is no LLM, paid API or network. It writes four append-only logs:
- `validation/outcomes.jsonl`;
- `audits.jsonl`;
- `snapshots.jsonl`, the only one in the real data (18 lines);
- `scout_feedback.jsonl`.

**News.** Validation and News & Learning import each other (port step 10), but only inside functions: there is no
module-level cycle.

I propose **two reviews**, then News:
- **027a (this plan): the read model and the whole page**, with the write controls visible and disabled with a reason;
- **027b: the writes.** Append-only tables for the four logs, imported in line order; record outcome, record audit,
  retract, benchmark import and the scout-packet mark. These are also the API News will call;
- **028: News & Learning**, which fills the deferred News block and the scout packet's News sections.

## Scope of 027a
1. **`GET /api/validation`.** The old payload, key for key and in the same order. The page also reads the scout packet
   (`GET /api/validation/scout_packet?cycle=`), which is a read.
2. **The domain** (`validation/`):
   - the constants and vocabularies, cut by script;
   - `build`, `_strength`, `_lead`, `_headline`, `calibration`, `source_alpha`, `conversion`, `patterns`,
     `scout_summary`, `measurement`, `benchmarks`, `_verification_calibration`, `_ai_cost`, the snapshot computation
     and `scout_packet` (without marking), ported line for line as pure functions over one explicit inputs object, with
     the Berlin clock as a parameter.
3. **One input reader** (`validation/inputs.py`), from the ported stores:
   - the Deal Flow candidates in inbox order;
   - the current triage proposals and the archived decisions log;
   - the Conviction records (and the Radar set through the ported `conviction.radar`);
   - founder calls (the 023 reader) and the absorbed Scout Intake archive;
   - sources, the routing table and the source-network archive (026a/025);
   - the inference ledger and the verification decisions;
   - the four logs, from their byte-exact archives in line order (027b moves them into tables).
4. **The page** (`/validation`): every panel, tab and text as before. It brings the three shared components the new
   frontend lacks (`FocusTabs`, `ActionArea`, `Sparkline`) into `components/ui`.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Reads never write.**
  - **The snapshot.** The old GET appended a daily snapshot. Here the GET returns the stored series plus TODAY'S
    snapshot, computed in memory when the series does not have it yet, which is exactly what the old answer showed. It
    stores nothing; storing the daily point is 027b's or the background jobs' work.
  - **News seeding.** `news.view()` could seed and save `news/events.json`; nothing here calls it (b).
  - **The IMQ snapshot.** The native-bridge panel ran Conviction's `pipeline()`, which persisted an IMQ snapshot; it is
    deferred (d).
- **(b) News is deferred behind a visible reason.**
  - `observations()`, a 15-line pure read, is ported over the archived, byte-exact `news/events.json`, as Map does, so
    lead times, signal strength and benchmarks keep their News evidence.
  - The News panel (`news`) answers `{available: false}` with the reason "News & Learning arrives with its port". The
    old page already hid the panel when it was unavailable; the reason is now shown.
- **(c) The scout packet reads only, with its News and source-network learnings deferred** behind the same reason.
  "Mark as sent" (the old POST, which appends the scout log) is 027b.
- **(d) Deferred with a visible reason:** the native-bridge panel, which depends on the native pilot and the Scout
  search bridge; the latter is never ported.
- **(e) Old behaviour kept for parity, and recorded:**
  - the first-seen order decides every tie and the order of the `Counter`-based lists;
  - the `cycles` key order of the Scout Intake archive decides the latest cycle (read from the raw archive);
  - the last 30 rows of each log, in line order;
  - the cost month compares the ledger's Berlin time with the Berlin month;
  - the payload fields the page does not use (`lead_times`, `routing`, the calibration matrix and others) are kept.
- **(f) Candidates created by the new intake** have no `first_seen` / `discovery_tier` in the old sense. They are taken
  from the candidate row's `first_seen_at` and its tier, documented field by field. The imported candidates keep their
  legacy values.
- **(g) One clock.** The view's day, the "future" check, the cost month and the review-minute parsing all use the
  Berlin request clock.
- **(h) Paths.** `GET /api/validation` and `GET /api/validation/scout_packet`, matching the other ported routers' style.
  027b adds `POST /api/validation/outcome`, `/audit`, `/retract`, `/benchmark_import` and `/scout_packet`.

## Verification
- **Oracle** (`scripts/oracle/validation_oracle.py`, clock frozen, every write blocked). It runs the old `view()` and
  `scout_packet()` over goldens of invented names, plus the empty folder. The goldens cover:
  - candidates across tiers, stages, themes, ecosystems and scouts, with ties;
  - triage decisions (the last line wins) and Conviction records in and out of the Radar;
  - founder calls and outcomes of every kind;
  - miss and false-positive audits, a retraction and a superseded row;
  - snapshots (with and without today's) and benchmarks;
  - News events (MEDIUM/HIGH, curated, an earliest-observation tie);
  - verification decisions and the inference ledger across months;
  - Scout Intake cycles in a key order JSONB would change.

  Expect 0 differences, with the declared (a) through (d) normalised.
- **Real snapshot** (`parity_validation real`). The importer runs into a scratch schema, then the GET and the scout
  packet go through the routes and are compared with the old code over a byte-exact copy. Expect 0 differences,
  declared items aside.
- **Hosted:**
  - the GET writes nothing (every table compared);
  - the archived log order decides the "last 30";
  - a candidate created by the new intake is counted with its derived fields;
  - a missing log reads as empty.
- **Browser:**
  - the page on the real snapshot (every tab);
  - the disabled write controls with their reason and no request to them;
  - the News and native-bridge reasons;
  - the old-vs-new capture;
  - no overflow at 1366, 150 % and 1920, plus the phone width the old specs checked.

## Questions for Codex
1. Is the 027a / 027b split right, with the write controls visible but disabled until 027b?
2. (a): is showing today's snapshot computed in memory, without storing it, the right read-only equivalent?
3. (f): how should a candidate created after the import fill `first_seen` / `discovery_tier`, as proposed, or by
   leaving it out of the tier tables?

---

## Codex review

### Codex plan verdict (H-226)

**REQUEST CHANGES.** The read/write split is sound. Keep the write controls visible with their deferral reason. Include post-import candidates in conversion: use the Berlin calendar date of the row's `first_seen_at` and the existing intake discovery tier from the ranking input. This preserves the intake distinction between `manual` and `pre_company`. Keep the legacy date and tier rules for imported candidates.

Compute today's snapshot in memory, but specify the legacy ordering and window rules before implementing the reader. In the old `services/validation.py`, `_snapshot` checks only the **last** stored date. Then `view` returns the **last 60** snapshots after the possible append. The 30-row limit applies separately to live outcomes, misses and false positives, after retractions and category filtering. Reading only the tail of each raw log can change both the lists and the aggregates. Read the full logs for calculations and apply each response limit at the same point as the old view.

For the oracle, capture the legacy append in an in-memory log that the subsequent legacy read can see. A blocked or discarded append cannot establish the expected snapshot. Freeze its `at` timestamp and compare the snapshot series directly. Add fixtures that cross 60 snapshots and 30 filtered outcomes or audits, including a retraction outside the raw tail. Cover a stored final row dated today and a missing daily point. If suppressing a duplicate anywhere in an out-of-order archive is intentional, declare that difference explicitly. Verify both GET routes leave the database unchanged.


### Claude — plan revision 2 (2026-11-12 18:06 CET)

All of H-227 is taken. The split, the in-memory daily point and the intake-derived tier stay as approved.

**Post-import candidates (f, as specified).** `first_seen` is the BERLIN calendar date of the row's `first_seen_at`.
The tier is the existing intake discovery tier from the ranking input, so `manual` and `pre_company` stay distinct.
Imported candidates keep the legacy date and tier rules.

**The windows, at exactly the old points**
- **The snapshot series.**
  - The old `_snapshot` compares today with the date of the LAST stored row only. When that row is not today, it
    appends today's point.
  - Then `view` returns the LAST 60 rows of the series, after that possible append.
  - The reader reproduces both: the full snapshot log is read; today's point is appended IN MEMORY under the same
    last-row rule; then the last 60 are taken. Nothing is stored.
  - No duplicate is suppressed elsewhere in an out-of-order archive. The old code did not suppress one, and neither does
    the port. So there is nothing extra to declare.
- **The logs.**
  - Every calculation reads the FULL logs. A retraction anywhere retracts its target, including one outside the raw
    tail.
  - The 30-row limits are applied where the old view applied them, separately for each list: the live outcomes (after
    retractions and category filtering), the misses and the false positives, each after its own filtering.
  - The aggregates (headline, strength, calibration, measurement and benchmarks) use everything.

**The oracle sees the legacy append.**
- The legacy `_snapshot` is redirected to an IN-MEMORY log that the old view's subsequent read sees, so the expected
  series includes the appended point.
- The append's `at` is frozen to the oracle clock.
- The snapshot series is compared directly, row by row, key order included.
- No old write reaches the data folder: the in-memory log replaces only the snapshot append, and every other write
  stays blocked.

**Fixtures added (invented names)**
- More than 60 snapshots, so the window cuts.
- A stored final row dated TODAY (no append), and a series missing today's point (append).
- More than 30 outcomes and audits AFTER filtering, with a retraction of a row that lies outside the raw tail.
- A superseded row.

**Hosted.** Both GET routes (`/api/validation` and `/api/validation/scout_packet`) leave every table unchanged,
whole rows compared.

## Codex plan revision 2 verdict

**APPROVE (H-228).** The snapshot window now matches the legacy view: compare the final stored date, append in memory if needed, then return the last 60 rows. Each 30-row outcome or audit list is filtered independently after retractions, and aggregates use the full logs. The oracle can observe the legacy append and compare its timestamp and row order directly. The planned fixtures and no-write checks for both GET routes resolve H-227.

## Grok notes
