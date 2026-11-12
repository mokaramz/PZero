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


### Claude — implementation (2026-11-12 14:01 CET)

Ready for **code review**. The approved plan, with revision 2, is implemented. There is no migration: the Map only
reads.

**The pure domain** (`map/`: `catalog`, `inputs_model`, `network`, `intel`, `pins`)
- **The catalog.** Cut by script (`scripts/gen_map_catalog.py`) from exact top-level line ranges, including the texts
  inside functions: the legend, the Where-to-go notes, `bring_back` and the plan note. Each cut is checked to compile
  to the old syntax tree. `GAZETTEER`, `ORGS` and `CITIES` are reused from Events and Ecosystems.
- **The logic.** `intel` is the old `services/geo_intel.py` line for line: `_fold`, `_cities`, `_Placer`, `_collect`,
  the analysis, `build`, `where_to_go`, `view`, `detail`, `sourcing_day` and `search`. `pins` is the old `home.py`
  pins with `geocode_location` and `enrich_signals_with_geo`.
  - They are pure functions over ONE frozen `MapInputs`. Each field names the old call it replaces, with its shape
    and ORDER.
  - The clock is the Berlin request day. `built_at` is the Berlin wall time and `build_s` is 0. There is no cache (g).
- **(a)** The pins geocode shallow copies, so the stored records are never touched.
- **(c)** The pins answer gains `new_signals`.
- **(f)** `network.check_candidates` is the one statement of the rules in revision 2. The intelligence and the city
  detail use only the usable candidates. When records are left out, their `note` gains the old `compat._skip`
  sentence ("Source network: N record(s) could not be interpreted — skipped safely (…)").
- **Old quirks kept (e).** The person pins carry no `city`. The intelligence links a Conviction company by name. The
  pins' institutions are the 24 static ones.

**The database side** (`map/inputs.py`, `api/routers/map.py`)
- **One adapter.** `load(conn, schema, now, for_pins=False)` reads everything in one read-only transaction.
  - It goes through the new `EcosystemsStore.snapshot()`, so the coverage inputs (adoptions included), the Events
    listing (with its pins), the stored registry and the candidate rows are loaded once and shared.
  - The current triage proposals are re-keyed by the inbox records' ids.
  - The byte-exact archives are read in their key order (b): `scout_intake.json`, `news/events.json`,
    `sources/network.json` and `watch/triggers.jsonl`.
  - Everything then goes through the same `inputs_from_docs` the goldens use, with the coverage computed once
    (`coverage_of`).
  - `for_pins` (the pins) skips the coverage, the proposals and the archives.
  - `config.json` is read archive-first, Conviction's rule, so `home_base` keeps the old key order. JSONB had
    reordered it; the real parity found this.
- **(d) Scout links.** A Scout 00 card links to `/scout-intake?item=<id>` (`MapInputs.scout_links`; the goldens keep
  the old bare link). The page opens it in Deal Flow through the existing old-id redirect.
- **(i), new, under the standing instruction.** The Deal Flow layer is the old inbox plus what intake added since.
  Candidates imported only from the retired Scout views (`origins` ⊆ {`legacy_scout00`, `legacy_native`}) are left
  out.
  - The old Map never read native-scout items.
  - Scout 00 items are already the archived Scout layer, so counting them twice would raise `new_signals` and the
    unplaced counts and could change states.
  - The real parity found this.
- **The routes.** `GET /api/map/pins`, `/intel`, `/ecosystem?city=` (404 `{ok: false, error}`) and `/search?q=`
  (`{results}`), and `POST /api/map/sourcing_day` (400 for an unknown city, a bad date or a non-object body).
  Nothing is stored.
- **The import blocker (f).** `RecordsMapper.source_network` reports each `check_candidates` problem as a plan
  blocker.
- **Speed.** The first build took about 12 s per request.
  - Coverage was computed twice, and `_fold` ran 828,000 times per request.
  - The coverage fold and its per-name patterns are now cached (`ecosystems.coverage._fold_text` / `_word`). They are
    pure, with unchanged results: the Ecosystems goldens and parity still match. This also speeds up the Ecosystems
    page.
  - The loads are now shared.
  - Computing now takes about 1 s. The rest is the database transfer of the candidate and event rows over the
    pooler, which the Deal Flow and Ecosystems pages already pay. So decision (g), no cache, stands.

**The page** (`frontend/src/features/map/`)
- A port with the same text, test ids and aria labels:
  - the four modes and `?event=`;
  - the MapLibre canvas, loaded lazily with its worker, with clustering, the 9-second plain fallback and the "could
    not load" text;
  - the layers, filters and results;
  - the strip cards, the detail panel, the ecosystem panel and the planner.
- **(b)** The snapshot note.
- **(c)** The Deal Flow card reads `pins.new_signals`.
- **(d)** Links:
  - `/news…` is plain text with "(News arrives with the News & Learning port)";
  - `/scout-intake?item=` opens Deal Flow;
  - a bare `/scout-intake` is text with the merged-view reason.
- **(g)** The plan's default date is the Berlin day + 7, unit-tested around midnight, the summer-time change and the
  year end.
- **One change.** An unknown `?mode=` opens Opportunity. The old page showed no section.

**Tests**
- **Old-code goldens** (`oracle_map.json`). Seven synthetic data folders of invented names (`munich`, `blind`,
  `noisy`, `watchers`, `chain`, `broken`, `empty`) rebuild the old `test_geo_intel` acceptance 28–31.
  - They cover every order-sensitive point: the gazetteer order, the news and network key order, the collection order
    behind search `results[0]`, and the `Counter` ties.
  - They cover tolerance, and a placeable record without coordinates.
  - They compare the intelligence, every ecosystem plus unknown and folded names, the searches, a plan per ecosystem
    with every refusal, and the pins.

  0 differences, value by value and as serialized text. The inputs are checked unchanged.
- **Real snapshot** (`parity_map real`, through the API routes over an imported scratch schema, against the old routes
  over a byte-exact copy):
  - the intelligence (63 ecosystems);
  - all 68 ecosystem details;
  - 11 searches;
  - 69 plans and refusals;
  - the pins, with `new_signals` compared against the old Home count.

  0 differences (after (i) and the `config.json` rule, both found here). The declared exception is the Scout link (d). The stored Conviction records are checked unchanged.
- **Hosted** (`test_map_hosted.py`, 5):
  - **(a)** A placeable Conviction record with no coordinates keeps its whole row (every column), and every event
    table is unchanged, through all five endpoints. Its pin still has coordinates.
  - **(b)** The archived News and network orders (long keys first) decide `detail.news` and `source_candidates`.
  - A missing News or network archive empties only its layer; the companies and institutions are unchanged.
  - **(f)** An existing import with a malformed network archive, written past the importer:
    - the city detail answers 200;
    - the usable candidates are kept in order;
    - the note names the dropped one;
    - the companies, people, events, news, institutions and reasons equal the valid answer;
    - the intelligence, search and plan answer 200.
  - The old refusals (404 and the 400s).
- **Unit.** `tests/map` (36): the goldens, literal provenance (the port carries only the old texts plus the declared
  ones), the network rules, the origin rule (i) and convergence (acceptance 32). The preview tests cover the network
  blocker (7).
- **Browser:**
  - **The page tests** (MSW, 44): the filters, the deep link and its toast, search and its fallback, the panels, the
    planner (exactly one POST, nothing invalidated), Where to go, the gaps, and the intelligence-failure text.
  - **`map.spec.ts` on the preview** (4): Opportunity → Why here? → a plan with exactly one POST; Explore and the
    search; the `?event=` deep link; no overflow at 1366, 150 % and 1920. The OpenFreeMap requests are blocked, so the
    run never touches the internet.
  - **The old-vs-new capture** (both apps with tiles blocked) in Opportunity and Explore. At 1366 and 1920, light and dark, the layout matches. Opportunity adds only the snapshot note (b). Explore's extra result rows, and the event and Zürich counts, are records earlier browser runs added to the preview. The real parity on a fresh import is the authority there.
- **Gate** passes (backend 1,473, frontend 404). The Map and Ecosystems hosted files pass (10). `parity_ecosystems real` still shows 0 differences after the fold cache.
- **Note.** The pure domain and the page were built by two subagents against the plan; I verified both. I wrote the
  adapter, the routes, the importer blocker, the Scout links, rule (i), the speed fixes, the real parity and the
  hosted and browser tests.

## Codex implementation verdict

**REQUEST CHANGES (H-200).** I reproduced silent loss of an imported source candidate. Given the same BOM-prefixed UTF-8 archive containing one valid DISCOVERED candidate, the importer’s parser and `check_candidates` returned one candidate and zero problems. The Map adapter’s `_parse` and the same check returned zero candidates and zero problems. The adapter decodes plain UTF-8, catches the JSON parse error and treats the archive as absent. The legacy tolerant reader also fell back on this encoding, but the new importer accepts it and the approved plan promises to show usable imported candidates.

Use the importer’s optional-BOM decoding for archived Map JSON, retaining key order and the existing fallback for genuinely unreadable input. Apply the same decoding to the archived watch JSONL text so a BOM cannot discard its first record. Add a regression through the adapter or routes proving the imported candidate survives in city detail and a first-line watch trigger survives decoding.

All 36 local Map domain tests passed. The hosted, real-snapshot and browser results are Claude’s reported runs.


### Claude — implementation revision 2 (2026-11-12 14:10 CET)

All of H-201 is taken. The Map decodes its archives exactly as the importer does.
- **`map/inputs.py`.** `_parse` (the Scout Intake, News and source-network JSON archives) and `_text` (the watch
  JSONL) decode `utf-8-sig`, so an optional leading BOM is skipped.
  - The key order is kept.
  - A genuinely unreadable archive still falls back as before: `None`, then each consumer's old default.
  - The archived bytes are never changed.
- **The regression (hosted, through the route).** Two archives are written with a leading BOM:
  `sources/network.json` (two valid candidates) and `watch/triggers.jsonl`, whose FIRST record is a trigger named
  after the fixture's Munich company. Then, in the Munich detail:
  - `source_candidates` holds both candidates, in archive order;
  - the note reports no dropped record;
  - the company is marked `watch`, so the first JSONL line survived decoding.

  With the old plain `utf-8` decoding, both fail: the candidates vanish and the trigger is lost.
- **Results.** The Map hosted file passes (6). The gate passes (backend 1,473, frontend 404).

## Codex implementation revision 2 verdict

**APPROVE (H-202).** I reran the H-201 case with two candidates. Both survived in archive order with no reported drops. The first BOM-prefixed watch record also survived, and invalid UTF-8 still produced the expected empty fallback. All 36 local Map domain tests passed. I inspected the city-detail route regression, which checks both candidate names and the company's watch flag. Claude reports all six hosted tests passed. This resolves H-201 and closes review 025.

## Grok notes
