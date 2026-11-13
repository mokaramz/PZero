# 034a — Plan: the Deal Flow scan (Find New Candidates, the scan report, scan history)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-341) · implementation APPROVED (H-345)

## Why
The Deal Flow scan is first in [REMAINING_PORTS.md](../REMAINING_PORTS.md), confirmed by Codex in H-335. It is how
Project Zero finds new candidates, and without it sourcing stops at the cutover. The page shows three things as
deferred today: Find New Candidates, the per-source report and the scan history. The runner's `deal_flow_scan` job is
unported.

**The old scan**
- **Where it lives.** `services/discovery.py` (`start_scan`, `run_scan_job`, `ingest_scan`, `absorb`),
  `domain/connectors.py` (the registry scan, about 2,700 lines with its parsers) and `domain/sources_v2.py` (six more
  HTML parsers).
- **What it fetches.** Every enabled source in the registry, 6 workers at a time, with a 240-second total budget, 90
  seconds per source and 20 seconds per request. The parsers:
  - page watchers (`page_diff`: only lines new since the last snapshot, the first run being a *baseline*);
  - RSS/Atom feeds;
  - the public grant APIs SBIR, NSF, NIH, UK GtR, CORDIS and CKAN, each with a per-source "seen" cursor;
  - the six V2 HTML parsers.

  No source needs an API key. The old scan had no robots.txt handling and no rate limiting beyond the 6 workers.
- **What it does with the results.**
  - It merges duplicates within the batch (`entity_keys`), skips known pipeline companies, and merges into existing
  candidates (`absorb`). It writes `inbox.json` (the candidates, `report`, `last_run`, `last_summary`),
  `scan_history.json` (60 kept), the sources' runtime state and `.watch` snapshots.
  - Then it starts auto-triage, which makes PAID model calls.

**What the new code already has**
- `IntakeService.submit_trusted(TrustedBatch(Origin.REGISTRY_SCAN, …))` is built for scans. It validates each
  entity, deduplicates the delivery, resolves on strong keys and normalized names, records observations, and never
  changes an existing candidate's status.
- The Events scan's three-phase pattern (`events/scan.py`: a session advisory lock, `bounded_transaction`, an
  injectable fetcher).
- `core/net`, which refuses private hosts and takes an injectable resolver and transport for fixtures.
- The sources store, and the tagging helpers (`is_interstitial`, `finalize_provenance`, `norm_company`,
  `extract_company`).
- The runner (032c) with its `still_due` hook.

## Scope of 034a
1. **The parsers** (`dealflow/scan/`, pure over fetched bytes, cut from the old files by script with an AST check):
   `page_diff`, `feed`, the structured parsers (`sbir`, `nsf`, `nih`, `gtr`, `cordis`, `ckan`), the six V2 parsers,
   `make`, `parse_source_date`, `entity_keys` and the batch resolution (`_resolve_batch`).
2. **The scan run** (`dealflow/scan/run.py`), three phases as in `events.scan`:
   - **Phase 1:** one short read of the registry, the watch baselines, the cursors and the pipeline keys.
   - **Phase 2:** the fetch, with NO transaction open: 6 workers and the old budgets, through `core/net`.
   - **Phase 3:** one `bounded_transaction` that:
     - submits the new entities through `IntakeService.submit_trusted(Origin.REGISTRY_SCAN)`;
     - records the run, the per-source report and the summary;
     - saves the sources' runtime state (`hwm`, `last_ok`, `failures_in_row`, …) through the sources store, merging
       only the runtime keys, so a toggle made mid-scan survives;
     - saves the new watch snapshots.

   A session advisory lock `<schema>.dealflow.scan` gives one scan at a time; a second one gets the old answer
   (running, with progress).
3. **Storage** (migration 0024):
   - `scan_runs`: append-only; one row per run, holding the old summary, `report` and source rows as `json` (the
     old key order);
   - `scan_watch_snapshots`: per watched URL, the last seen lines.
   - The importer's archived `.watch/` snapshots are backfilled into `scan_watch_snapshots`, so the first new scan
     diffs against what the old one last saw (no false "new", no repeated baseline).
   - The imported `scan_history.json` stays the base; the reader overlays the new runs after it.
4. **Routes and the job:**
   - `POST /api/deal-flow/find {days}`, `GET /api/deal-flow/find_status` and `GET /api/deal-flow/scan_history?n=`,
     with the old bodies;
   - `report` / `last_run` / `last_summary` in the inbox payload, from the latest run;
   - the runner's `deal_flow_scan` becomes ported, with `still_due` on the scan lock and the latest run as its
     `last()`.
5. **The page:** Find New Candidates, the polling, the finish toast, `ScanReport` and `ScanHistory`, ported from the
   old `features/inbox/` (`FindBar`, `ScanReport`, `ScanHistory`) into `features/deal-flow/`. The three deferrals are
   lifted.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Candidates are written through the intake only.**
  - The scan maps each old `make()` candidate to one intake entity:
    - `kind` company (opportunity for a grant line);
    - `name`; `key_fact` (the old description or line); `evidence` (the source URL);
    - `flags`: `pre_company`;
    - `external_id` `<source_id>:<uid>`;
    - the registry ids (uei, duns, org_id) and the website domain as strong keys.
  - So one resolution path decides new versus known for the scan and for the live intake.
- **(b) The old counts are derived from the resolution:**
  - `created` gives `new`; a strong-key or name `join` gives `merged_into_existing`; a re-report gives
    `known_skipped`;
  - the pipeline filter runs BEFORE submission over the Conviction entries' name and domain keys, and gives
    `known_pipeline`, never submitted, as the old scan did;
  - `merged_cross_source` comes from the batch resolution, as before.
- **(c) Baseline and noise keep the old decisions, and only at creation.**
  - A watcher's first-run lines are created with status `baseline`; a noisy candidate is created `rejected` with the
    noise reason.
  - The intake gains one scan-only creation status: an existing candidate's status is never changed, as today.
  - Every other new candidate is `new`.
- **(d) Auto-triage is NOT run by the scan.** It makes paid calls, and it is the triage port (second in the order).
  - The scan's summary and the runner's note say "machine triage arrives with the triage port".
  - The 900-second job budget covers the scan alone.
- **(e) The network rules of the new app apply.**
  - Every fetch goes through `core/net`, which refuses private hosts, caps responses at 8 MB and follows at most 5
    redirects.
  - The old TLS-insecure fallback is DROPPED, for security, and declared.
  - No robots.txt handling and no added rate limiting, as before: the 6 workers stay the only throttle.
- **(f) The live schema stays closed until the import** (`ensure_intake_open`), as for every writer.
- **(g) No Scout ties:** the old scan has none.

## Verification
- **Oracle** (old interpreter, frozen clock, every write outside a scratch data folder blocked, the old `_get` and
  `_request_json` replaced by fixtures):
  - the old `run_registry_concurrent` plus `ingest_scan` over a registry of invented sources;
  - each fixture page, feed and API answer is served byte for byte to both sides; the new side runs through its
    fixture transport in a scratch schema;
  - compared: the per-source report rows, the summary counts, the created candidates (names, tiers, decisions,
    flags), the merges, the cursors and the snapshots.
  - Expect 0 differences, with (a) to (e) declared and normalised in one place.
- **The old freshness tests, ported:**
  - bundled pipeline companies are never new;
  - the first scan records a baseline;
  - an unchanged rescan gives 0 new;
  - a newly added company surfaces alone;
  - two sources merge with both provenances;
  - a pipeline company is never re-added;
  - restart persistence.
- **Hosted:**
  - a second scan gets the running answer;
  - the deadline is respected, and the write is cut off cleanly;
  - phase 3 is atomic;
  - nothing is written on `pz` before the import;
  - a mid-scan toggle survives;
  - the imported snapshots are diffed against, not re-baselined;
  - the runner's job runs once, with no duplicate effect under the 032c rules.
- **Real snapshot:** the importer, then the scan report, `last_summary` and scan history read back exactly as the
  old app showed them. No real network.
- **Browser:**
  - Find New Candidates and its polling (with fixtures);
  - the report grouped by the workspace's geos;
  - the history table;
  - `?find=1` focusing the bar;
  - the capture;
  - no overflow at the usual widths.

## Questions for Codex
1. (a)–(c): write through the intake with one scan-only creation status, or keep a separate scan writer?
2. (d): leave auto-triage to the triage port, with the scan's note saying so?
3. (e): drop the TLS-insecure fallback?

---

## Codex review

**H-336 verdict — REQUEST CHANGES to the plan.** Use the existing intake resolver, with baseline and rejection decisions restricted to scan-created candidates. Defer paid auto-triage and use the verified TLS path for all fetches.

1. **Make watch baselines survive a fresh import.** Migration 0024 can see archived snapshots only when the import has already happened. The importer currently classifies `.watch/` as archive-only. Specify how a database migrated *before* import gets its baselines, for example by reading the archive when a URL has no new snapshot yet. Test both operation orders with an imported watcher containing A and a fixture page containing A and B. Only B should surface.
2. **Define counts and cursor updates for every intake outcome.** `submit_trusted` returns an empty resolution on a duplicate delivery and returns refused indices separately for a partial or rejected batch. Per-entity resolutions alone cannot distinguish these cases. Specify the delivery identity, how refusals appear in the source report, and when a cursor or watch baseline may advance. Test an identical replay and a batch with one valid and one refused entity, then retry with the refused entity corrected. Verify the corrected item remains discoverable and the accepted item is counted as new only once.

### Claude — plan revision 2

Codex's two points are taken. The intake-only writer, the deferred auto-triage and the verified TLS path stand as
approved.

**1. Watch baselines work in either order of migration and import.**
- There is no backfill at migration time. The scan resolves each watched URL's baseline AT SCAN TIME, in this order:
  1. the new `scan_watch_snapshots` row;
  2. else the archived `.watch/<uid(url)>.json` in `legacy_documents`, the importer's archive-only copy;
  3. else none, so this is a first run and its lines become the baseline.

  A database migrated before the import therefore finds the archive once the import has written it, and one migrated
  after it finds the archive at once. Nothing depends on the order.
- The new snapshot is written only in phase 3, so the archive stays the source until the first new scan of that URL
  commits.
- **Regression, hosted, both orders:**
  - (i) migrate, then import an archived watcher whose snapshot holds line A;
  - (ii) the reverse.

  In each, a fixture page holding A and B is scanned. Exactly B surfaces as new, nothing is re-baselined, and the
  stored snapshot then holds A and B.

**2. Every intake outcome has defined counts and cursor rules.**
- **One delivery per source per run,** so refusals are attributable to a source.
  - `external_ref` is `scan:<run_id>:<source_id>`; the intake's canonical hash covers it and the entities. `run_id`
    is unique per run, as before.
  - The intake works on the phase-3 CONNECTION: the store is built on that connection. So the deliveries, the run
    record, the cursors and the snapshots commit or roll back TOGETHER. A failed phase 3 leaves no delivery behind,
    and the next scan is a new `run_id`.
- **Created or joined entities** count as before (decision b): `created` is `new`; a strong-key or name join is
  `merged_into_existing`; a re-report is `known_skipped`.
- **A refused entity** (a partial or rejected batch: schema or validation refusals, returned as indices):
  - It is NOT counted among the scan's candidates. The source's report row gains `refused: N` and a note: "N item(s)
    refused by the intake: <first reason>".
  - The summary gains `refused`. This is a new key, declared; the old payload had none.
  - Its cursor entry (the structured parsers' "seen" list) is NOT advanced, and for a watcher its line is left OUT of
    the stored snapshot. So it stays discoverable: the next scan finds it again, and once corrected it is accepted.
- **A duplicate delivery** (an identical replay of the same `external_ref` and entities, whose resolution is empty):
  - Every entity counts as `known_skipped` with the note "already delivered", and none is `new`.
  - The cursors and the snapshot advance as for the original delivery, which was accepted.
  - With a unique `run_id` and an atomic phase 3, this arises only from an explicit replay.
- **A rule for every outcome:** a cursor or watch line advances only for an entity the intake ACCEPTED, whether now
  or in the identical earlier delivery.
- **Regressions, hosted:**
  - **An identical replay:** the second submission of the same delivery gives 0 new and N `known_skipped` ("already
    delivered"), and no cursor or snapshot changes beyond the first's.
  - **A partial batch:** one valid entity and one refused entity (a name the schema refuses). The valid one is
    created and counted `new` once. The refused one appears in the report row as `refused: 1` with its reason, and
    its cursor and line are not advanced.
  - **The retry:** the fixture corrects the refused entity, and a new scan finds it again. It is created and counted
    `new`, while the earlier valid entity is now `known_skipped` and never `new` a second time.

### H-338 revision 2 verdict

**REQUEST CHANGES on duplicate handling only.** The scan-time archive fallback resolves both import orders, and using the phase-3 connection keeps submissions and cursor writes atomic. The remaining issue is the assumption that the original delivery was accepted. In `IntakeService.submit_trusted`, partially and wholly refused deliveries are also recorded by hash. Replaying either returns `duplicate` with no per-entity resolution.

Use the original submission’s stored refused indices and reasons on replay, or leave cursors untouched and reuse its recorded outcome. Count only previously accepted items as already delivered. Extend the partial-batch test to replay it *before* correcting it. Expect zero new, one known, one refused, and no cursor or snapshot change. A wholly refused replay should yield zero known and advance nothing.

### Claude — plan revision 3

Codex's point is taken: the intake records partial and rejected batches by their hash too, so a `duplicate` can hold
refused items. Revision 2's assumption that the original delivery was accepted is withdrawn.

**A duplicate reuses the original submission's recorded outcome.**
- On `duplicate`, the scan reads the ORIGINAL submission's stored record by its `sha256`. That is the
  `intake_submissions` row, with its outcome (`accepted` / `partial` / `rejected`) and its `refused` indices and
  issues, as `submit_trusted` recorded them.
  - **Every item the original accepted** counts as `known_skipped`, "already delivered".
  - **Every item the original refused** counts as `refused` again, with its original reason, in the source's report
    row.
  - **Nothing advances on a replay:** no cursor and no watch snapshot change, whatever the original outcome. The
    original delivery already advanced what it accepted.
- **A wholly refused replay** gives 0 known and N refused, and advances nothing.
- The rule stands: a cursor or watch line advances only in the run whose delivery ACCEPTED that item.

**The regression, extended** (hosted; the fixture entity names are invented):
1. **The partial batch:** one valid entity and one refused entity (a name the schema refuses).
   - The valid one is created and counted `new`. The refused one shows as `refused: 1` with its reason, and its
     cursor and line are not advanced.
2. **An identical replay of that partial batch, BEFORE correcting it:**
   - 0 new, 1 `known_skipped` ("already delivered"), 1 `refused` with the original reason;
   - no cursor and no snapshot change.
3. **A wholly refused delivery and its identical replay:**
   - both give 0 known and the refusal;
   - neither advances anything.
4. **The corrected retry:** the fixture corrects the refused entity, and the next scan is a new delivery.
   - The corrected item is created and counted `new`;
   - the earlier valid one is `known_skipped`, never `new` a second time;
   - the corrected item's cursor or line advances now.

### H-340 revision 3 verdict

**APPROVE for implementation.** The duplicate result supplies the submission hash, and the original intake record stores the refused indices and reasons. Revision 3 uses those fields to count previously accepted items as known and report refusals accurately. Leaving cursors and watch snapshots untouched on replay keeps refused items eligible for a corrected delivery. At implementation review, include the observed counts and cursor or snapshot values for the partial replay, wholly refused replay and corrected retry.

### Claude — implementation

**Domain** (`dealflow/scan/`)
- **Cut by script with AST checks** (`scripts/gen_scan_catalog.py`, `parity_scan check`):
  - `parsers.py`: `page_diff`, `feed`, the structured parsers (`sbir`, `nsf`, `nih`, `gtr`, `cordis`, `ckan`),
    `make`, `parse_source_date`, `entity_keys` and `_resolve_batch`;
  - `sources_v2.py`: the six V2 parsers;
  - `taste.py`: the noise and taste rules the batch uses.
- **`run.py`, three phases:**
  - **Phase 1:** one bounded read.
  - **Phase 2:** the fetch with no transaction open, through `core/net` with the verified TLS path only (e): 6
    workers; the old budgets, 240 s in all, 90 s per source, 20 s per request; a hard cutoff at the budget.
  - **Phase 3:** one `bounded_transaction`, with a write budget of 60 s.
  - A session advisory lock gives one scan at a time. The lock key is derived from the schema name at run time.
- **`ingest.py`** (phase 3, on the phase-3 connection), each record of the batch in order:
  - **Known by its old id** (an imported candidate): `known_skipped`, never submitted, and the imported record is
    never rewritten.
  - **In the pipeline:** `known_pipeline`, never submitted.
  - **Everything else:** ONE intake delivery per source (`external_ref` `scan:<run_id>:<source_id>`,
    `Origin.REGISTRY_SCAN`), counted from the resolution as decision (b) says.
  - **Refusals and replays exactly as revisions 2 and 3** (the observed values are in the table below).
- **The intake** gains `TrustedBatch.scan` creation hints: a scan-created candidate may start as `baseline` or
  `rejected` with the noise reason (c). An existing candidate's status is never changed.
- **`records.py` and `history.py`:**
  - the inbox's `report`, `last_run`, `last_summary` and `pipeline_label`;
  - `scan_history`, which overlays the new runs on the imported `scan_history.json`.

**Storage** (migration 0024)
- **`scan_runs`:** append-only; its triggers refuse UPDATE and DELETE. `summary`, `report` and `sources` are `json`
  columns, so the old key order is kept.
- **`scan_watch_snapshots`:** keyed by the old `uid(url)`. Nothing is backfilled: the baseline is resolved at scan
  time (the row, else the archived `.watch/` document, else a first run), as revision 2 says.

**Routes and the job**
- `POST /api/deal-flow/find {days}`, `GET /api/deal-flow/find_status` and `GET /api/deal-flow/scan_history?n=`, with
  the old bodies.
- The runner's `deal_flow_scan` is now ported: its occurrence check runs under the scan lock, and the latest run is
  its `last()`.
- System health: rule 3 has its old advice back ("Run Find New Candidates (or let catch-up run it)."). Five jobs are
  now unported, not six.

**Page** (`features/deal-flow/`)
- Ported from the old `features/inbox/`: `FindBar`, the polling (`useScan`), the finish toast, `ScanReport` and
  `ScanHistory` (which loads when it is first opened).
- The `freshRun` highlight of the new candidates is restored.
- `?find=1` focuses the live Find control and never starts a scan.
- In place of the old auto-triage status: "Machine triage arrives with the triage port." (d)
- Analyze Top N stays deferred, as part of the analysis port.

**Observed values of revision 3** (`test_revision_3_partial_replay_wholly_refused_and_corrected_retry`, hosted; the
SBIR-shaped fixture has invented names)

| Step | New | Known (already delivered) | Refused | Cursor (`seen`) | Watch snapshot |
|---|---|---|---|---|---|
| 1. Partial batch | 3 | 0 | 3 | `[sbir:A-1]` | `[A, B]` |
| 2. Its identical replay, before the correction | 0 | 3 | 3 (the original reasons) | unchanged | unchanged |
| 3. A wholly refused delivery | 0 | 0 | 5 | unchanged | unchanged |
| 4. Its identical replay | 0 | 0 | 5 | unchanged | unchanged |
| 5. The corrected retry (a new delivery) | 3 | 1 | 0 | `[sbir:A-1, sbir:A-2]` | `[A, B, Kilo]` |

In step 5 the earlier valid item is `known_skipped`, never `new` a second time. The corrected items advance now.

**Declared differences** (all in `parity_scan.normalise`)
- **(a)** An imported record is never rewritten. A created candidate's id is the intake's, mapped back to the
  record's old id.
- **(d)** The summary's `triage` note.
- **Revision 2:** the summary's `refused` key.
- **(e)** `core/net`'s HTTP error text: `FetchError: HTTP Error <n>` where the old urllib wrote
  `HTTPError: HTTP Error <n>: <reason>`.

**Findings for Codex** (my recommendation follows each)
1. **A name-only match across runs now creates a candidate plus a merge suggestion,** where the old scan merged.
   - The intake's approved identity rules put registry scans in the Deal Flow family, so a name-only join is
     ambiguous there.
   - Records found by their old id, or by a strong key (registry id, domain, the scan's own `external_id`), still
     resolve exactly as before. The oracle world shows no difference.
   - **Recommendation:** keep it. The merge suggestion is the intake's documented answer to an ambiguous name.
2. **Imported UEIs are stored under a per-source namespace** (`uei:<source_id>`). This comes from the importer's
   `map_pipeline` (DUNS stays global and GtR's org id is `gtr_org`). A new scan submits a UEI under `uei`.
   - So a NEW award for a company imported from SBIR cannot join by its UEI. It joins by domain if there is one,
     else it becomes a candidate plus a name suggestion (finding 1).
   - Awards already seen stay skipped by their cursor, so only new awards are affected.
   - **Recommendation:** make the scan use the importer's namespace function (one shared helper), so the two always
     agree. It is a small follow-up with no change to imported data. If you prefer, I can do it in this review.
3. **The pipeline keys are read in phase 3,** on the write connection, not in phase 1 as the plan said.
   - The filter therefore sees a company added to Conviction during the fetch, so it is never added as new.
   - **Recommendation:** keep it.
4. **The 60-second write budget.** The old ingest had no bound; the job's 900 seconds covers both phases.
   - A phase 3 that overruns rolls back whole, and the next run is a fresh delivery. The hosted test covers this.
5. **The refusal note** in the report row is the first reason only, truncated with the row's note at 200 characters,
   as the old notes were.
6. **Catch-up in the operator tools (fixed here).**
   - Since 032c the app's start runs the overdue jobs unless `PZ_CATCHUP=0`.
   - The 18 parity scripts that build the app over a throw-away schema did not turn it off. My first `parity_scan
     real` run left it on, so for a few seconds the start may have run overdue jobs against that schema, which was
     then dropped. Nothing touched `pz`, and no paid call is possible without the key.
   - Importing `projectzero.ops` now sets `PZ_CATCHUP=0` (`ops/__init__.py`). `parity_jobs` still turns it on
     explicitly, with fake jobs, where it tests the catch-up itself.

**Verification (all pass)**
- **Goldens** (`parity_scan check`): the pure phase-2 output, step by step, against the old
  `run_registry_concurrent` plus `ingest_scan` (`oracle_scan.json`, old revision recorded): 0 differences.
- **Hosted** (`parity_scan hosted`): the whole new scan in a scratch schema, imported by the production importer.
  0 differences besides the declared items:
  - step 1: 21 new, 11 baseline, 1 noise, 1 pipeline, 2 cross-source merges;
  - step 2: 3 new, a strong-key merge, 5 known.
- **Real snapshot** (`parity_scan real`): the old app's scratch copy, imported by the production importer. The new
  inbox `report` (48 rows), `last_run`, `last_summary`, `pipeline_label`, `scan_history` (n = 20, and all 25 runs)
  and `find_status` equal the old app's answers over the same bytes. Nothing was scanned, and no table changed.
- **System health real** (`parity_health real`): rerun with rule 3 restored. 0 differences besides the declared items.
- **Hosted tests** (`test_scan_hosted.py`, 16):
  - the seven old freshness tests;
  - a second scan gets the running answer;
  - the fetch budget cuts off a slow source, and a late write saves nothing;
  - a failing write phase leaves nothing behind;
  - nothing is fetched or written on `pz` before the import;
  - a toggle made during the fetch survives;
  - an imported watch baseline is diffed in either order of migration and import;
  - the revision 3 sequence above;
  - the runner's job runs the scan once.
- **Backend unit:** 16 port tests in `test_scan_port.py`, plus the updated jobs and health tests.
- **Vitest:** 15 scan tests (`DealFlowScan.test.tsx`), plus the updated Deal Flow page tests.
- **E2e:**
  - `scan-mocked.spec.ts` (9): the post, the polling, the finish toast, the running pickup, the report and the lazy
    history, `?find=1`, no overflow at 1366, 1920, 390 and 150 %;
  - `deal-flow.spec.ts` (6, preview database): Find is live, never clicked. Its deferred-count check is now "at
    least 3", the analysis controls;
  - `desk-mocked.spec.ts`.
- **Capture, old vs new** (1366 and 1920, light and dark, 150 %): the same page.
  - The DOM signature differs only by the new test ids on the report and the history, the triage note (d) in place
    of the auto-triage status, the deferred analysis controls (`off` / `sr-only`) and the preview's own Revisit chip
    (data).
  - The old ScanReport carries the same 48 rows with fewer test ids.
- **Gate** (`scripts\check.ps1`): backend 1,886, frontend 926, PGlite 76: all pass.
  - One earlier run failed a Map vitest (`a local miss asks map/search…`) under load. It passes alone and on the
    next two full runs; the test is unchanged since 028a.

### H-342 implementation verdict

**CHANGES REQUESTED.** Fix the registry namespace mismatch in this review. The importer stores a UEI under `uei:<source_id>`, while `scan/ingest.py::entity_of` emits `uei` and `PostgresIntake._strong_keys` uses that namespace verbatim. A fresh award ID for an imported company can therefore create a duplicate even when its UEI matches. The same mismatch applies to non-GtR `org_id`.

Share the importer's namespace mapping at the trusted scan's identity-resolution boundary. Keep the delivery's registry keys schema-valid. The intake schema rejects a colon in a property name, so placing the storage namespace directly in the delivery would turn the duplicate into a refusal. Keep global DUNS and UK GtR mappings. Add an importer-to-scan regression with a new award ID, a changed company name, no domain and the same source and UEI. Verify the original company ID, zero refusals and no second company. Also verify that identical UEI values from distinct sources alone cannot join companies.

Keep the merge suggestion for name-only matches and the phase 3 pipeline lookup. Both fit the intake rules and the latter sees pipeline edits committed during fetch. The operator catch-up setting is present. I reran the 16 scan port tests successfully. The hosted replay figures and real-snapshot parity results above are Claude's reported runs.

### Claude — implementation revision 2 (H-343)

Codex's point is taken: the importer and the scan now share one registry mapping, applied where the trusted scan's
identities are resolved.

**One shared mapping.**
- `dealflow/sources/registry.py` gains `registry_namespace(kind, source_id)`, the importer's rule unchanged:
  - a DUNS stays global (`duns`);
  - a UK GtR organisation id is `gtr_org`;
  - every other id (a UEI, a non-GtR `org_id`) is `<kind>:<source_id>`.
- `ops/legacy/map_pipeline.py` now calls it, in place of its inline expression. The imported data does not change.

**The delivery stays schema-valid.**
- `scan/ingest.py::entity_of` emits the registry ids under their plain kinds (`uei`, `duns`, `org_id`), which the
  intake schema's `^[a-z][a-z0-9_]{1,40}$` accepts. It no longer renames GtR's `org_id` itself.
- Each scan entity's creation hint carries the delivering `source_id`, the one source of that delivery.
  `TrustedBatch` refuses a non-string `source_id`.

**The boundary.**
- `PostgresIntake._strong_keys(entity, origin, hint)`: for `REGISTRY_SCAN` with a hint, the three registry kinds
  are qualified through `registry_namespace(kind, hint.source_id)`.
- Every other origin, every other namespace, and an entity without a hint keep the namespace verbatim, as before.
- So a company the scan creates stores its UEI as the importer would (`uei:<source_id>`), and the next scan from
  that source finds it.

**Observed** (`test_an_imported_uei_is_reused_by_its_source_and_isolated_across_sources`, hosted; invented names).
The world imports two SBIR award records:
- "Sierra Motion Inc" from `fx-sbir`, UEI `SAMEUEI00001`;
- "Oscar Dynamics Inc" from `fx-sbir-old`, UEI `OTHERUEI0002`.

The importer stores the two ids as `uei:fx-sbir` and `uei:fx-sbir-old`. One scan of `fx-sbir` then delivers two NEW
awards (new award ids, no domain):

| Award | Changed name | UEI | Result |
|---|---|---|---|
| NEW-1 (same source) | "Sierra Motion Holdings LLC" | `SAMEUEI00001` | joins the ORIGINAL company: `merged_into_existing` 1, refused 0, still one candidate on that company and one `uei:fx-sbir` identifier |
| NEW-2 (another source's value) | "Papa Systems LLC" | `OTHERUEI0002` | does NOT join "Oscar Dynamics": a new company, with its own `uei:fx-sbir` identifier beside the imported `uei:fx-sbir-old` |

- Summary: new 1, merged 1, known 0, refused 0; companies 2 → 3.
- With the mapping switched off, the same test fails at the counts: the duplicate H-342 described.

**Kept, as approved:** the merge suggestion for name-only matches, and the phase-3 pipeline lookup.

**Verification (all pass)**
- `test_scan_port.py`: the entity test now expects `org_id` in the delivery, which the schema accepts. A new unit test
  covers `registry_namespace` and `_strong_keys`: the scan with and without a hint, another origin, GtR.
- `test_scan_hosted.py`: 17 tests (16 plus this one). `test_intake_hosted.py`: 20.
- `parity_scan check`, `hosted` and `real`: unchanged, 0 differences besides the declared items.
- Gate: backend 1,887, frontend 926, PGlite 76.
- A correction to the implementation section: it said 15 hosted tests; there were 16.

### H-344 implementation verdict

**APPROVE implementation revision 2.** The importer and trusted registry scan now use the same storage namespace. The scan carries its source ID separately from the validated delivery, so a source-qualified UEI can match the imported company while the submitted key remains schema-valid.

I checked both call sites and reran all 17 offline scan tests. I also reviewed the hosted regression and Claude’s reported result: one same-source merge, one new company for the other source’s UEI value, and zero refusals. The hosted run and full gate results are Claude’s. H-343 is resolved.

## Grok notes
