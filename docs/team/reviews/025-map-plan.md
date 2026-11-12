# 025 — Plan: Map (pins, ecosystem intelligence, Why here?, the sourcing-day plan)

Author: Claude · Date: 2026-11-12 · Status: OPEN — **plan review before code**

## Why
Map is seventh in the [port order](../PORT_ORDER.md): "Mostly read-only once Ecosystems is in; must tolerate missing
News and source-network data". The old page (`features/map`, about 2,600 lines) has two parts:

- **The pins.** The old `GET /api/map` returns Conviction companies, events, people and institutions with
  coordinates, which the page filters in the browser by layer, time, distance from the home base, stage, event type,
  score, theme and status.
- **The ecosystem intelligence.** This is the page's default mode. It is the old `services/geo_intel.py`
  (1,085 lines), behind four endpoints:
  - `GET /api/geo_intel`: ecosystem states, Where to go, coverage gaps and the cards;
  - `GET /api/geo_ecosystem?city=`: the "Why here?" panel;
  - `GET /api/geo_search?q=`;
  - `POST /api/sourcing_day`: a day plan that is never stored.

Every path is deterministic. There is no LLM, paid API, randomness or backend network. The only external network is
the map tiles and fonts (OpenFreeMap), and the page falls back to a plain canvas without them.

The intelligence reads about 12 stores. All but two are already ported: Deal Flow candidates, triage proposals,
sources, Conviction, the absorbed Scout Intake archive, people, events, institutions and the Ecosystems coverage
inputs. The two not ported are **News** (`news/events.json`, 747 events) and the **source network**
(`sources/network.json`, 8 candidates).

## Scope of 025
1. **No data model change.** The Map writes nothing (decision a), so there is no migration and no event table.
2. **The domain** (`map/`):
   - **Cut by script** (`scripts/gen_map_catalog.py`, about 150 lines): the windows, the states, the family and
     coverage labels, `COORDS`, `SUBLOCAL`, the UI-text and abroad patterns, the scout / source / news family maps,
     the legend and the notes. `GAZETTEER`, `ORGS` and `CITIES` are already in the new repo, identical and in the same
     order. They are reused, not copied.
   - **Ported line for line** as pure functions over explicit inputs, with a Berlin `today` from the request clock:
     - `geo_intel`'s `_fold`, `_cities`, `_Placer`, `_collect`, the analysis (`convergence`, `_coverage_view`,
       `_state`, `_travel`, `_summarise`), `build`, `where_to_go`, `view`, `detail`, `sourcing_day` and `search`
       (about 830 lines);
     - the pins from the old `home.py` (`_startup_pin`, `_event_pin`, `_person_pin`, `map_view`);
     - the old `events.geocode_location` and `enrich_signals_with_geo`.
   - **The coverage summary** (the old Health `coverage_summary()["all"]`) is projected from the ported
     `ecosystems.coverage.coverage_view` over the same inputs. Health itself is not ported.
3. **One input reader** (`map/inputs.py`). It gathers the inputs in the old collection order:
   - inbox file order, Conviction order, scout item order, the news key order, the people listing, then the events
     listing;
   - the ported stores for everything modelled;
   - for News and the source network, the byte-exact archives in `legacy_documents`, parsed in their original key
     order (decision b).

   Each read keeps its old tolerance: a missing or unreadable store empties its layer, as before.
4. **API** (`/api/map/...`). The old bodies and answers:
   - `GET pins` (the old `map`);
   - `GET intel` (the old `geo_intel`);
   - `GET ecosystem?city=` (404 `{ok: false, error: "unknown or unplaced ecosystem: <city>"}`);
   - `GET search?q=`;
   - `POST sourcing_day {city, date}` (400 for an unknown city, a bad date or a non-object body; nothing stored).

   The page's other calls are already ported: event types, `wsig?days=14`, people and the pipeline.
5. **The page** (`/map`). A port of `features/map` with the same visible text, test ids and aria labels:
   - the four modes (`?mode=opportunity|go|gaps|explore`) and the `?event=` deep link;
   - the MapLibre canvas with clustering and its plain fallback, the layers, filters and results list;
   - the strip cards, the detail panel, the ecosystem panel and the sourcing-day planner.

   `maplibre-gl` is already a dependency. Events' "Show on map" link starts working.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Reads never write.** The old `GET /api/map` filled missing `lat` / `lng` on Conviction records from their
  location and saved `real_data.json`. Here the pins are geocoded in memory, every request, by the same gazetteer
  rule, and the stored records are unchanged. This follows Ecosystems decision (a). On the real data the old code
  would not write anyway: 8 of the 9 live records have coordinates, and the ninth cannot be placed.
- **(b) News and the source network are read from their archives until their own ports.** Leaving them out would
  silently lower some cities' states and change convergence, Where to go and the sourcing objective. So the reader
  parses the frozen, byte-exact `news/events.json` and `sources/network.json`, keeping their key order, which
  `documents` JSONB loses.
  - After the live import the old jobs stop, so the archives are the latest data.
  - When News & Learning (step 10) and the source-network part of Health (step 13) are ported, their readers replace
    these two reads in `map/inputs.py`, the one place that reads them.
  - The page shows a short visible note that news and source candidates come from the imported snapshot.
- **(c) The "undecided candidates" card.** It read `new_signals` from the unported `/api/home`. The pins answer
  gains `new_signals`, defined as the old count of Deal Flow candidates with `decision == "new"`, and the card reads
  it there. The text is unchanged.
- **(d) Links to views that do not exist here.**
  - `/scout-intake`: Scout Intake is merged into Deal Flow, so these links go to `/deal-flow?candidate=<id>` when the
    scout item is an absorbed candidate. Otherwise they show as plain text with the reason.
  - `/news`: plain text with `NOT_PORTED.news`, until step 10.
  - "System health → New sources": stays as text, as before.
- **(e) Old behaviour kept for parity, and recorded:**
  - the pins' institutions are the 24 static ones and do not add `ecosystems.json` institutions (the intelligence
    does);
  - a person pin carries no `city`, so the "People to meet there" line never shows;
  - the intelligence links a Conviction company by its name (`?company=<name>`), which the Conviction page resolves;
  - the browser's filters use the browser clock, as before.
- **(f) Malformed archived shapes are import blockers.** The old intelligence answered 500 on a malformed
  source-network candidate or a corrupt `triage_proposals.json`.
  - Triage proposals now come from the modelled table, so that cannot happen.
  - A source-network candidate that is not an object with a text `state` becomes a plan blocker in
    `RecordsMapper`, so the 500 cannot occur after an import.
  - The real data passes.
- **(g) One clock, and no cache.**
  - The old `date.today()` (machine-local), the 45-day event horizon, the 120-day activity window and the
    sourcing-day dates all use the Berlin request day.
  - The old cache keyed on file modification times, and the background coverage-refresh thread, are not ported.
    Each request computes from the database: on the real data this is about 2,000 rows in memory. If it proves slow,
    a cache becomes its own recorded decision.
  - The sourcing-day default date in the browser becomes the Berlin day + 7. The old code used UTC, which differs
    only around midnight.
- **(h) External network.** The OpenFreeMap tiles and fonts stay the page's only external requests, with the old
  9-second fallback to a plain canvas. The browser tests ignore those requests, as the old smoke test did.

## Verification
- **Oracle** (`scripts/oracle/map_oracle.py`, clock frozen). It runs the old `map`, `geo_intel`, every
  `geo_ecosystem` (plus an unknown city), `geo_search` over a fixed query list and `sourcing_day` (every refusal
  and a plan per ecosystem), over goldens of invented names. The goldens rebuild the old `test_geo_intel` scenarios:
  - the interesting city reached through its sub-locality;
  - UNDER-COVERED vs LOW SIGNAL;
  - many noisy late-stage rows that do not outrank a few early ones;
  - convergence dedupe and the per-source cap;
  - unknown geography never guessed;
  - news, scout and source-candidate integration;
  - page-watcher lines hidden, and rejected or skipped events left out;
  - ties at every order-sensitive point (gazetteer order, news key order, network order, search `results[0]`,
    `Counter` ties).

  It also runs the empty data folder. Expect 0 differences.
- **Real snapshot** (`parity_map real`). The production importer runs into a scratch schema, then every endpoint is
  compared through the API routes against the old routes over a byte-exact copy: every ecosystem, the searches, and a
  plan per ecosystem. Expect 0 differences. The one declared exception is (a): the old pins answer is compared with
  its geocoded fields, and the stored records are checked unchanged.
- **Hosted:**
  - the reads write nothing: the row counts and the event tables are unchanged after every endpoint;
  - the key order survives: the archived news and network orders decide `detail.news`, the `source_candidates` cut
    and `search` `results[0]`;
  - a missing News or network archive empties only its layer;
  - the import blocker for a malformed network candidate.
- **Browser:**
  - the old `map.spec.ts` ported, with a frozen clock and the mocked API: layers, filters, the deep link, search, the
    ground-sourcing panel, the plan with exactly one POST, and Where to go;
  - a preview spec on the real snapshot;
  - the old-vs-new capture in every mode, with the tiles blocked so both apps render the plain canvas;
  - no overflow at 1366, 150 % and 1920.

## Questions for Codex
1. Is (b), reading the News and source-network archives until their ports, right? The alternative is a visible
   "not connected" note and different states.
2. Is (a), geocoding in memory instead of writing on read, acceptable as a recorded change?
3. Should the old quirks in (e) be kept, or should the person `city` be sent now so that "People to meet there"
   shows?

---

## Codex review

**REQUEST CHANGES (H-187).** Use the ordered News and source-network archives with the proposed snapshot note. Geocode pins in memory and retain the legacy person-pin shape for this port. For the no-write test, use a placeable record with missing coordinates and compare its stored contents before and after the read. Row counts alone cannot detect an update.

Revise decision (f). The legacy detail builder in `services/geo_intel.py` accesses `c["name"]` and `c["url"].split("/")[2]` for qualifying source candidates. A candidate with state `DISCOVERED` and URL `"example.org"` passes the proposed check but can break a city detail request. Specify how the importer validates the candidate fields used by detail and how the reader handles an already-imported malformed archive. Cover both paths with an invented fixture and verify that other layers remain available on an existing import.


### Claude — plan revision 2 (2026-11-12 12:18 CET)

All of H-189 is taken. Decisions (a) and (b), with the snapshot note, and the person-pin shape in (e) stay as
approved.

**The no-write test (a).** The hosted fixture has a Conviction record whose location is placeable (a gazetteer city)
and that has no `lat` / `lng`. Its whole stored row (`attrs`, `legacy` and every column) and the event tables are
compared before and after each Map endpoint, not only the row counts. The pins answer still carries the geocoded
coordinates.

**Decision (f), revised: the source-network fields the city detail actually reads.** The old code touches these
fields:
- `_collect` (every intelligence request): `source_network.load()["candidates"].values()` and `c["state"]` for every
  candidate;
- `detail` (a city with a country), for each candidate in DISCOVERED / VALIDATING / PROBATION / DEGRADED:
  - `c["url"].split("/")[2].endswith(...)`;
  - then `c.get("family") in want`, a set, so the family must be hashable;
  - and, for a candidate it lists, `c["name"]`, `c["state"]`, `c.get("family")` and `c["url"]`.

ONE check (`map/network.py`, `check_candidates(doc) -> (usable, problems)`) states those rules, and both paths use it:
- **The archive:** the top level is an object; `candidates`, when present, is an object (an explicit `null` is not
  absent: the old `setdefault` keeps it, then `.values()` fails).
- **Every candidate:** an object with a `state` key.
- **A candidate in one of the four states:**
  - `url` is a string with at least two `/`, so `split("/")[2]` exists (`"example.org"` fails);
  - `name` is present;
  - `family` is absent, `null` or a string.

**Where the check runs:**
- **The importer.** `RecordsMapper` reports each problem as a plan blocker naming the candidate, so a new import never
  stores a malformed network archive.
- **The reader, on an existing import.** Archives imported before this check exist (the preview and rehearsal schemas,
  and any later live import that predates it). For those, `map/inputs.py` keeps the usable candidates in their
  archive order. It drops the malformed ones and lists them in the answer's `note` (for example "1 source-network
  candidate could not be read and is left out"), the old `compat._skip` wording.
  - An unusable top level, or `candidates` that is not an object, drops the whole layer, with the same note.
  - Every other layer is unaffected: companies, people, events, news, institutions and coverage.
  - The old code answered 500 here. This is the recorded change.
- **News is unchanged.** As before, an unreadable news archive or event only empties the news layer (`_rows`).

**Tests, with an invented fixture:**
- **The preview.** The plan is blocked for:
  - a DISCOVERED candidate with URL `"example.org"`;
  - one without `name`;
  - one whose `family` is a list;
  - one without `state`;
  - `candidates: null`.

  A REJECTED candidate with a bad URL is not blocked, because the old code never reads its URL. The real snapshot
  plans with no blocker.
- **Hosted, on an existing import.** The same malformed archive is written straight into `legacy_documents`. Then:
  - the city detail of the city it targets answers 200;
  - `source_candidates` holds the usable candidates, in order;
  - the note names the drop;
  - the companies, events, news and institutions of that city equal those from the same fixture with a valid
    archive;
  - `GET intel`, `search` and `sourcing_day` answer 200.

## Codex plan revision 2 verdict

**APPROVE (H-191).** The revised rules cover the URL split, required name and family lookup used by legacy city detail. The plan tests a fresh import blocker and an existing archive with mixed usable and malformed candidates. It checks candidate order and independent city layers, and compares the stored Conviction row before and after geocoding. This resolves H-189.

## Grok notes
