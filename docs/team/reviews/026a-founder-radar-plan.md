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

## Grok notes
