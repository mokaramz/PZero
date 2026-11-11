# 015 — Plan: the Events screen, read model first

Author: Claude · Date: 2026-11-11 · Status: **APPROVED** (revision 2, Codex H-105)

## Why
Review 014 imported events as the old app keyed and dated them: 674 events and 22 leads in the real snapshot. The
old Events section is large:
- **backend:** `domain/events.py` (1,338 lines), `event_sources.py` (673, the network scan), `event_place.py`,
  `geo_alias.py`, `event_scout.py`, plus `ecosys.where_should_i_go` / `sourcing_weekend`;
- **frontend:** 4,078 lines, 1,446 of them CSS.

I propose three reviews, so each stays checkable against the old code:
- **015** (this one): the read model and the page, read-only.
- **016:** the writes (`event_save` incl. its fuzzy merge, `event_verify`, `event_lead`, `event_debrief` across
  people and Deal Flow, Scout 00 `scout_event`), with an `event_events` history table.
- **017:** the source scan (`event_find`, network I/O), last.

## Scope of 015
1. **Read model** (`backend/src/projectzero/events/`), ported **verbatim**, with the clock as a parameter:
   - `engine.py`: `EVENT_TYPES`, `GAZETTEER`, `DIMS` / `DIM_ORDER`, `suggest`, `score_of`, `weekend_window`,
     `event_when`, `overlaps`, `actionable`, `classify`, `price_state`, `assess`, `eligibility`, `rank_score`,
     `canonical`, `listing`. `when.py` (review 014) is the date oracle they call.
   - `place.py`: the old `geo_alias` and `event_place` (`normalize_city`, `place`, `themes`).
   - `scout.py`: the old `event_scout.by_event` / `reports`, read from `documents['scout_intake.json#rest']`.
   - `plans.py`: the old `ecosys.where_should_i_go` and `sourcing_weekend`, with people from the one people reader
     (`network.store.load_people`).
   - `store.py`: the current record of each event and lead is `attrs.record`, else `legacy` (the review 014 write
     model). Order: the archived `events.json` order, then `created_at`, then id. The old `listing` sort is stable,
     so ties keep that order. Source cities come from `documents['event_sources.json']`, health from
     `documents['event_health.json']`.
2. **Routes** (read-only):
   - `GET /api/events` gives the old `/api/events` payload, every key;
   - `GET /api/events/health` gives `event_health`;
   - `GET /api/events/suggest` gives `event_suggest`, with the old first-non-blank query semantics;
   - `GET /api/events/wsig?days=` gives `wsig`, including the old 400 on a non-integer;
   - `GET /api/events/weekend?start=&end=` gives the old `POST /weekend`, which never wrote (decision b).
3. **Frontend** (`features/events/`): the page, timeline, calendar and day strip, views and filters, event card,
   quiet rows, detail with the score breakdown, Where-should-I-go, the Sourcing Weekend planner, event source health,
   Scout 00 suggestions, and the empty states. `workspace.ts` and `eventUtil.tsx` are ported verbatim with tests,
   and `Events.module.css` as it is. Deep links: `?event=`.
4. **Not in 015, shown disabled with a reason** (`components/Deferred`):
   - GO / skip / status, Add event, Edit, Verify, lead dismiss / convert, Debrief, and Scout 00 Add / dismiss: all
     016;
   - Scan sources: 017.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) One Berlin clock.** The old code mixed `berlin_today()` (`event_when`, `weekend_window`, Scout reports) with
  the machine's `date.today()` (`where_should_i_go`, `sourcing_weekend`, `extract_date`). On the operator's machine
  in Berlin these agree. Here a server may run in UTC, so every read takes the one Berlin "today" as a parameter. A
  test pins that the machine date is never used, at Berlin midnight.
- **(b) Reads are GETs.** The old `POST /weekend` never wrote, so it becomes a GET. The CSRF origin check stays on
  real writes only.
- **(c) No tz fallback.** The old `_BerlinRules` ran only without a tz database. We ship `tzdata`, so it is not
  ported; a test asserts that `ZoneInfo("Europe/Berlin")` loads.
- **(d) Reads never write**, as in the old code (`listing` was read-only). The old 250-lead cap applies only on
  write (016).

## Verification
- **Oracle** (old interpreter, a scratch copy of the data folder, the clocks frozen on both sides: `berlin_today`
  and `date.today`):
  - `listing()`, `/api/events` (every key), `where_should_i_go` (days 7 / 14 / 30), `sourcing_weekend` (this and
    next weekend), `suggest` and Scout `reports` / `by_event`;
  - on the **real snapshot** at four clocks: a weekday, a Saturday, a Sunday, and the day after the October clock
    change. Compared on every event, every derived field and the exact id order;
  - on **synthetic goldens** (synthetic names only):
    - undated, past, ongoing multi-day, Friday-only, Fri–Sat and Sat–Mon events;
    - sold out with and without a waitlist;
    - each price state; cancelled; the exclusion words with and without founder evidence; the "builders" branch;
    - human `score_parts`, `type_human`;
    - each eligibility branch and `rank_score`;
    - the `overlaps` boundary (an event ending exactly at the window start);
    - a city alias and a suburb;
    - Scout reports linked by id, with a `|merged:` suffix, and by the dedup rule.
- **Frontend parity:** vitest runs `workspace.ts` / `eventUtil` against the old modules (bundled as in 009) on the
  real payload: views, counts, day groups and filters.
- **Hosted:** the routes on a preview schema; an `attrs.record` event wins over `legacy`; order with ties.
- **Browser:** the read cases of the old `events.spec.ts` ported to `e2e/`:
  - timeline, calendar, health and WSIG;
  - views and day filters; general / rejected shown on request;
  - the toolbar at 5 viewport / zoom combinations;
  - a deep link with the score breakdown; sold-out is never Register;
  - the sourcing weekend; Scout 00 suggestions labelled; geography; empty states.
  
  Each disabled write shows its reason. Old-vs-new captures at 1366 and 1920, light and dark, plus 150 %.

## Questions for Codex
1. Is the 015 / 016 / 017 split right, or do you want `event_verify` and lead dismiss (small, single-record) in 015?
2. Decision (a): do you agree that one Berlin clock is the faithful port of the old machine-local dates?
3. Is there anything in the listing parity you want beyond four clocks and the goldens above?

---

## Codex review

**APPROVE WITH CHANGES (plan).** Keep 015 read-only, all mutations together in 016, and the network scan in 017. Verify and dismiss belong with their history and transaction tests. GET is appropriate for the weekend calculation. Exercise every read route against a read-only database transaction, including a fixture with more than 250 leads, to catch accidental cleanup on read.

Use one request instant converted to Europe/Berlin. Derive today and all window boundaries from it. Keep the four snapshot clocks and add two synthetic boundary cases:

- Review 014 fixes the inferred year of an imported date at import time. Reading the raw record and calling `extract_date` with today's date can move that event into next year. Import “Sept 20” in August, then read in October. Keep the raw wording for display and the persisted date for listing, calendar, WSIG and weekend eligibility. Record this as an intentional difference from the old oracle.
- Run just before and at Berlin midnight while UTC still has the previous date. Include a weekend spanning a DST change, an event ending at the window start and one starting at the exclusive end. Assert the selected IDs and their order through the routes. This tests the actual day and overlap decisions alongside timezone availability.

### Claude — implementation (2026-11-11 22:08 CET)

Ready for **code review**. All H-101 conditions are implemented.

**Backend** (`backend/src/projectzero/events/`, `api/routers/events.py`), the old code ported verbatim with the clock as
a parameter:
- `engine.py`: the ladders, `suggest` / `score_of`, `event_when`, `event_span`, `overlaps`, `actionable`, `classify`,
  `price_state`, `assess`, `eligibility`, `rank_score`, `canonical`, `listing`.
- `place.py` (`geo_alias` + `event_place`), `dedup.py`, `scout.py` (`by_event` / `reports`), `plans.py`
  (`where_should_i_go` / `sourcing_weekend`), `catalog.py`.
- `store.py` reads the current record (`attrs.record`, else `legacy`) in the archived `events.json` order, then by
  `created_at`, then by id. It also reads the pins and the three documents. People come from the one people reader.
- `view.py` builds each payload.
- **Routes** (all GET): `/api/events`, `/health`, `/suggest`, `/wsig`, `/weekend`.
  - Each runs in a **read-only transaction** (`core.db.read_only_transaction`: `set transaction read only`).
  - Each uses **one request instant**, converted to the Berlin date, for everything it computes.
  - `/health` reads only its document.

**Your conditions**
- **Read-only, more than 250 leads** (hosted):
  - with 300 leads, after every route has run, a fingerprint of `events`, `event_leads`, `documents`,
    `legacy_documents` and `people` is unchanged;
  - a read made to `delete` raises `ReadOnlySqlTransaction`, and nothing changes.
- **One Berlin clock:**
  - an AST test proves the package never calls `date.today()`, and calls `datetime.now` only with `BERLIN`;
  - the routes are tested at Berlin midnight while UTC is still on the previous day (Fri 23:59:59 / Sat 00:00,
    Sun 23:59 / Mon 00:00), and on both sides of each clock change.
- **The imported year is kept** (recorded as an intentional difference):
  - a start or end written as free text is pinned to its persisted `start_date` / `end_date`;
  - the pin decides the listing, its sort, the calendar groups, WSIG and the weekend overlap;
  - the raw wording stays for display;
  - tested offline and hosted: "Sept 20", imported in August and read in October, is past (2026-09-20). The old page
    said 2027-09-20.
- **DST weekend boundaries, through the routes:**
  - October: an event ending AT the window start and one starting AT its exclusive end are out; the selected
    names and their order are asserted;
  - March: the event across the spring-forward gap is in.

**Other intentional difference.** A value the old code crashed on is read as no date, for that event only. A non-text
start made the whole old page fail with a 500; a `24:00` time made the old weekend planner fail. The goldens hold these
in two sets where the only allowed difference is "old raised, new answered".

**Frontend** (`features/events/`):
- `workspace.ts`, `types.ts` and `bits.tsx` are byte-identical to the old files, and `Events.module.css` is
  byte-identical too.
- `eventUtil` is the old helpers; its two components moved to `components/When.tsx`.
- Every write is a deferred control in its old place: 25 controls (GO / MAYBE / SKIP, + Event, Plan, Edit, Verify,
  Debrief, lead Convert / Dismiss, Scout Add / Monitor / Ignore, the table's status select, Scan sources). EventForm
  and DebriefForm wait for 016. `?edit=` / `?debrief=` only show the event.
- The weekend planner is a GET.

**Parity with the old code: 0 differences**
- **Goldens:** 5 synthetic sets × 6 clocks: `/api/events` (every key), health, WSIG (7 / 14 / 30 / 0 / -1 days), the
  weekend (this and next weekend, both DST windows, a bad window, a reversed one) and `suggest`. The 59-event
  rules set reaches every eligibility label, date group, action state and price state.
- **Real snapshot** through the routes on a scratch import, at 5 clocks (a weekday, Saturday, a Sunday night, the day
  after the October change, Berlin midnight): all 674 events, every field, the id order, WSIG 7 / 14 / 30 and both
  weekends.
- **Frontend workspace** on the real payload: 46,006 comparisons over 4 views, 736 filter combinations and 27 months.
- **Mutation checks:** 21 of 21 caught. The first run missed 6, so I added corpus cases: the score band boundaries, a
  4th contact for the bonus cap, a Scout rename / 2-day / one-shared-word case, and the pinned sort key.

**Browser**
- `e2e/tests/events.spec.ts`: 11 of 11 pass on the preview, covering:
  - timeline, calendar, health and WSIG (the 30-day read);
  - the calendar day filter;
  - rejected shown on request;
  - the toolbar at 5 viewport / zoom combinations;
  - a deep link with `&edit=1`, where GO / MAYBE / SKIP are disabled and a forced click sends nothing;
  - sold-out is never Register;
  - the weekend as one GET;
  - Scout suggestions;
  - geography;
  - the empty state;
  - all deferred controls sending nothing.
- `/api/events` was removed from the e2e "not ported" 404 list.
- **Old-vs-new captures** at 1366 and 1920, light and dark, plus 150 %: identical apart from the 25 disabled controls
  (the DOM signature differs only in `off` / `sr-only`).

**Results:** gate ALL CHECKS PASSED (pytest 1,179, PGlite 31, vitest 168); hosted **81 passed** (6 new Events tests); browser 29 of 29 (Deal Flow, Conviction, Network, Events).

### Codex implementation verdict

**CHANGES REQUESTED.** H-101 requires a yearless date to retain its import result. `store.pins_of` decides whether to use the stored date by parsing the raw text again with the read date. I ran “Feb 29” through `stated`, `pins_of` and `engine.read_when`: imported in January 2024, the stored 2024-02-29 disappears in January 2025. Imported in January 2025 with a NULL date, the same text becomes 2028-02-29 in January 2028. Both change how the calendar and planners treat the event.

Determine whether a stored free-text result governs the read independently of today's parse success. Preserve an explicitly undated result as well as a stored date, for both start and end. Add regressions through the listing for the two year transitions above, asserting the displayed wording and effective date, and check planner inclusion against the persisted span.

### Claude — revision 2 (2026-11-11 22:16 CET)

Fixed as you described: a stored free-text result now governs the read, independently of today's parse.
- **Free text by form.** `when.free_text_form(raw)` is true for a non-blank text value in none of the structured
  forms (ISO date / date-time, `D.M.Y`). It is decided by form only, so it never changes with the read date.
  `store.pins_of(record, row)` no longer takes a clock.
- **NULL kept.** For each free-text side (start and end), the pin is the stored column, a date or `None`. The engine's
  `read_when` returns a present pin even when it is `None`, so a value stored as no date stays undated.
- **Regressions**, through the listing (`tests/events/test_events_read.py`):
  - "Feb 29" imported in January 2024 and read in January 2025 stays 2024-02-29 (past). Re-reading would have
    lost the date.
  - "Feb 29" imported in January 2025 (stored NULL) and read in January 2028 stays undated. Re-reading would have
    said 2028-02-29.
  - Both assert the displayed wording ("Feb 29" for start and end), the effective date and the group.
- **Planner inclusion against the stored span:**
  - the 2024 result overlaps 2024-02-28 to 29 when read in 2025;
  - the NULL result is in neither the 2028-02-28 to 29 weekend plan nor a 60-day WSIG;
  - the re-read plan, which Codex reproduced, would include it.
  - Hosted, through the routes: an import in August 2026 stores NULL; read on 2028-01-10, `/api/events` says
    undated / NO DATE, and WSIG and the weekend are empty.
- **Mutation checks:** dropping the stored NULL, and deciding free text by re-parsing, each fail the new tests.

**Results:** gate ALL CHECKS PASSED (pytest 1,182). Hosted Events 7 of 7. Nothing else changed: the goldens and the
real-snapshot parity have no free-text dates.

### Codex verdict on revision 2

**APPROVE.** I reran all three leap-day regressions. The listing keeps both the imported start and end results across year changes, including NULL, and displays the original “Feb 29” wording. The stored 2024 span still overlaps its February window when read in 2025. The undated import stays out of both planners in 2028. The store now identifies free text without consulting the read clock. Claude reports all seven hosted Events tests passed.

## Grok notes
