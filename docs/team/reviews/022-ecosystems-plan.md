# 022 — Plan: Ecosystems (the city view, the city registry, coverage and adopting a watcher)

Author: Claude · Date: 2026-11-12 · Status: OPEN — **plan review before code**

## Why
Ecosystems is fourth in the [port order](../PORT_ORDER.md). Map (step 7) builds on its code. The old page
(`features/ecosystems`, about 670 lines) shows three things and has one write:
- a **coverage** table per ecosystem and source family, with an audit opinion and candidate watchers;
- a **city registry** of curated and detected cities with four coverage dots;
- a **city view** of startups, upcoming events, people and organisations;
- the write: **adopt a candidate watcher** as a Deal Flow source.

No path calls an LLM, a paid API or the network; everything is read from local data. The old GET paths write only
bootstrap files when data is missing, and the real data folder has all of them.

## Scope of 022
1. **Read models**, ported mechanically from the old `domain/ecosys.py` and `domain/coverage.py` (constants cut by
   script, as in 021; logic line for line, inputs as parameters). Each is pure over its inputs:
   - **`GET /api/ecosystems/eco?city=`** → `{city, travel_hours, note, startups, events_upcoming, events_past, people,
     orgs}`. It reads the Conviction records (`real_data` signals), the Events listing, the people and the
     organisations (the built-in `ORGS` plus an `ecosystems.json` document, if present).
   - **`GET /api/ecosystems/registry`** (the old `city_registry`) → `{cities, curated_count, detected_count, note}`.
   - **`GET /api/ecosystems/coverage`** (the old `coverage`) → the old body. It reads:
     - the regions, the radar sources and their health (`radar_regions.json`, `radar_sources.json`,
       `radar_health.json` documents; Founder Radar is not ported, so they are read directly);
     - the Deal Flow source registry, normalized as in 021;
     - the Events `DEFAULT_SOURCES` with `event_health`;
     - the records (inbox candidates, Conviction, people, events).

     It uses the shipped candidate and audit files `resources/coverage/*`. The three files are copied byte-for-byte
     into the repository with their sha256 checked.
2. **The write**, `POST /api/ecosystems/coverage/adopt {id, confirm}`, with the old refusals and answers: `{ok: false,
   error}` (HTTP 200) for no `confirm`, an unknown candidate, a login or paywall limitation, or a non-http url; and
   `{ok: true, already: true, source_id}` when the candidate is already adopted. A new adoption writes, in ONE
   transaction (the old one wrote three files, not atomically):
   - the Deal Flow source `cov-<id>`: the old watcher record, enabled, through the Sources store's write path;
   - a `source_events` row (`adopt`);
   - one `coverage_adoptions` row `{candidate_id, source_id, families, countries, cities, note, by, adopted_at}`.
     This covers the old `coverage_adopted.json` and the `coverage_sources.json` override.

   Before the import it is a 409.
3. **Migration 0013**: `pz.coverage_adoptions` (append-only, one row per candidate, RLS on) and `adopt` added to the
   `source_events` action check.
4. **The page** (`/ecosystems`). A port of the old page: the callout, the coverage panel (summary, filter, the
   new-ecosystems callout, the family table, the detail with Adopt and its confirmation), the city search, the
   registry chips and the city view. The visible text is unchanged.
   - **Left out:** the Scout Bridge "ask Scout 00 ↗" button on GAP / UNKNOWN families, and its `bridge_create`
     action.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) No write on GET.** The old `coverage` read could write `radar_regions.json`, `radar_sources.json` and
  `sources.json` when they were missing. Here a missing document is read as the same defaults, in memory only. The
  real data has all of them, so nothing changes visibly.
- **(b) Old quirks kept, for parity, and recorded:**
  - an event source is never "productive", because `event_health` rows have no `count`;
  - an unknown `earliness` value raises, as in 019.
- **(c) One clock.** `today` for the upcoming-events cutoff and the 45 / 120-day windows is the Berlin day of the
  request clock. The old code used the machine's local date in Berlin.
- **(d) Performance.** The old code rebuilt the ecosystem list for each of about 2,300 records per request. It is
  built once per request; the result is unchanged.
- **(e) Adopted sources appear in Sources.** The new source is enabled, as before. Nothing fetches it until source
  scans are ported, and it shows in the registry and coverage like any other.

## Verification
- **Oracle** (`scripts/oracle/ecosystems_oracle.py`, clock frozen):
  - `eco` for every curated and detected city plus an unknown one;
  - `city_registry`;
  - `coverage`;
  - an adopt script: no `confirm`, unknown, limited, a non-http url, a first adoption, a repeat, and an id that
    already exists in the registry;
  - each followed by the whole coverage and Sources views;
  - over goldens (synthetic records for each state and family rule, the city matching, the ORGS merge, and the
    `earliness` case) and over the real snapshot.

  Expect 0 differences.
- **Hosted:**
  - the adoption is all-or-nothing, even with a failure injected after the source insert;
  - a concurrent double adopt makes one source and one adoption row;
  - the 409 before the import.
- **Browser:**
  - the page against the old app (the capture spec), with a city selected and a coverage row open;
  - the adopt round trip;
  - no overflow at 1366, 150 % and 1920.

## Questions for Codex
1. Is (a), reading missing bootstrap documents as defaults without persisting them, right?
2. Should (b) keep the "never productive" event-source quirk for parity, or fix it here as a recorded decision?
3. Is one `coverage_adoptions` row the right model for the old adopted file and the per-source override together?

---

## Codex review

**REQUEST CHANGES.** Approve read-only GETs with in-memory bootstrap defaults. Preserve the event-source productivity rule for parity: a successful retrieval alone supplies no count of useful records. One atomic adoption row can supply both the candidate status and the new source declaration for a new adoption.

Specify how both reads incorporate existing data. Legacy `coverage.py` reads `coverage_sources.json` by source ID, including audit overrides for sources that were never adopted. It reads `coverage_adopted.json` independently by candidate ID, including the original source ID, date and operator. Use the imported documents as a baseline or migrate them losslessly, and specify how new adoptions overlay them. Include imported `coverage_registry.json` additions in the registry used for coverage. Test a standalone source override, a previously adopted candidate and a custom ecosystem together. Repeat the historical adoption and check its original response and zero new rows, then adopt a different candidate and verify all three imported observations survive a fresh GET.

Pin the legacy ID mapping in the adoption test. The source ID is `"cov-" + candidate_id[5:]`. An existing source with that ID returns `already: true` without creating an adoption record, even when the candidate has no archived adoption.

### Claude — plan revision 2 (2026-11-12 06:52 CET)

The points of H-165 are taken. The imported documents are the baseline, never rewritten, and a new adoption overlays
them.

**What the reads combine** (one function, `coverage_inputs`, used by `GET coverage` and by adopt)
- **Overrides by source id.** The imported `coverage_sources.json` `sources` (audit overrides for any source,
  adopted or not), overlaid by the declaration on each `coverage_adoptions` row for its own `source_id`. An imported
  override for another source is untouched.
- **Adoptions by candidate id.** The imported `coverage_adopted.json` `adopted` (each with its original `source_id`,
  `on` and `by`), overlaid by the rows for candidates adopted since. A row never replaces an imported adoption: the
  candidate is already adopted, so adopt answers `already`.
- **The registry.** The old order and sources: `radar_regions.json`, the ecosystem cities, `DEFAULT_ECOSYSTEMS` and
  the imported `coverage_registry.json` additions (custom ecosystems). Nothing adopt writes changes it, as before.
- **Organisations.** `ecosystems.json`, if imported, is read by both `eco` and `coverage`.

None of these files exist in the real data, but the import keeps them as generic documents if they ever do, so the
port reads them as the old code did.

**Adopt, with the legacy id mapping pinned.** The source id is `"cov-" + candidate_id[5:]`, as before. In order:
1. Validate. Refuse with `confirm`, unknown, limited or non-http.
2. **Candidate already adopted** (imported or a row): `{ok: true, already: true, source_id: <its recorded
   source_id>}`. Nothing is written.
3. **A source with that id already exists** in the normalized registry: `{ok: true, already: true, source_id}`.
   Nothing is written, not even an adoption row, even when the candidate has no archived adoption (the old code
   returned before writing).
4. **Otherwise**, the one transaction: the source, its `source_events` row and the `coverage_adoptions` row.

**The hosted test** (Codex's case):
- **Import.** A standalone override for a source that was never adopted, an archived adoption of candidate X (source
  `cov-…X`, its date and operator), and a custom ecosystem in `coverage_registry.json`.
- **Retry X.** The adopt answers X's original `source_id` with `already`, and adds zero rows of any kind.
- **Name an existing source.** An id whose `cov-` id is already a source answers `already`, with no adoption row.
- **Adopt Y.** One source and one row.
- **A fresh GET.** The standalone override, X's adoption and the custom ecosystem are all still there, unchanged, and
  Y is added.
- **The id mapping.** `cov-` plus the id from position 5, asserted on a sample candidate id.

### Codex plan revision 2 verdict

**REQUEST CHANGES.** The shared coverage inputs and combined test resolve the imported-state concern. Correct the order in the numbered adoption rules. Legacy `coverage.py::adopt_candidate` checks confirmation and candidate existence, then returns a recorded adoption before checking current access limitations or URL. The proposed order would refuse a historical retry if the catalog entry has since become restricted or lost its URL. Keep the existing-source lookup after those eligibility checks, as in the legacy code.

Extend the retry test with a known candidate whose current URL is empty and whose archived source ID differs from its derived ID. With confirmation, expect the archived ID and zero writes. Without confirmation, expect the confirmation refusal.

### Claude — plan revision 3 (2026-11-12 06:54 CET)

H-167 is taken. Adopt keeps the old `adopt_candidate` order exactly:
1. No `confirm`: `{ok: false, error: "explicit confirmation required"}`.
2. Not in the current catalog: `{ok: false, error: "unknown candidate"}`.
3. **Already adopted**, imported or a row: `{ok: true, already: true, source_id: <its RECORDED source_id>}`, with
   nothing written. This comes BEFORE the current access and URL checks, so a historical adoption is answered even
   when its catalog entry has since become restricted or lost its URL.
4. An access limitation (captcha / login / paywall / credential / bypass) without `structured` access: the old
   refusal text.
5. No http URL: `{ok: false, error: "candidate has no URL"}`.
6. A source `"cov-" + id[5:]` already in the normalized registry: `{ok: true, already: true, source_id}`, with no
   row.
7. Otherwise, the one transaction.

**The retry test**, extended as asked. A known candidate whose current catalog URL is empty and whose ARCHIVED
adoption recorded a source id different from its derived `cov-` id:
- with `confirm`, the answer is the archived id, `already`, and zero writes;
- without `confirm`, the confirmation refusal.

The combined revision-2 test is otherwise unchanged.

### Codex plan revision 3 verdict

**APPROVE the Ecosystems plan.** Revision 3 matches the legacy adoption order. After confirmation and candidate lookup, a historical retry returns the recorded source ID without writing, even if the current URL is empty. The planned regression uses distinct archived and derived IDs and also checks refusal without confirmation. This resolves H-167. Implementation verification is pending.

### Claude — implementation (2026-11-12 08:01 CET)

Ready for **code review**. The approved plan, with revisions 2 and 3, is implemented.

**The pure port** (`ecosystems/`: `catalog`, `cities`, `inputs`, `coverage`, `adopt`)
- **The catalog.** `scripts/gen_ecosystems_catalog.py` cuts `CITIES`, `ORGS`, `CITY_NOTES`, the coverage families,
  states, labels, thresholds and registries, and the Founder Radar defaults by exact line ranges from the old modules.
- **The logic.** Ported line for line, with the inputs as parameters and the Berlin request clock.
  - Missing bootstrap documents read as the old defaults in memory, and nothing is written on GET (decision a).
  - The quirks are kept (b): event sources are never productive; an unknown earliness raises; a three-element region
    city makes coverage raise; events reading stops at the first bad record.
  - The ecosystem list is built once per call (d).
- **The literal check.** `catalog`, `cities`, `coverage` and `adopt` carry only literals of the old modules.
- **The shipped files.** The three `resources/coverage` files are copied byte-for-byte, with their sha256 tested
  against the old ones.
- **Reused.** `conviction.taste`, `events.engine` / `place` / `registry`, `network.view`, and the normalized
  registry from 021.
- **Revisions 2 and 3.**
  - `merged_overrides` / `merged_adoptions` read the imported documents as the baseline, overlaid by
    `coverage_adoptions` rows. A row never replaces an imported adoption, except an EMPTY `{}` one, which the old
    code did not count.
  - `adopt_plan` follows the old order exactly.

**The database layer** (`ecosystems/store.py`, `api/routers/ecosystems.py`)
- **Reads.** `inputs(now)` reads the normalized registry, the nine archived documents, the records in the old file
  order and the adoption rows. `GET /api/ecosystems/eco` (with the empty city as `Karlsruhe`), `/registry` and
  `/coverage` run in read-only transactions.
- **The write.** `POST /api/ecosystems/coverage/adopt` takes the one write lock, then runs the pure decision. A real
  adoption writes ONE transaction:
  - the whole normalized registry with the watcher appended, as the old `save_registry` did. The save is now one
    Sources-store method, `save_registry`, shared with the toggle;
  - a `source_events` row (`adopt`);
  - the `coverage_adoptions` row, with `adopted_at` = the request clock.

  Before the import it is a 409.
- **Migration 0013.** `coverage_adoptions` (one row per candidate, append-only, RLS on, foreign key to the source)
  and `adopt` in the `source_events` check. The PGlite test covers it.

**The page** (`frontend/src/features/ecosystems/`)
- A port with the same text, panels, chips, dots, table, detail, modal and toasts.
- An adoption also refreshes the Sources registry.
- **Left out:** the Scout Bridge "ask Scout 00 ↗" button and its `bridge_create` action.

**Tests**
- **Old-code goldens** (`oracle_ecosystems.json`, 6c739b9, clean). Synthetic folders of invented names cover:
  - 16 registry cities and every city view;
  - coverage of 60 ecosystems, with all four family states;
  - the standalone override, an archived adoption with a different id and an empty URL, custom ecosystems, and the
    ORGS merge;
  - a 12-step adopt script with coverage and the registry after each step;
  - a defaults / malformed variant, and broken regions.

  0 differences.
- **Real snapshot** (`parity_ecosystems real`): 29 city views, the registry, and coverage of 58 ecosystems. Then a
  real eligible candidate adopted and adopted again, with coverage and the stored registry after each step.
  0 differences.
- **Hosted** (`test_ecosystems_hosted.py`, 4):
  - your combined case. The historical retry answers `cov-legacy-historic` with `already` and writes zero rows, and
    without `confirm` it is the refusal. An existing `cov-` source answers `already` with no row. A new adoption
    writes one event and one row, and a fresh read keeps the standalone override, the historical adoption (id, date
    and operator) and the custom ecosystem. The legacy id mapping is pinned;
  - all-or-nothing: a failure injected after the source write leaves nothing;
  - two concurrent adopts give one source, one row and one event;
  - the write boundary.
- **Unit** (`tests/ecosystems`, 14): the goldens, provenance, the resources, the literal check, the adopt order, the
  merge rules and the kept quirks.
- **Browser** (`ecosystems.spec.ts`): coverage, the registry and the city view render, and a chip opens its city;
  a row opens its detail, Adopt needs the confirmation (Cancel, then adopt), and there is no Scout control; no
  overflow at 1366, 150 % and 1920. The old-vs-new capture is identical at 1366 and 1920, light and dark, apart from
  added test ids.
- **Totals.**
  - Gate passes (backend 1354, frontend 282). E2E: 46 of 46.
  - Hosted: 138 of 139. The one failure was a pooler connection timeout in `test_events_writes_hosted`, which passes
    13 of 13 when rerun on its own.
  - Sources hosted passes 7 of 7 after the `save_registry` refactor.
- **Note.** The pure port and the page were built by two subagents in parallel, against the plan and the interface
  above. I verified both (lint, types, tests, the goldens rerun) and wrote the database layer, the routes, the
  migration, the real-snapshot parity and the hosted and browser tests.

## Codex implementation verdict

**REQUEST CHANGES (H-170).** The adoption write changes the Sources list order for an imported registry missing repair-added sources. The old `adopt_candidate` loads and repairs the registry before appending the watcher. `EcosystemsStore.adopt` appends to `stored` before calling `load_registry`. With an empty stored list I reproduced eight resulting records in both paths. The watcher was first on the store path and eighth on the legacy path. The 14 Ecosystems unit tests pass because the in-memory adoption helper appends to the already-normalized list.

Use the normalized registry in `inputs.sources` as the base for the append and keep the raw stored list for the persistence comparison. Add a store-level regression that adopts against an imported registry missing repair-added entries and checks the complete ordered source IDs on a fresh read against the legacy result.

### Claude — revision 2 (2026-11-12 08:09 CET)

H-171 is fixed. Adopt now does what the old code did: it normalizes the stored registry (the repair-added sources
included), THEN appends the watcher, then saves the whole registry. Before, it appended first and normalized after,
so with an empty imported registry the seven repair-added sources landed after the new one.

**Regression** (hosted). A schema with an EMPTY imported registry and the corpus documents, then an adoption. A fresh
read of the stored registry is the seven normalized sources, then `cov-<id>`. With the old ordering this test fails.
The pure `with_adoption` was already correct, because its inputs are normalized before the append.

Gate passes. Hosted Ecosystems: 5 of 5.

## Codex implementation revision 2 verdict

**APPROVE (H-172).** The store now normalizes the registry before appending the watcher, matching legacy adoption order. The new regression posts through the API and checks every stored source ID in a fresh transaction. With an empty registry it expects all seven repair-added sources in order, followed by the watcher. I reran all 14 Ecosystems unit tests successfully and inspected the hosted regression. Claude reports all five hosted Ecosystems tests passed.

## Grok notes
