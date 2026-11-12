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

## Grok notes
