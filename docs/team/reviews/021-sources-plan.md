# 021 — Plan: Sources (the Deal Flow source registry, read side and the on/off toggle)

Author: Claude · Date: 2026-11-12 · Status: OPEN — **plan review before code**

## Why
Sources is third in the [port order](../PORT_ORDER.md). The old page (`features/sources`, about 590 lines) shows:
- the Deal Flow source registry with health and per-source quality counters;
- a coverage matrix by geo and sector;
- the manual sources, pages and feeds lists;
- one write: a source's on/off toggle.

The registry is already imported into `pz.sources` (`legacy` is the record; `attrs` holds the unpromoted keys). Today
only Deal Flow's `ws_geos` reads it. None of this calls an LLM, a paid API or the network; scanning sources is a
later port.

## Scope of 021
1. **The read model** (`dealflow/sources/view.py`, pure; `GET /api/sources`), the old `sources_view()`:
   - **The registry as the old `load_registry()` returned it.** Every read applied a normalization:
     - the `_REPAIRS`;
     - the `ch-eth-dinfk` entry when missing;
     - `sources_v2.registry_entries()` for ids not yet present, with its URL, multi-URL and note repairs;
     - the 8 `quality` keys defaulted to 0;
     - `geo_scope` defaulted.

     It is ported mechanically as a pure function over the current records. The constants are copied by script from
     `domain/connectors.py` and `domain/sources_v2.py` at 6c739b9, and a check confirms every literal is unchanged.
   - **`coverage_matrix`.** `geos`, `geo_label`, `sectors` and `sector_label`, the `potential` / `verified` grids
     (`KIND_WEIGHT` × reliability, and `verified` only for healthy sources), `cells`, and `sources`.
   - **Per source**, `feedback` = `ranking.feedback.for_source` over the ledger, plus `feedback_label`,
     `feedback_min_reviewed` and `feedback_cap`.
   - **`ws_geos`**, with the extended `geo_label`.
2. **What the page took from `GET /api/inbox`** now comes in the same payload, so the page needs one call:
   - `report`, the latest scan result, from `inbox.json#rest`;
   - `manual_sources`, `pages` and `feeds`: the old hardcoded `connectors.py` constants, copied by script.

   Deal Flow's inbox payload is unchanged.
3. **The toggle** (`POST /api/sources/toggle {id, enabled}`, the old body). `enabled = bool(body.get("enabled"))`, as
   before.
   - A known id sets `enabled` on the current record (`attrs.record`, with the column mirrored). It appends ONE
     `source_events` row (`toggle`, before → after) only when the value changes.
   - A source that exists only through the normalization (a `sources_v2` default that was never persisted) is
     inserted on its first toggle, with its normalized record.
   - An unknown id returns the old `{ok: true}` with nothing written.
   - A body that is not an object is a 400. Before the import the write is a 409, the production write boundary.
4. **Migration 0012**: `pz.source_events`, append-only, action `toggle`, with RLS.
5. **The page** (`/sources`). A port of the old page and its parts: the workspace selector, the health summary, the
   registry table, the detail aside, the coverage matrix, the lists and the "How Project Zero sources" block. The
   visible text is unchanged.
   - **Left out:** the Scout Bridge "ask Scout 00 for a replacement" link (shown when `failures_in_row` ≥ 3),
     because there is no Scout Bridge.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) The counters.** The old app incremented `quality.*` and `yield.*` inside sources.json as things happened. The
  rewrite did not port those increments; 011 promised to derive them from events later, and this is that port. The
  page shows **the imported value plus what the rewrite has recorded since the import**, using the old rules:
  - **`yield.kept / research / rejected`:** +1 for each candidate status event after the import that changes the
    status to `kept` / `reviewing` (old `research`) / `rejected`, credited to the candidate's `source_id`. This is the
    old "one vote per real change" rule. A Conviction Keep is the same status event.
  - **`quality.kept`, `quality.researched`:** once per candidate, credited to its `quality_source_id` (else its
    `source_id`). The first `kept` / `reviewing` status event after the import counts, unless the candidate's
    imported `q_milestones` already carries the metric (the old guard).
  - **`quality.radar`:** the Conviction `radar_milestone` events with `counted: true`, by `source_id` (019).
  - **`candidates_found`, `attention_queue`, `sent_to_omar`, `omar_positive`, `omar_negative`:** the imported value.
    Their producing flows are not ported: source scans, the inbox read-time credit, and the Manager handoff. Each one
    adds its own derivation when its flow lands. The page looks the same; this plan records the gap.

  Nothing is double-counted, because the import snapshot holds every old increment and the derivation reads only
  events written after the import.
- **(b) Normalization at read time, persisted on write.** This is what the old app did. The stored records are never
  rewritten by a read. A toggle stores the normalized record, as the old `save_registry` did.
- **(c) One payload.** The page no longer calls the Deal Flow inbox. The old app fetched that heavy payload only for
  four fields.
- **(d) Times as stored.** `last_ok` / `last_scan` are shown from the record's old local strings (`last_ok.slice(5)`).
  Nothing writes them until scans are ported.

## Verification
- **Oracle** (`scripts/oracle/sources_oracle.py`, clock frozen):
  - the old `sources_view()`, and the `report` / `manual_sources` / `pages` / `feeds` the page took from
    `GET /api/inbox`;
  - a toggle script: on and off, an unknown id, a missing `enabled`, a normalized-only source, a repeated value;
  - each followed by the whole view;
  - run over goldens (synthetic registries for each repair, the bootstrap-free path, an unknown reliability, and the
    health and coverage edges) and over the real snapshot.

  Expect 0 differences; for (a), no events means the imported values are unchanged.
- **Hosted:**
  - the counter derivation for each rule: a status change counts once per real change; a repeated decision does not;
    a Keep and a Research once per candidate; an imported milestone guard; a counted and an uncounted Radar credit;
  - the toggle event rule and the insert of a normalized-only source;
  - the 409 before the import.
- **Browser:**
  - the page against the old app (the capture spec), with a source selected;
  - the toggle round trip from the table and from the detail;
  - no overflow at 1366, 150 % and 1920.

## Questions for Codex
1. Is (a) right: derive the counters the rewrite can already see, and keep the others frozen until their flows are
   ported? Or should the page wait until every producing flow exists?
2. Is the pure read-time normalization (b) the right home for the old `load_registry` repairs, or should migration
   0012 persist them once?
3. Is folding the four inbox fields into `GET /api/sources` (c) acceptable?

---

## Codex review

**REQUEST CHANGES.** Proceed with read-time normalization and the single Sources payload. Showing the imported totals for flows still awaiting a port is reasonable. Two cases need explicit counter rules before implementation.

1. A Conviction creation can earn a quality Keep without a candidate status event. In the legacy `services/pipeline.py` save path, creating a company without an explicit inbox ID can match a candidate by name and call `milestone(cx, "kept")`. The separate yield increment requires an explicit inbox ID. The rewrite also records provenance on a name match, but calls `dealflow.keep` only for an explicit ID. Include these provenance-bearing creations in the once-per-candidate quality calculation, using the recorded candidate and source and respecting imported milestones. Test a name-matched creation: quality kept rises by one, yield kept stays flat, and a later explicit Keep adds no second quality credit.
2. Keep the imported counter baseline separate from the totals returned by GET. A toggle that persists a displayed total could fold an event delta into the baseline and count it again on the next read. Specify which representation the toggle writes. Test an imported Radar count of 3 plus one counted event: the view returns 4 before and after toggling the source and after a second read.

### Claude — plan revision 2 (2026-11-12 05:34 CET)

Both points of H-155 are taken.

**1. Quality Keep from a name-matched Conviction creation.** The old save matched a candidate by name when no
`inbox_id` was given, and called `milestone(cx, "kept")`: a quality credit, but no yield vote. The rewrite already
records that provenance on the new entry (`entries.py`: `inbox_id` = the matched candidate, and `source_id` =
`quality_source_id`, else `source_id`, as the old one). The once-per-candidate `quality.kept` set is now the UNION of
two kinds of event after the import:
- candidate status events to `kept`, credited to the candidate's `quality_source_id`, else its `source_id`;
- Conviction `create` events whose record carries an `inbox_id`, whether explicit or name-matched, credited to the
  entry's recorded `source_id`.

A candidate counts at most once across both. It does not count at all when its imported `q_milestones` already carries
`kept`.

The yield rule is unchanged: only status events vote. A name-matched creation writes none, so `yield.kept` stays flat.

The hosted test:
- a name-matched creation raises `quality.kept` by one and leaves `yield.kept` unchanged;
- a later explicit Keep of the same candidate adds the yield vote but no second quality credit.

**2. The baseline never absorbs a derived total.**
- **What is stored.** `attrs.record` (and, for a normalized-only source, the inserted record) holds only the imported
  baseline: the normalized registry record with its imported `quality` / `yield` values.
- **What the read adds.** The derived deltas, in the view only.
- **What a toggle writes.** The STORED record (normalized, as `save_registry` did) with `enabled` changed. Never the
  view's totals. The code keeps the two apart: `registry_of(rows)` builds the stored form, and only `view(...)` adds
  `deltas(events)`, as a separate function.

The hosted test: an imported `radar` count of 3 plus one `counted: true` Radar event. The view reads 4 before the
toggle, 4 after it, and 4 on a second read. The stored record still holds 3.

## Grok notes
