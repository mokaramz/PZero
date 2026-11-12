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

### Codex plan revision 2 verdict

**APPROVE the Sources plan.** The Conviction creation event retains the matched candidate ID and source. Revision 2 uses that evidence to count the first quality Keep once across both creation and status events. A name match earns no yield vote until an explicit status change. The toggle writes the stored baseline, and the proposed test checks both the stored Radar count of 3 and the displayed count of 4 after toggling and rereading. Both H-155 questions are resolved. Implementation verification is pending.

### Claude — implementation (2026-11-12 06:24 CET)

Ready for **code review**. The approved plan, with revision 2, is implemented.

**The catalog and normalization** (`dealflow/sources/catalog.py`, `normalize.py`)
- **Cut by script.** `scripts/gen_sources_catalog.py` cuts each needed top-level definition of the old `connectors.py`
  and `sources_v2.py` by its exact line range. These are the three lists, the coverage constants, `_REPAIRS`, the
  three `sources_v2` repair tables and `registry_entries()`. The only edit is one return-type hint.
- **Ported line for line.** `normalize.py` holds `_apply_repairs`, the `load_registry` defaults and
  `coverage_matrix`, run on a copy of the stored records. The unknown-reliability `KeyError` is kept.
- **The literal check.** It confirms both modules carry only literals of the old modules (docstrings aside).

**The view** (`view.py`) is the old `sources_view()`:
- `feedback.for_source` over the effective ledger, `ws_geos` and the extended `geo_label`;
- plus `report` (from `inbox.json#rest`), `manual_sources`, `pages` and `feeds`. One call.
- The deltas are added in `with_deltas` to a deep copy only.

**The counters** (`counters.py`, decision a and revision 2). The pure `derive` reads only live events
(`actor <> 'import'`):
- **Yield:** one vote per change of the old decision (`archived` → `rejected` is no change), credited to `source_id`.
- **Quality kept / researched:** once per candidate, credited to `quality_source_id`, else `source_id`, with the
  imported `q_milestones` guard. Kept is the union with Conviction `create` events that carry an `inbox_id`, so
  name-matched creations count.
- **Quality radar:** counted `radar_milestone` events.
- **The rest:** found, attention and the Manager counts keep their imported value.

**The toggle** (`store.py`, `POST /api/sources/toggle`)
- `bool(enabled)`. An unknown id, or an unchanged value, writes nothing.
- A real change does three things:
  - it stores the normalized record (the baseline only), with the columns mirrored;
  - it also stores every source that existed only through the normalization, in its normalized order
    (`clock_timestamp()`), as the old `save_registry` persisted the whole registry, so the order never moves;
  - it writes one `source_events` row (migration 0012, append-only, RLS on).
- Before the import the toggle is a 409.

**The page** (`frontend/src/features/sources/`)
- A port with the same text, sections, columns, detail, matrix, lists and toasts, the shared workspace preference,
  one `GET`, and the optimistic toggle with a refetch on error.
- **Left out:** the Scout Bridge "ask Scout 00 for a replacement" link. It was an inline addition to the meta line,
  so nothing replaces it.
- **Small deliberate differences:**
  - the lists load with the rest, from the same payload;
  - an active source without an adjustment shows `0` (the old page showed "undefined").

**Tests**
- **Old-code goldens** (`oracle_sources.json`, 6c739b9, clean): 22 invented sources, which normalize to 26. They cover
  every repair condition, `_repair_v` 2, the URL / multi / note repairs, each `geo_scope` default, health, coverage
  and kind edges, a missing reliability, feedback on 6 decisions and the inbox `report`. The pure view shows 0
  differences, and a registry with an unknown reliability raises in both.
- **Hosted** (`test_sources_hosted.py`, 5):
  - the golden registry seeded as the import writes it, plus a 7-step toggle replay: every GET identical, 4 events,
    and the normalization-only `ch-epfl-creation` inserted in order;
  - yield once per real change, and quality kept / researched once per candidate with the imported guard (Keep
    through the Conviction workflow);
  - a name-matched creation: quality +1 and no yield, then a later Keep: the yield vote and no second credit;
  - the baseline: radar 3 plus 1 reads 4 before the toggle, after it and on a second read, with 3 stored;
  - the write boundary.
- **Real snapshot** (`parity_sources real`): all 46 sources, the whole GET and a 5-step toggle replay, 0 differences.
  It was rerun after the order fix.
- **Unit** (`test_sources_port.py`, 8): the literal check, the goldens, the baseline copy, and every counter branch.
- **Mutations, each caught:** a repeated decision voting; the imported guard ignored; name-matched creations
  ignored; kept credited to `source_id`; deltas folded into the stored form.
- **Browser** (`sources.spec.ts`): one `GET` and no inbox call; a table row opens the detail; the toggle off and on
  against a fresh read; no overflow at 1366, 150 % and 1920. The old-vs-new capture is identical at 1366 and 1920,
  light and dark, except the removed bridge link and two added test ids.
- **Totals.** Gate passes (backend 1,337, frontend 254). Hosted: 133 of 133. E2E: 43 of 43.

### Codex implementation review

**REQUEST CHANGES.** `counters.derive` processes every candidate status event before any Conviction creation, regardless of their relative dates. I checked a name-matched creation that recorded source A, followed by an explicit Keep when the candidate record supplies source B. The function credits both quality and yield to B. The earlier creation already earned the single quality credit for A. With no source on the candidate row, the same check returns no credit at all: `quality_credit` marks the milestone done even when `_bump` adds nothing. The legacy milestone function returns before marking a candidate when there is no source.

Preserve the relative order of eligible events, and consume the quality milestone only when there is a source to credit. Add a regression with distinct creation and status sources, and one where a source-less event precedes a valid credit. Verify the per-source totals and the separate yield vote. All eight offline Sources port tests passed independently.

### Claude — revision 2 (2026-11-12 06:33 CET)

H-159 is fixed in `counters.derive`.
- **Time order.** Status events and Conviction creations are one stream in their relative time order (`at`). On a
  tie, a creation comes before a status event: an explicit Keep writes both in one transaction, and the old save
  credited the milestone first. Then by id. The first eligible event earns the single quality credit, and its source
  is credited.
- **No source, nothing consumed.** An event with no source credits nothing and consumes nothing, like the old
  `milestone`, which returned before marking. A later event with a source can still earn the credit.
- **Regressions.** Unit:
  - a creation with source A, then a Keep whose candidate names B: quality A +1, B nothing, and the Keep's yield
    vote goes to the candidate's `source_id`;
  - the reverse order credits B;
  - a source-less Keep, then a creation with A: A +1;
  - a source-less research: nothing.

  Hosted, end to end: a name-matched creation records A; the candidate's provenance changes to B; an explicit Keep
  (its own linked entry) gives quality A 1, B 0, and yield B 1, A 0.
- **Mutations, each caught:** status events before creations; a source-less event consuming the credit.

Gate passes (backend 1,339, frontend 254). Hosted Sources: 6 of 6.

### Codex implementation revision 2 verdict

**REQUEST CHANGES.** Revision 2 fixes event ordering and lets a later sourced event earn the first credit. All ten offline Sources tests passed independently. One attribution issue remains in the status-event path: `_STATUS` reads the transition, then `derive` takes both source IDs from the candidate's current row. If a Keep occurs under source A and a subsequent re-report changes the candidate to B, the next Sources read moves the historical yield vote and status-earned quality credit to B, even without a new decision.

Capture the yield source and effective quality source at decision time for both status writers, including Conviction Keep. Use those values in the counter calculation and specify the fallback for existing events without them. Test an explicit status change under A followed by a provenance change to B: a second GET should leave the earned totals with A. The current hosted test changes provenance before the status event.

### Claude — revision 3 (2026-11-12 06:43 CET)

H-161 is fixed. Both status writers now record the decision-time sources in the event:
- `DealFlowStore.decide`, for Research, Reject, Watch and every other change;
- `DealFlowStore.keep`, the status half of a Conviction Keep.

The record is `detail.sources = {source_id, quality_source_id}`, with `quality_source_id` falling back to `source_id`
(`decision_sources`, the old `decide` / `milestone` reads). `counters.derive` credits the yield vote to the recorded
`source_id` and status-earned quality to the recorded `quality_source_id`.

**The fallback.** An event without `detail.sources` reads the candidate's current provenance. Only events written
before this revision lack it: the preview and test schemas. Production writes start after the import, so none
exists there.

**Regressions**
- Unit: a Keep recorded under A (quality source Aq) while the candidate now names B. The yield vote goes to A, the
  credit to Aq, and B gets nothing. The same event without `sources` falls back to B.
- Hosted, end to end: a Research decision and a Conviction Keep under source A, then a provenance change of both
  candidates to B. Two later reads both give `src-a` yield kept 1, research 1 and quality kept 1, researched 1, and
  `src-b` stays at 0.
- **Mutation, caught:** ignoring the recorded sources.
- The ledger reads `detail.feedback` only, so its parity is unaffected. Hosted Deal Flow, feedback and Conviction
  pass (24 with Sources).

Gate passes (backend 1340, frontend 254).

### Codex implementation revision 3 verdict

**APPROVE.** Both the Deal Flow decision and Conviction Keep paths record the yield source and effective quality source on each new status event. The counters use those recorded IDs, so changing a candidate’s provenance later preserves the credit already earned. Older events without recorded IDs use the documented current-source fallback. All 11 offline Sources tests passed independently, including the distinct yield and quality source regression. Claude reports the hosted end-to-end case also passed.

## Grok notes
