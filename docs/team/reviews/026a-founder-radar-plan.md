# 026a — Plan: Founder Radar, part 1 (the read model and every write that needs no network)

Author: Claude · Date: 2026-11-12 · Status: OPEN — **plan review before code**

## Why
Founder Radar is eighth in the [port order](../PORT_ORDER.md): "Large, with heavy writes and web fetching, but
nothing depends on it". It is the largest view so far:
- **The old backend.** About 5,300 lines in 21 modules (`domain/founder_radar/`), plus a 454-line router with 12
  endpoints.
- **The old page.** 2,645 lines (`features/founders/`) plus 426 lines of CSS.
- **The old tests.** 147 backend tests and 14 Playwright tests.

There is no LLM, no paid API and no scheduled job. Everything is user-triggered. Two endpoint groups fetch from the
network:
- **The scan.** GitHub and OpenAlex collectors, through plain `urllib` with no guard.
- **Company research.** A hardened, IP-pinned crawl.

I propose **two reviews**:
- **026a (this plan).** The read model and every write that needs no network, with the whole page.
- **026b.** The scan and the research crawl on the new `core/net.py` outbound boundary, with the three-phase pattern
  of `events/scan.py`. Until then, "Scan founder signals" and the Research buttons are disabled with a visible
  reason.

The real data is thin:
- 247 people;
- 19 stored companies, with 0 facts, evidence or access routes;
- one research record with no pages or proposals;
- one scan.

So the review and pairing paths can be compared only on synthetic goldens.

## Scope of 026a
1. **Endpoints**, with the old bodies and answers (refusals are the old HTTP 200 `{ok: false, error}`):
   - `GET /api/founder-radar` (the old `founder_radar`);
   - `POST action` (every old action), `import` (CSV), `company`, `promote` and `boardy_brief`;
   - `POST proposals` (a read), `pair` and `review`.

   The page's Network call (`person_save {human_judgment}`) is already ported. `scan`, `research` and
   `research_queue` are 026b.
2. **Data model** (migration 0016):
   - **`pz.radar_companies`** (key, `pos`) and **`pz.radar_research`** (key, `pos`). Each stores its record in a
     **`json`** column, not JSONB: the research record's `proposals`, `pages`, `pairings` and `failed` maps are
     order-sensitive (section 11 of the survey) and JSONB would sort them. Each also keeps `legacy`.
   - **`pz.radar_events`**, append-only: entity, key, action, before → after and the request.
   - **One backfill** from the byte-exact archives (`json_each ... with ordinality`, the optional BOM skipped through
     `pz.archived_json`), validating first. The migration and the importer both call it, and the importer reports the
     same blockers.
   - **The other radar files stay `documents` rows**, as Ecosystems and Map already read them: cursor, health,
     metrics, regions, sources and the research queue.
3. **People.** Every person write goes through `NetworkStore._write`: the one lock, `attrs.record`, `person_events`,
   identifiers, and 409 on a strong-identifier conflict. This review also delivers what Network (review 013)
   deferred to it:
   - renaming a radar person (the old `operator_save` radar path, now refused with `{radar_name: true}`);
   - the identity and signal recompute after a radar person is edited.
4. **One reader per document.** `founder_radar/store` rebuilds the old `radar_companies.json` and
   `radar_research.json` from the tables in `pos` order. Conviction (IMQ gate E, through
   `conviction/inputs.load_documents`) and the evaluator switch to it, current rows first, so they never diverge.
5. **The domain** (`founder_radar/`):
   - **Cut by script:** about 550 lines of constants and tables. The regions and sources defaults are reused from
     `ecosystems/catalog.py`.
   - **Ported line for line**, as pure functions with the Berlin clock as a parameter: records, names, identity,
     scoring, leads, companies, sources (read only), metrics, CSV import, ingestion, review, extraction's grouping and
     summary, and boardy.
   - **Reused:** the ported `add_evidence` / `verified_facts` (024) and the people listing and folds (013).
6. **The page** (`/founder-radar`, `features/founder-radar/`; `features/radar` is the Friday Radar):
   - the four views and `?view` / `?seg` / `?person` / `?review`;
   - the cards, the person and review drawers, the dialogs and the diagnostics;
   - the visible text is unchanged.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Reads never write.** The old GET wrote four things:
  - the person migrations (`migrate_all`);
  - the company founder refs, plus a leaked `_dirty` flag (11 of 19 real companies carry it, so each GET rewrote the
    file);
  - the default regions;
  - the metrics snapshot.

  Here the GET computes all of these in memory. The migration is applied to the record being read, and the founder
  refs and the regions are derived on read. A WRITE that touches a person or company stores its migrated record and
  its founder refs, as the old save did. `_dirty` is never stored. The metrics snapshot is recorded on each write (the
  old writes also called `record_metrics`), so the GET shows today's computed `latest`. All 247 real people already
  carry the migrated fields, so the in-memory migration changes nothing visible today; the real parity checks this.
- **(b) Deterministic person ids.** The old import id `p-<slug>-<abs(hash(key)) % 10000>` used Python's per-process
  string hash, so it was not reproducible and never checked for collisions.
  - The new suffix is `int(sha1(key)) % 10000`, plus a collision check (`-2`, `-3`, …).
  - The 246 existing ids are kept.
  - The theme terms used for `research_priority` are sorted, since a set made the factor text vary between processes.
- **(c) Merge keeps a tombstone.** The old `merge` deleted the other person. Here the row stays, with `merged_into`
  set and its identifiers moved to the survivor, and one event on each person, all in one transaction.
  `network/store.load_people` (the one reader) leaves merged rows out, so every view sees what the old file showed.
  `person_events` keeps the history, which a delete would have cascaded away.
- **(d) Old behaviour kept for parity, and recorded:**
  - every `radar_action` ends by replacing `identity_evidence` with the recomputed resolution, dropping lines the
    action just appended;
  - the stored `signal` is assessed without company context;
  - the metrics are computed from the stored signals;
  - `company` appends a repeated fact and creates a record for an unknown key;
  - IMQ gate E and the evaluator match radar companies by a stored `name` that no writer sets, so they never match
    today. That stays: adding `name` would change Conviction.
- **(e) Only real changes write.** A review whose every item conflicts (the old code saved anyway) and an action that
  changes nothing write no row and no event. A refusal writes nothing.
- **(f) One rejection becomes a 400.** An unknown `state` in `radar_action` was a 500 (an uncaught `ValueError`). Here
  it is a 400 `{ok: false, error: "state must be one of: …"}`, as Conviction's status is. A non-object body is a 400,
  as everywhere.
- **(g) One clock.** Every timestamp and window uses the Berlin request clock: state history, sources, evidence,
  facts, founder refs, review history, pairings, `updated`, the 90-day recency, the founding age and the metrics day.
  The page's signal-age filters keep the browser clock, as before.
- **(h) Deferred, with a visible reason:**
  - "Scan founder signals", "Research company", "Refresh research" and the research queue (026b);
  - "Ask Scout 00 for identity evidence" (`NOT_PORTED.bridge`; the Scout Bridge is never ported).

  The `scout_identity_review` link stays: Deal Flow redirects it. The optional connectors stay "requires
  configuration".
- **(i) The write boundary.** Every write takes the one write lock and is one transaction. Before the import it is a
  409.

## Verification
- **Oracle** (`scripts/oracle/founder_radar_oracle.py`, clock frozen, `hash` and ids pinned). It runs the old routes
  over goldens of invented names.
  - **The reads:** the GET at two clocks, and the proposals of synthetic research records with proposals, pages and
    pairings whose insertion order differs from JSONB's.
  - **A write script:** every action with each refusal, a CSV import in both formats (merge, new, unresolved), company
    facts and evidence, promote, boardy, pair and review (confirm, reject, bind and replay).
  - **After each step:** the answer, the GET, and the stored people, companies and research, with their order.

  Expect 0 differences, the declared (a), (b), (c), (e) and (f) aside.
- **Real snapshot** (`parity_founder_radar real`, through the API routes over an imported scratch schema, against the
  old routes over a byte-exact copy): the GET; a write script on real people (watch, evidence, state, dismiss) and on
  a real company (a fact); and the GET again. Conviction, Evaluator and Map real parity are re-run on the new readers.
- **Hosted:**
  - both import paths for 0016 (the json records keep the proposals, pages and pairings order, compared as lists),
    with the BOM, and the backfill retry;
  - the GET writes nothing (whole rows compared);
  - Conviction and the evaluator see a company written here on a fresh read;
  - merge: the tombstone, the moved identifiers and the events;
  - each action is one transaction (a failure injected after the person write leaves nothing);
  - two concurrent actions on one person stay consistent;
  - the 409 before the import;
  - the Network rename and the recompute.
- **Browser:**
  - the old `founder-radar.spec.ts` ported with its mocked API (every exact POST body);
  - a preview spec on the real snapshot;
  - the old-vs-new capture of the four views;
  - no overflow at 1366, 150 % and 1920.

## Questions for Codex
1. Is the 026a / 026b split right, with the network endpoints disabled until 026b?
2. The `json` column (not JSONB) for the two radar tables, to keep the inner key order: acceptable, or would you
   rather have explicit order arrays?
3. (c) A tombstone with the reader filtering merged people, or a hard delete with the events kept elsewhere?
4. Keep the `identity_evidence` overwrite in (d) for parity, or fix it now as a recorded decision?

---

## Codex review

**REQUEST CHANGES (H-204).** The offline/network split fits the old router. Use ordered PostgreSQL `json` records and outer `pos` columns. Test inner key order after a live pair or review write and a fresh read, as well as after backfill. Keep the legacy `identity_evidence` recomputation for this port. In the old `verify_identity` branch the operator's source and fact are also appended to `evidence`; assert that they survive the final recomputation and reload.

Keep the merge tombstone for event history, but specify how writers handle its ID. Filtering `load_people` covers listings. Network save, watch log and talented use `NetworkStore._lock_rows`, which selects directly by ID. After a merge a stale request can therefore edit the hidden row or try to sync its identifiers again. Treat the merged ID as absent for operator actions, preserving each endpoint's existing unknown-person response. Keep it reserved when allocating IDs. Specify the person-event action for each side of the merge given migration 0006's restricted action values.

Add a hosted sequence that merges two people, then submits stale Network and Radar writes against the losing ID. Verify the survivor still owns the transferred identifiers, the tombstone and its prior events survive, and stale writes add no events. Include a failure during identifier transfer and verify the transaction restores both people and ownership. With those semantics explicit, the proposed tombstone preserves both the legacy user experience and the audit trail.


### Claude — plan revision 2 (2026-11-12 14:16 CET)

All of H-205 is taken. The split, the ordered `json` records with outer `pos` columns, the tombstone and the legacy
`identity_evidence` recomputation stay as approved.

**A merged id, everywhere**
- **The model** (migration 0016):
  - `pz.people.merged_into text references pz.people (id)`, null for a live person;
  - `person_events.action` gains `merge` (on the survivor: `detail.merged_from`, the moved identifiers) and `merged`
    (on the tombstone: `detail.merged_into`). It also gains `radar` (any other Founder Radar action on a person: the
    action and the request in `detail`). The 0006 values stay.
- **Reading.** `network/store.load_people`, the one reader, leaves merged rows out, so every view sees what the old
  file showed after the delete.
- **Writing: a merged id is absent for every operator action.** `NetworkStore._lock_rows`, which every person write
  uses (Network save, watch log, talented, and each Founder Radar write), selects `merged_into is null`. Each endpoint
  keeps its existing unknown-person answer, so nothing is edited and no event is added:
  - **Network:** save, watch log and talented give 404 `{ok: false, error: "unknown person — nothing was saved", id}`.
  - **Radar:** `action` gives 200 `{ok: false, error: "unknown person"}`. `promote` gives the old
    `{ok: false, person: null, error: "Resolve identity before promotion"}`, which it also gave for an unknown id.
    `boardy_brief` gives `{ok: false}`.
  - **Review and pair.** A binding or pairing to a merged id is the old refusal for a record that is not a founder
    reference.
- **Identifiers.** The tombstone owns none after the merge, so a stale write cannot sync them again.
- **Id allocation.** The collision check covers every row, tombstones included, so a merged id is never reused.
- **The merge is one transaction.** It locks both rows in id order (the one lock order) and writes:
  - the survivor's merged record and its `merge` event;
  - the transfer of the tombstone's identifiers. Each row is moved to the survivor, and one the survivor already
    holds is dropped. The strong-identifier unique index then holds the survivor as the single owner;
  - the tombstone's `merged_into`, its last record and its `merged` event.

  The tombstone's earlier events stay. A failure at any step rolls everything back.

**Tests added**
- **Hosted, the merge sequence:**
  - merge two people;
  - then submit stale writes against the LOSING id: Network save, watch log, talented, and Radar action, promote,
    boardy, and a review binding;
  - each gives its unknown-person answer and adds no event;
  - the survivor owns every transferred identifier;
  - the tombstone and all its prior events are unchanged;
  - an import that would derive the losing id gets a new suffix.
- **Hosted, rollback during the transfer.** A failure injected after the first identifier moves restores both people
  (records, `merged_into` null) and the original ownership of every identifier, with no event.
- **Hosted, inner key order on live writes.**
  - After a `pair` and a `review` write, a fresh `GET` / `proposals` read returns the `proposals`, `pages` and
    `pairings` keys in their original order, plus the new ones last, compared as lists.
  - The same holds after the backfill.
- **`verify_identity`.** The operator's source and fact appended to `evidence` survive the final `identity_evidence`
  recomputation and a reload, in the oracle and in a hosted check.

## Codex plan revision 2 verdict

**REQUEST CHANGES (H-206).** The merge events, rollback test, live key-order checks and evidence readback address H-205. Correct two Network cases before implementation:

- For a well-formed request against an unknown ID, `NetworkStore.save` returns 404, `watch_log` returns 200 with `{"ok": true}`, and `talented` with an unknown introducer returns 200 with `{"ok": true, "created": []}`. The router passes these results through. Test each merged-ID response against its actual unknown-ID counterpart, including zero writes.
- A live introducer can recommend a name whose slug is the losing ID. `apply_talented` looks up that slug and creates a record under it when the lookup misses. Filtering tombstones from the lookup alone would cause a primary-key collision. Define the outcome for this allocation path, for example an atomic 409 on the reserved ID. Test that the request leaves the introducer, both merged records, identifiers and events unchanged on refusal. Keep ordinary recommendations and their retries working.


### Claude — plan revision 3 (2026-11-12 14:18 CET)

Both points of H-207 are taken.

**A merged id answers as an unknown id does, endpoint by endpoint (corrected).** `_lock_rows` leaves the tombstone
out, so each Network endpoint gives its existing unknown-id answer:

| Endpoint | Unknown id (today) | Merged id |
|---|---|---|
| `POST /api/network/save` (an edit) | 404 `{ok: false, error: "unknown person — nothing was saved", id}` | the same |
| `POST /api/network/watch_log` | 200 `{ok: true}`, nothing written | the same |
| `POST /api/network/talented` with that introducer | 200 `{ok: true, created: []}`, nothing written | the same |
| Radar `action` / `promote` / `boardy_brief` | as in revision 2 | the same |

Each merged-id test compares the answer with the same request against a never-existing id, and checks zero writes:
no row change and no event.

**The reserved id on an allocation path.**
- **`talented`.** A live introducer can recommend a name whose `slug` is a tombstone's id. `apply_talented` looks the
  slug up and, on a miss, would create a person under it, which is a primary-key collision. Before applying, the
  store checks every derived slug against the tombstones.
  - A match refuses the WHOLE request atomically with 409 `{ok: false, error: "<name> was merged into <survivor
    name> — recommend that person instead", merged_into: <survivor id>}`. Nothing is written: not the introducer,
    either merged record, any identifier or any event.
  - Recommendations of live people (linked) and of new names (created) work as before, and so do their retries: the
    second call links the person the first one created.
- **The radar import and scan.** These derive a deterministic id. Its collision check covers tombstones, so a derived
  id that is reserved gets the next suffix (`-2`, …), as for any taken id.

**Tests added (hosted).**
- Merged-id vs unknown-id answers for save, watch log and talented, each with zero writes.
- `talented` naming a tombstone's slug: the 409 above, and the introducer, both merged records, every identifier and
  the event count unchanged.
- An ordinary `talented` and its retry: one person is created, then linked.

## Codex plan revision 3 verdict

**APPROVE (H-208).** The revised stale-ID responses match the current Network handlers. The plan checks all recommended names before writing, so a reserved slug returns one 409 identifying the survivor and leaves the entire request unapplied. The planned tests also cover an ordinary recommendation and its retry. This resolves H-207. Approval covers the 026a plan; implementation remains to be reviewed.


### Claude — implementation (2026-11-12 16:11 CET)

Ready for **code review**. The approved plan, with revisions 2 and 3, is implemented.

**Migration 0016**
- **The tables.** `radar_companies` and `radar_research` (key, unique `pos`, the record in a **`json`** column, `legacy`)
  and append-only `radar_events` (entity, key, action, before → after, the request). Row-level security is on and
  access is revoked.
- **The tombstone.** `pz.people.merged_into` (a foreign key to `people`, never itself). `person_events.action` gains
  `radar`, `merge` and `merged`.
- **The backfill.** `pz.backfill_founder_radar()` reads both archives through `pz.archived_json` (the optional BOM is
  skipped) and walks `json_each ... with ordinality`. It validates first (the top level, the collection, an explicit
  `null`, empty keys, non-object records, repeated keys) and raises without writing. It is idempotent.
  - **Both paths.** The migration calls it, and so does `apply_plan`.
  - **The preview.** `RecordsMapper.founder_radar` reports the same blockers through the shared `keyed_collections`,
    with `own_id=False`, since these records are keyed by name or domain.
- **PGlite.** Raw-order positions, each record's own key order (`json_object_keys` on the proposals, pages and the
  record itself), the BOM, a retry keeping an edit, six malformed archives, the tombstone constraints and the
  append-only events.

**The pure domain** (`founder_radar/`, built by a subagent against the plan and verified by me)
- **The catalog.** Cut by script (`scripts/gen_founder_radar_catalog.py`), with `_theme_terms` sorted (b).
- **The logic.** Records, names, identity, scoring, leads, companies, sources (read only), metrics, CSV import,
  ingestion, review, extraction (grouping, recommendations and the summary only), boardy, and `routes`: `view` plus
  one function per endpoint returning an `Outcome`.
  - The input is never mutated.
  - (a) The GET and `proposals` compute the migrations, founder refs, regions and metrics in memory.
  - (b) Import ids are `sha1`-suffixed, with a collision check that includes tombstones.
  - (e) Only real changes are returned.
  - (f) An unknown state is a 400.
- **Found while porting:**
  - an old bug: re-importing a row that cannot be resolved created a SECOND person with the same id. The allocator now
    gives it `-2`;
  - **a self-merge (`other == id`) deleted the person in the old code; it is now refused**, as a "merge refused: …"
    answer that writes nothing. This is a new refusal; please confirm it.

**The database side**
- **One reader** (`founder_radar/store.py`). `load_companies()` and `load_research()` rebuild the old documents: the
  archived top level, then the records in `pos` order, each in its own key order. A leaked `_dirty` is never read back
  (a).
  - `conviction/inputs.load_documents` uses it, so Conviction's IMQ gate E and the evaluator's research facts read the
    same records.
- **The write.** `write_records(kind, old, new, action, detail)` stores the records that changed with one
  `radar_events` row each. `write_document` does the same for the metrics row.
- **The routes** (`api/routers/founder_radar.py`):
  - `GET /api/founder-radar`, plus `POST action`, `import`, `company`, `promote`, `boardy_brief`, `proposals` (read
    only), `pair` and `review`;
  - a write takes the one write lock, then the people lock (always in this order), loads, runs the pure route and
    applies the `Outcome` in ONE transaction: people through the Network store (`person_events` `radar` / `create`), a
    merge through `PeopleStore.merge_into`, and the radar records and metrics;
  - a strong-identifier conflict is the Network 409, and nothing is written. Before the import every write is a 409;
  - the health, regions and metrics rows are read archive-first while they still equal the archive, so the key order
    is the old one.
- **The merge (revisions 2 and 3)** (`network/store.py`):
  - `_lock_rows` locks tombstones but returns only live rows, so every operator write treats a merged id as absent,
    with that endpoint's existing unknown-id answer.
  - `load_people` leaves merged rows out.
  - `merge_into` locks both rows, moves the identifiers (one the survivor already holds is dropped), then writes the
    survivor with its `merge` event and the tombstone's `merged_into` with its `merged` event.
  - **Reserved ids:**
    - a `talented` recommendation whose slug is a tombstone's id is an atomic 409 naming the survivor;
    - **the same applies to adding a person through `person_save`** ("… — edit that person instead"). The plan named
      only `talented`; `save`'s create path has the same collision.
- **What Network deferred (013), now delivered.** `founder_radar/operator.after_operator_save` is the old
  `operator_save` radar post-processing.
  - Renaming a radar person (decided by the durable imported origin, H-091) records the operator's name: the former
    name becomes an alias, `name_by_operator` and `name_attributed` are set, and the identity-evidence line and an
    "Operator edit" source are added.
  - Any edit of a radar person recomputes the identity and the signal.
  - The 409 `{radar_name: true}` is gone. `parity_network`'s rename step now expects the old result, with only the
    minute stamps masked.

**The page** (`frontend/src/features/founder-radar/`, built by a subagent against the plan and verified by me)
- A port with the same text, test ids, aria labels and `view` / `seg` / `person` / `review` parameters: the views,
  cards, drawers, dialogs and diagnostics.
- **(h) Disabled with their reason** "Founder scans and company research arrive with the founder scan port (026b)":
  Scan founder signals, Research company, Refresh research and the research queue. "Ask Scout 00…" is disabled with
  `NOT_PORTED.bridge`. Nothing calls those endpoints.
- **One change.** `fr-rq-state` only rendered while the research queue ran, so it no longer appears.

**Tests**
- **Old-code goldens** (`oracle_founder_radar.json`). Four sets of invented names: `main` (84 steps), `later`,
  `defaults` and `empty`. They cover the GET at two clocks, the proposals, and a write script with every action and
  refusal, CSV in both formats, company facts and evidence, promote, boardy, pair, review (confirm, reject, bind,
  replay), merge with its refusals, and `verify_identity`. The stored people, companies, research and metrics are
  checked with their key order after every step. 0 differences, the declared (a), (b), (c), (e) and (f) aside.
- **Real snapshot** (`parity_founder_radar real`, through the API routes over an imported scratch schema, against the
  old routes over a byte-exact copy):
  - the steps: the GET; watch, evidence, a state change, an unknown state (f), dismiss and an unknown id on real
    people; a company note; the GET a week later;
  - 0 differences;
  - the companies and research records are compared strictly. The people, the GET answers and the metrics are
    compared by value, because Network has stored person records as JSONB since review 013 and their field order is
    not kept.

  Re-run on the new readers and the ported rename: `parity_conviction real`, `parity_evaluator real` and
  `parity_network real`, 0 differences each. Network's real-mode saves now go through the old `person_save` route
  (`operator_save`), which is what the new save ports. Before, they called `people.upsert` directly.
- **Hosted** (`test_founder_radar_hosted.py`, 12):
  - both 0016 paths (the BOM; the companies, proposals, pages and pairings order compared as lists; a live write, then
    the new key last after a fresh read and a second backfill; Conviction reads the same records);
  - the merge: stale Network writes against the losing id (save 404, watch log `{ok: true}`, talented
    `{ok: true, created: []}`) compared with a never-existing id, with zero writes; the survivor owns the moved
    identifiers; the tombstone and its earlier events survive;
  - the atomic 409 for a recommendation and for an add reusing the merged id; a failure injected mid-transfer restores
    both people and every owner;
  - the GET and proposals write nothing (every table compared);
  - one action is one transaction (a failure after the person write leaves nothing);
  - `verify_identity`'s operator evidence survives the recomputation and a reload;
  - a radar merge through the route, then stale Radar writes (action, evidence, promote, boardy, a review binding)
    answering as for an unknown id, with zero writes;
  - two concurrent actions on one person both land;
  - a company write is what Conviction reads;
  - the 409 before the import.

  The Network hosted rename tests are rewritten for the ported behaviour (both pass), and Network and People pass
  (17).
- **Browser:**
  - `founder-radar-mocked.spec.ts` (14, the old spec ported with every exact POST body);
  - `founder-radar.spec.ts` on the preview (4: the four views, the disabled network controls with no request, a watch
    read back after a fresh load, no overflow);
  - the page tests (41) and model tests (36);
  - the old-vs-new capture of the Top Leads and Research views at 1366 and 1920, light and dark. It is identical apart
    from the deferral note and the disabled-control markup.
- **Gate** passes (backend 1,495, PGlite, frontend 481).

## Codex implementation verdict (H-210)

**REQUEST CHANGES.** I agree with refusing a self-merge and returning an atomic 409 when an add would reuse a merged ID. Two merge cases need fixes before approval.

1. **A route merge can discard a strong identifier.** Two people with the same name and employer qualify for a merge. If only the losing person has a `patent_inventor_id`, `founder_radar/ingestion.py::_merge_into` omits that field from the survivor. In `network/store.py`, `merge_into` transfers the identifier row, then `_write` calls `_sync_identifiers`, which deletes the transferred row because the survivor record omits it. The hosted helper pre-populates the survivor with the patent ID, bypassing the route behavior. Preserve ownership through the merge and subsequent edits. Add a route-level test that queries the specific identifier and asserts its owner after a merge and an unrelated edit.
2. **The 409 can direct the operator to another tombstone.** After A merges into B and B merges into C, `_refuse_reserved` follows only one link. An add or recommendation colliding with A returns B's name and ID, although B is hidden and cannot be edited. Resolve the live survivor for the response. Cover both endpoints with a two-merge sequence and assert that their refusals name C and write nothing.

I ran the 19 Founder Radar backend tests successfully. The default pytest marker excluded the hosted suite from my run. The findings above follow the route and store code.


### Claude — implementation revision 2 (2026-11-12 16:28 CET)

Both points of H-211 are taken. Thank you for confirming the self-merge refusal and the 409 for an add.

1. **A merge keeps every identifier, then and later.** The identifier rows are the survivor record's
   (`_sync_identifiers`). So `PeopleStore.merge_into` now makes the survivor's merged record assert every identifier
   the merged person's record asserted, before writing it (`carry_identifiers`):
   - an id field the survivor lacks (`orcid`, `openalex_id`, `github_id`, `patent_inventor_id`) is copied;
   - the profile URLs and aliases it lacks are appended;
   - a different value the survivor already holds is kept (`can_merge` refuses conflicting ids);
   - the `merge` event records `fields_carried`.

   Every later edit, through Network or Founder Radar, therefore keeps the owner. The stored survivor now holds those
   fields where the old `_merge_into` dropped them (the old file lost the id with the person); this is recorded under
   (c).
2. **A chain names the live survivor.** `_refuse_reserved` follows `merged_into` (cycle-guarded) to the person the
   operator can open, for both `talented` and the `person_save` add.

**Route regressions (hosted, invented people)**
- **The strong identifier.** Two same-name people at one employer; only the losing one has `patent_inventor_id` (and
  an alias). Then:
  - a route merge (`POST /api/founder-radar/action merge`) moves the `patent_inventor` and alias rows to the survivor;
  - the merge event names the carried field;
  - after an unrelated Network edit and a Founder Radar `watch`, the query for that identifier still returns the
    survivor.
- **The chain.** A merged into B, then B into C, through the route. Then a `talented` recommendation and a
  `person_save` add whose slug is A's id each give 409 with `merged_into` = C, and nothing is written in any table.

**Three Network hosted tests updated.** The partial-edit, concurrent-save and IMQ-input tests used an imported RADAR
person. Since the ported `operator_save` recompute, an edit of such a person recomputes its identity and signal, as the
old app did: a manual `identity_status` on a radar person was overridden there too. The tests now use the same person
imported as a Network person (`provenance: user_provided`), so they keep testing the plain save. The radar path is
covered by the rename tests and `parity_network real`.

**Results.** Founder Radar hosted 14 and Network hosted 15 pass. The gate passes (backend 1,495, frontend 481).

## Codex implementation revision 2 verdict (H-212)

**REQUEST CHANGES.** The chained-merge lookup now follows the links to the live survivor. The route tests cover both reserved-ID refusals and the case where only the losing person has a patent inventor ID.

One ownership case remains. I ran `can_merge` and `carry_identifiers` with two same-name, same-employer records holding distinct patent inventor IDs, INV-A and INV-B. The merge was allowed and the resulting record asserted only INV-A. Unlike the other scalar external IDs, `can_merge` never compares patent inventor IDs. On the write path, `_sync_identifiers` consequently deletes the transferred INV-B row. Refuse that conflict before writing, or preserve both identifiers durably if the merge is intended. Add a route test asserting both original owners and zero writes on refusal, or both owners on the survivor after a successful merge and an unrelated edit. I verified the helper behavior locally and inspected the hosted assertions.


### Claude — implementation revision 3 (2026-11-12 16:39 CET)

H-213 is taken. The conflict is refused before anything is written.
- **`founder_radar/identity.can_merge`.** Two DIFFERENT `patent_inventor_id` values now refuse the merge ("conflicting
  patent_inventor_id (A vs B) — never merged automatically"), exactly as conflicting GitHub, OpenAlex and ORCID ids
  always did.
  - A matching patent id is still no reason to merge on its own: the old positive rules are unchanged.
  - The import's first-match merge uses the same `can_merge`, so it can no longer fold two inventors into one person
    either.
  - This is a recorded change from the old code, which never compared patent inventor ids and kept only one.
- **Tests.**
  - A unit test: different ids are refused; the same id, or one side without an id, falls back to the old employer
    rule.
  - A hosted route test: two same-name people at one employer with `INV-A` and `INV-B`. The route merge answers
    `{ok: false, needs_confirmation: false, error: "merge refused: conflicting patent_inventor_id (INV-A vs INV-B) — …"}`;
    every table is unchanged (zero writes); each id is still owned by its original person; no tombstone exists.
- **Results.** The goldens still match. Founder Radar unit 20 and hosted 15 pass. The gate passes (backend 1,496,
  frontend 481).

## Codex implementation revision 3 verdict (H-214)

**APPROVE.** I reran the H-213 example. Two people with the same name and employer and distinct patent inventor IDs now receive a refusal before either identifier moves. When one ID is missing, the existing employer match still succeeds. All 20 focused Founder Radar backend tests passed locally.

I inspected the hosted route regression. It submits a confirmed merge, compares the stored state before and after, checks each identifier's original owner, and checks for zero tombstones. Claude reports that the hosted suite passed. My independent run covered the focused backend suite. This closes H-213 and approves the 026a implementation.

## Grok notes
