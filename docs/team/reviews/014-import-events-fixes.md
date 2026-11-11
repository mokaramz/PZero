# 014 — Importer fixes for events, before the live import

Author: Claude · Date: 2026-11-11 · Status: OPEN — **code review** (small, urgent: the live import has not run yet)

## Why
Mapping the old Events feature for its port surfaced defects in how **our** importer (`ops/legacy/map_records.py`
`events()`) mapped `events.json`. As in reviews 010 and 012, the raw record is still kept byte-exact in `legacy`, so no
data would have been lost. The promoted columns would have been wrong in `pz`, though, and the Events port would have
inherited them.
1. **Ids (G1).** An event without an `id` crashed the mapper (`e["id"]`); the old `events.upsert` would have crashed on
   it too. Two events with one id made `apply` fail on the primary key instead of failing at plan time.
2. **Dates (G2/G3).** `start` / `end` went through the generic `day()`, not the old `parse_when`:
   - a date-only end became the midnight that **starts** that day, while the old `event_span` ends a date-only event
     at the **next** midnight (exclusive end);
   - a missing end was `NULL`; the old app reads it as the end of the start day;
   - a stated time could not be told from midnight, so "no time stated" was lost;
   - `DD.MM.YYYY` and free text ("Sept 20") were `NULL`, and seconds were kept where the old app drops them.
3. **`created_at` (G4)** ignored the old `created` day: every event would have been "created" at import time.
4. **Empty strings (G5)** reached `city` / `country` / `url` / `status` as `''` (17 cities and 17 countries on the
   real snapshot).
5. **`lat` / `lng` (G6)** accepted bools (`isinstance(True, int)`) and out-of-range or non-finite numbers, and silently
   dropped numeric strings.
6. **Status values (G7)** were not reported.
7. **The events write model (G8) was undefined**: an imported field named `record` would have been copied into `attrs`,
   where the people reader rule (review 012, H-078) treats it as the application's record.
8. **Leads (G9)** had no table: the 20 leads were only an `events.json#rest` document.
9. **Scout 00 event reports (G10)** kept the `"<id>|merged:<name>"` value the old `events.upsert` returned when it folded
   a report into an existing event, so 9 of 40 `event_id`s matched no event. `DATA_MODEL.md` also claimed the reports
   go to `events`.

## Changes
- **New `projectzero/events/`** (the Events context, not ported yet):
  - `when.py`: the old `parse_when`, `extract_date`, `_aware` and `event_span` (`domain/events.py` at `6c739b9`),
    ported **verbatim**, raising where the old code raised. The one change is the clock: `extract_date` read
    `date.today()` to give a year to "Sept 20"; here `today` is a required keyword. New, and never raising:
    - `stated(raw, today)`: one value as `absent` / `date_only` / `timed` / `unparseable` (with the reason);
    - `span_of(start, end)`: `starts_at` / `ends_at`, the old `event_span` over the stated values.
  - `columns.py`: the ONE mapping of an event or lead record onto its columns and `attrs` (`event_columns`,
    `lead_columns`, `coordinate`, `text`), for the importer now and the Events writes later, like
    `network.people.columns_of`.
  - `__init__.py` documents the write model (Decision 7).
- **`events()` in `map_records.py`:**
  - `_keyed` applies the people rule (review 012) to events and leads: a record without an id, or not a record, is
    skipped and listed (`skipped_without_id`, with position and name / title); a repeated id is an **import blocker**
    naming both records, and only the first becomes a row.
  - Dates via `event_columns` at the Berlin date of the import clock (`dates_clock` in the report). The report counts,
    per side, `date_only` / `timed` / `unparseable` / `absent` / `free_text`, the reasons for unparseable values, and
    ends before their start.
  - `created_at = day(created)`, else the import time (`created_at_from_import_time`).
  - Text, coordinates and status as in Decisions 4–6; the report has per-axis coordinate counts and status counts.
  - **Leads** (`_leads`) become `event_leads` rows. The report gives `in`, `rows`, `open` (decision `new`) and the
    decision counts. A decision outside `new | dismissed | converted` is a blocker.
- **`documents()`**: `events.json` is now fully modelled, so there is no `events.json#rest` document any more. In
  `scout_intake.json#rest`, each event report's `event_id` loses its `|…` suffix (`_scout_event_ids`, counted as
  `event_id_merge_suffixes_stripped`); `legacy_documents` keeps the original bytes.
- **Migration `20261111000007_event_dates.sql`** (ONE `DO` statement, like 0003 / 0005):
  - takes the `ACCESS EXCLUSIVE` lock on `pz.events` first, then **refuses to run if the table has rows**: the new
    columns can't be derived in SQL from rows written under the old meaning of `ends_at`, so it never invents them.
    The live table is empty.
  - adds `start_date date`, `start_time text`, `end_date date`, `end_time text`, with checks: a time is `HH:MM`
    (00:00–23:59), a time needs its date, the span exists exactly when there is a start date, and `ends_at > starts_at`;
    plus an index on `start_date`;
  - creates `pz.event_leads` (`id` text primary key, `title`, `source`, `url`, `city`, `type`, `lead_date`,
    `date_raw`, `confidence`, `detected_on`, `decision` default `new` with a check, `note`, `attrs`, `legacy`,
    `created_at`, `updated_at` with the touch trigger), a partial index on open leads, RLS on and the API grants revoked;
  - it is pushed with 0002–0006, right before the import.
- `TABLE_ORDER` gains `event_leads` (after `events`).
- **Oracle:**
  - `scripts/oracle/events_when_oracle.py` and `ops/parity_events.py`. `goldens` writes
    `golden_v1/oracle_events_when.json`: 100 synthetic values and 30 start / end pairs at two fixed clocks, from the
    old interpreter at revision `6c739b9`, clean tree, with ZoneInfo Europe/Berlin.
  - `real` compares every event start and end, every lead date and every event's span from the real `events.json`,
    and prints only counts and positions.
- **Docs:** `DATA_MODEL.md`: the table row for Scout Intake events (line 23) is corrected, `event_leads` is added, and
  there is a new events paragraph. There is also a line in the golden README.

## Decisions
1. **Ids (G1).** A record without an id is skipped and reported. A repeated id blocks the import and is not suffixed:
   the old `next(e for e in events if e["id"] == eid)` reached only the first record, so choosing for the operator would
   silently drop one. The same applies to leads. A lead whose `decision` is outside the vocabulary also blocks: the
   old API stored any value (`decide_lead`), and the old `/api/events` lists only `new` leads
   (`api/routers/events.py:37`), so mapping one would invent a decision. Today there are none of either. **Ids are not format-validated (G15):** `ev-<slug>-<date>` /
   `evlead-…` are conventions, not rules, and any non-blank id is kept as text.
2. **Dates (G2/G3), the old semantics, kept as stated:**
   - `start_date` / `start_time`, `end_date` / `end_time` are each value as the old `parse_when` reads it: the Berlin
     wall-clock date and an `HH:MM` time. `NULL` time means no time was stated; `NULL` date means none was stated or it
     is unparseable. Seconds are dropped and an offset time is converted to Berlin, as the old app did.
   - `starts_at` / `ends_at` are derived instants: the old `event_span`. `starts_at` is the start (Berlin midnight for
     a date-only start). `ends_at` is **exclusive**: a date-only end is the next Berlin midnight; a missing,
     unparseable, earlier or not-later end gives the end of the start day. No start date means no span, even when an
     end is stated.
   - An end before its start is stored **as stated**, with no check constraint. The old `event_when` reads it as the
     start; it is counted (`end_before_start`).
   - **Spans the database would refuse block the import** (H-097). The old code compared Berlin wall-clock times, so
     a start inside the spring-forward gap (`2026-03-29T02:45` → `03:15`) gives a span that runs backwards in UTC,
     and a start on `9999-12-31` has no exclusive end (`OverflowError`). `events.columns.checked_span` checks the
     derived instants in UTC and catches the overflow; either case is a blocker naming the event, its name and its
     stated start and end, and the row is not written. `events/when.py` (the oracle) is unchanged.
   - **Unparseable values** stay `NULL`; the raw value stays in `legacy` and, when non-blank, also in `attrs` under
     its key. Unparseable means:
     - not text;
     - no date found;
     - a value the old `parse_when` raised on (`+99:00` offsets, year 1 / 9999 overflow);
     - an out-of-range time such as `24:00`. The old `parse_when` returns it, but its `event_span` raises on it, so
       the date is not kept half-way.
   - **A free-text date without a year** ("Sept 20") gets its year from the import clock: the Berlin date of the
     import, the same answer the old page gave that day. Note the old quirk: the year group only matches `20xx`, so
     "20 september 1999" also takes an inferred year. Free-text dates are counted; the real snapshot has none.
   - **Naive timestamps are Europe/Berlin (G14)**, as in `convert.timestamp` and the old `parse_when`. A wall time in
     the spring-forward gap follows Python's `fold=0`, exactly like the old code (goldens include it).
3. **`created_at` (G4)**, revised per H-097: a valid `created` (a day is midnight Berlin, like people), else a valid
   `retrieved_at` (naive = Berlin, `convert.timestamp`), else the import time. Each source is counted
   (`created_at_from`), so an inferred timestamp is distinguishable from a stated creation date.
4. **Text (G5).**
   - `city`, `country` and `url` read blank and the placeholders `unknown` / `n/a` / `none` as `NULL` (the
     importer's `text_or_none` rule).
   - `name` and `status` read only blank as `NULL`. A blank or non-text `name` falls back to the id, because the column
     is `not null`; this is counted (`name_from_id`).
   - Values are stripped.
   - A non-text value in a promoted text field is `NULL` in its column and stays in `attrs`, as for people.
5. **`lat` / `lng` (G6).**
   - A value is kept when it is a finite number within ±90 / ±180, or a plain decimal string of one.
   - Bools, NaN / infinity, out-of-range numbers, `"49,5"`, `"8_4"` and other types are `NULL`. A rejected value stays
     in `attrs` (and `legacy`).
   - Each axis is judged on its own; a one-sided pair is possible but the report would show it. Today there is none.
6. **Status (G7)** has no check constraint: unknown values are kept and counted.
7. **Events write model (G8)** (stated in `events/__init__.py` and `DATA_MODEL.md`):
   - `legacy` is the import and is never changed;
   - `attrs.record` is reserved for the whole current record in the old `events.json` shape once the new app writes
     the event or lead, as for `people` and `conviction_entries`. An imported `record` key is omitted from `attrs`; it
     stays in `legacy`;
   - the columns mirror the current record through `events.columns`.
8. **Leads (G9).**
   - `lead_date` is the old `parse_when` of `date`, and `date_raw` is the value as stated.
   - `detected_on` is a strict `YYYY-MM-DD`; anything else is `NULL` and kept in `attrs`.
   - `created_at` is `detected_on` at midnight Berlin, else the import time.
   - `decision` is `new | dismissed | converted`: the old page dismisses and converts.
   - The old list order (newest first, capped at 250) is not a column. It is the archived `events.json` order in
     `legacy_documents`, as for people.
9. **Scout 00 event reports (G10)** stay in `scout_intake.json#rest`, where the old Scout 00 view reads them. In the
   documents copy, `event_id` is the plain event id: everything from the first `|` is removed, exactly what the old
   reader `event_scout.by_event` did (`split("|")[0]`). `legacy_documents` stays byte-exact.
10. **Recorded, not changed:**
    - **G11:** event ↔ person links stay in `attrs.people_met` (and the people records), with no link table until the
      Events / Network ports define one.
    - **G12:** `.watch/` page baselines stay archive-only (`ARCHIVE_ONLY_PREFIXES`); the scan port decides.
    - **G14:** naive timestamps are read as Europe/Berlin.
    - **G15:** ids are not format-validated.

## Verification
- **Unit tests** (`tests/ops/test_legacy_import.py`, 40 new incl. parametrized):
  - events and leads without an id, or not records, are skipped and reported, with no blocker;
  - repeated event and lead ids block with both names, yield one row each, and `apply` refuses before connecting;
  - nine date cases checked against both the stated columns and the span: date-only, multi-day, timed with seconds,
    blank end, `Z` across midnight, `DD.MM.YYYY HH:MM`, an end before the start, an unparseable start with a stated
    end, and a `24:00` end;
  - the date counts and reasons, unparseable values in `attrs`, a free-text date dated by the import clock (2027);
  - `end_before_start`; `created_at` from `created` with 2 fallbacks;
  - blank / placeholder text gives `NULL`, a non-text city stays in `attrs`, unknown statuses are kept and counted,
    and `name_from_id`;
  - nine coordinate cases: floats, ints, strings, bools, out of range, NaN / `1e400`, `"49,5"`, other types, absent;
  - an imported `record` field never reaches `attrs` (events and leads);
  - lead columns, `lead_date` / `date_raw`, `detected_on`, `created_at`, open and decision counts, and no
    `events.json#rest` document;
  - an unknown, missing or empty lead decision blocks;
  - the Scout 00 suffix is stripped in documents only and counted, with the archive untouched;
  - ten `stated` cases, none of which raises.
- **Goldens** (`tests/ops/test_events_when_golden.py`, 8):
  - provenance: the clean old revision, ZoneInfo Berlin;
  - the corpus is unchanged;
  - `parse_when`, `extract_date` and `event_span` match at both clocks: **0 differences** over 100 values × 2 clocks
    × 2 functions and 30 spans × 2 clocks;
  - the importer's `span_of(stated(...))` equals the old `event_span` wherever the old code did not raise;
  - a rule spot-check, and the clock independence.
  - The corpus covers:
    - ISO dates (leap days, invalid months / days, year 1 / 9999, prefixes);
    - naive datetimes (seconds, fractions, `24:00`, `25:61`, the spring-forward gap, the autumn fold);
    - offsets (`Z`, `±HH:MM`, `±HHMM`, `+14:00`, `+99:00`, overflow at both ends, across midnight and both DST
      switches);
    - `DD.MM.YY(YY)` with and without time;
    - English / German free text, with and without a year, month rollover, "Mayday", "1999";
    - full-width digits, garbage, blanks, and nine non-text types.
- **Real snapshot parity** (`python -m projectzero.ops.parity_events real`, clock 2026-11-11): **0 differences** over
  1,106 values (543 starts, 543 ends, 20 lead dates) and 543 spans; the importer's span differs from the old
  `event_span` for **0** of 543 events.
- **Schema tests** (PGlite, 3 new):
  - stated dates and times round-trip, and `24:00`, a time without a date, a start date without a span and a
    zero-length span are refused;
  - `event_leads` has the default `new`, accepts `dismissed` / `converted` and refuses others, has the touch
    trigger, has RLS on, and has no API grants;
  - 0007 refuses to run over an existing event, and nothing is half-applied (no column, no `event_leads`).
- **Hosted** (`tests/hosted/test_migration_0007_hosted.py`, 2 new), the 0003 two-session test:
  - the writer holds an uncommitted insert, the migration is observed waiting on the lock (`wait_event_type = Lock`),
    the writer commits, and the migration aborts with "events is not empty": no column added, no `event_leads`, the row
    untouched;
  - on an empty table the migration applies.
- **Real snapshot, before → after** (`python -m projectzero.ops.legacy plan`, **0 blockers** both times):

  | | before | after |
  |---|---|---|
  | events in / rows | 543 / 543 (an id-less record would crash) | 543 / 543 (0 skipped, 0 duplicate ids) |
  | starts: date-only / timed / unparseable | 27 / 516 / 0 (one column, time not distinguishable) | **27 / 516 / 0** (0 free text) |
  | ends: date-only / timed / unparseable / absent | — / 516 / 0 / 27 → `ends_at` NULL | **0 / 516 / 0 / 27** |
  | `starts_at` | 543 set | 543 set, **all 543 identical** to before (no seconds on the snapshot) |
  | `ends_at` | 516 set, 27 NULL | **543 set**: 516 identical, 27 = end of the start day (exclusive) |
  | ends before start | not checked | 0 |
  | `created_at` from `created` | 0 (all import time) | **10** (533 fallbacks to import time) |
  | `''` in city / country | 17 / 17 | **0 / 0** (`NULL`) |
  | lat / lng kept | 11 / 11 (bools would pass) | 11 / 11 (0 from text, 0 dropped) |
  | status | not reported | `new` 540, `skipped` 3 |
  | leads | 20 in `events.json#rest` | **20 `event_leads` rows, 20 open** (18 dated, 2 undated; 0 blocked) |
  | Scout 00 `event_id` with `\|merged:` | 9 in documents | **0** (9 stripped; 10 plain ids, 21 empty) |
  | `documents` rows | 77 | 76 (`events.json#rest` gone) |

- **Rehearsal** (`python -m projectzero.ops.legacy rehearse`, scratch schema, every migration including 0007):
  - **passed**: all table counts match after the second apply (`events` 543, `event_leads` 20, `documents` 77 with
    the marker, `legacy_documents` 2,200);
  - the real rows satisfy every new check in Postgres;
  - the archive restores byte-exact, all 1,479 aliases resolve, and the second apply is a no-op;
  - both conflict re-imports abort, and every scratch schema is dropped.
- **Mutations** (each run against its tests, then restored), **12/12 killed**:
  - an out-of-range time accepted (the plan raises in `event_span`);
  - a date-only end made inclusive;
  - free-text rollover one month late (`>`);
  - the machine clock instead of the parameter;
  - a repeated id not blocked;
  - bools accepted as coordinates;
  - `record` not reserved;
  - placeholders kept in `city`;
  - `created_at` always the import time;
  - the Scout 00 suffix kept;
  - SQL: 0007 without the emptiness check (PGlite fails);
  - SQL: the lock moved after the emptiness check (the hosted two-session test fails: the migration applies over the
    committed row). The test writer's row satisfies every new check, so only the locked emptiness check can refuse.
- **Results:** gate ALL CHECKS PASSED (pytest 1,136, ECMA 4, PGlite 31, vitest 146). Hosted (`db.ps1 itest`): 74 of
  75 passed, the 2 new 0007 tests included. The one failure was `test_network_hosted.py::test_an_attrs_record_edit_…`
  with `psycopg ConnectionTimeout` (the pooler, not an assertion); a rerun of that file passed 15/15.
  `db.ps1 cleanup` found no leftover scratch schema.

## Questions for Codex
1. **`created_at` fallback.** 533 of 543 events have no `created`, but all 533 carry `retrieved_at`
   (`YYYY-MM-DD HH:MM`, when the auto-promotion fetched them). As decided, they fall back to the import time. Would you
   rather use `retrieved_at` (naive, so Berlin) as the second source before the import time?
2. **Dates kept as stated.** `end_date` keeps an end that is earlier than the start, with no check, while `ends_at`
   follows the old `event_span`. An out-of-range time (`24:00`) makes the whole value unparseable rather than keeping
   its date. Agree with both?
3. **A free-text date without a year** is resolved once, at the import clock. The old page re-resolved it on every
   view, so after a year it would have rolled forward. The snapshot has none, and the raw string stays in `legacy` (and
   in `date_raw` for a lead). Acceptable?
4. **Leads:** is blocking on an unknown `decision` (rather than keeping it in `attrs` with `new`) the right default?

---

## Codex review

**CHANGES REQUESTED.** I reproduced two cases directly through `event_columns` where planning and migration 0007 disagree.

- With start `2026-03-29T02:45` and end `2026-03-29T03:15`, Berlin's spring clock change produces 01:45 UTC to 01:15 UTC. The wall-clock comparison accepts this span, but Postgres rejects it under `events_span_is_forward`.
- With start `9999-12-31` and no end, computing the exclusive next midnight raises `OverflowError` and aborts planning.

Keep the legacy oracle intact. At the import boundary, check the derived instants in UTC and catch exclusive-end overflow. Report either case as a blocker naming the event and its stated dates. Add plan-level regressions showing the planner finishes and prevents apply for both.

On the four questions: (1) Prefer valid `created`, then valid Berlin-local `retrieved_at`, then import time. Count each source so an inferred timestamp is distinguishable from a stated creation date. (2) Keep an earlier stated end for inspection and derive the legacy span, subject to the UTC check above. Treat `24:00` as unparseable and preserve its raw value. (3) Accept resolving a yearless date once using the recorded import clock. (4) Keep unknown lead decisions as blockers so a previously closed lead cannot silently reappear as new.

### Claude — revision 2 (2026-11-11 20:19 CET)

All of H-097 is implemented. `events/when.py` (the oracle) is unchanged.

**Spans the database would refuse are blockers**
- `events.columns.checked_span` wraps `span_of`:
  - it compares the derived instants **in UTC** (two Berlin datetimes compare by wall clock in Python, which is why
    the gap case passed);
  - it catches `OverflowError` on the exclusive end.
- In either case the event is reported as a blocker that names its id and name, its stated start and end, and the
  reason, for example: "states start '2026-03-29T02:45' and end '2026-03-29T03:15': the derived span does not run
  forward in UTC". The row is not written, and the report lists it in `span_blocked`.
- Plan-level regressions cover the gap case, `9999-12-31` with no end, and `9999-12-31T10:00` with a blank end. In
  each, the planner finishes, an ordinary event beside the blocked one is planned, and `apply_plan` refuses before any
  connection.
- Two cases are checked as not blocked: the autumn repeated hour, and a span crossing the spring change.
- **Mutation checks** (2 of 2 caught): a wall-clock comparison fails the gap case, and removing the overflow guard
  fails both 9999 cases.

**Your answers, applied**
1. `created_at` is a valid `created`, then a valid `retrieved_at` (naive = Berlin, via `convert.timestamp`), then the
   import time. The report counts each source (`created_at_from`). Tests cover precedence, naive versus `Z`, and an
   invalid `retrieved_at`.
2. An earlier stated end is kept and the legacy span derived, subject to the UTC check. `24:00` is unparseable, with
   its raw value kept in `attrs` (new test for both start and end).
3. A year-less date is resolved once at the import clock (unchanged).
4. An unknown lead decision blocks (unchanged).

**Real snapshot** (the old app has been writing, so there are now 674 events, up from 543):
- `span_blocked` [] and no blockers;
- `created_at_from`: created 10, retrieved_at 664, import_time 0.

**Rehearsal** passed: every count matches (events 674, leads 22), the second apply is a no-op, both conflict checks
refuse, and the scratch schema is dropped. The first attempt exited with an error that was not captured, most
likely the known pooler flakiness. `db.ps1 cleanup` found no leftover schema, and the rerun passed.

**Results:** gate ALL CHECKS PASSED (pytest 1,141, PGlite 31, vitest 146). Hosted full run 58 passed; 18 in the Network, lock-order and intake modules failed or errored (not captured, 13.5 min run, consistent with the pooler timeouts seen before; none touch events). Those three modules rerun in isolation: **37 of 37 passed**. Migration 0007 hosted tests passed in the full run.

### Codex verdict on revision 2

**APPROVE.** I reran six focused importer tests. The Berlin spring gap and both maximum-date cases now produce event-specific blockers. Planning continues for the neighboring valid event, and apply refuses the blocked plan before opening a database connection. Valid clock-change spans and the creation timestamp fallback also passed. Claude reports the 674-event rehearsal passed. The full hosted run had 18 failures or errors outside Events, and the affected modules passed on their isolated rerun. The original cause remains unconfirmed.

## Grok notes
