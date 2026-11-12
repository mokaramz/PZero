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

## Grok notes
