# 037a — Plan: WATCH, part 1 (the store, one trigger reader, the view, pages and acknowledgements)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-377) · implementation APPROVED (H-381)

## Why
Watch sensors are item 3 of [REMAINING_PORTS.md](../REMAINING_PORTS.md). The old feature (`services/watch.py`,
`api/routers/watch.py`) is small, deterministic and calls no model:
- two sensors: scan re-hits (no network) and official-page diffs;
- one append-only trigger log with status lines;
- one targets document;
- one 24-hour job, `watch_checks`.

Its only path to a paid call is indirect: a high-value trigger asks case preparation to refresh a case, and case
preparation is item 4.

Today the new app has only the READ side. The archived trigger log is read by Conviction, Today, Home, Health and
the Map, through two separate loaders (`conviction/inputs.py`, `map/inputs.py`). Five places show WATCH as deferred.

**The real data starts empty:** 0 targets, 0 triggers, 0 page baselines, 1 watched Deal Flow candidate with no extra
source. So parity must come from fixtures.

**I propose two reviews** (the survey's split; no paid call in either):
- **037a (this plan): the store, one trigger reader, the view, saving pages and acknowledging triggers,** with the
  old Watchlist panel and Deal Flow WATCH section. No network.
- **037b: the two sensors through `core/net`:** "Check now", the `watch_checks` job, Health's failing page checks, and
  the news bridge's watch triggers. The case refresh stays deferred until case preparation.

## Scope of 037a
1. **Storage** (migration 0027):
   - **`watch_targets`:** one row per company key (`norm_company(name)`), its old record as `json` (`name`, `urls`,
     `candidate_id`, `active`, `added_at`, `updated_at`, `checks`).
   - **`watch_events`:** append-only (`seq`, `kind` trigger|status, `line json`, and `dedupe_key` UNIQUE where
     `kind = 'trigger'`). UPDATE and DELETE are refused by trigger. 037b's sensors and news bridge will write their
     triggers here; 037a writes only status lines.
2. **ONE trigger reader** (`watch/log.py`): the archived `watch/triggers.jsonl` lines first, then the rows by `seq`,
   parsed by the existing `conviction/operator.watch_triggers` rules (bad lines skipped, the last status line wins).
   - Both loaders (`conviction/inputs.py`, `map/inputs.py`) switch to it, so Conviction, Today, Home, Health and the
     Map read the same overlay.
   - The targets reader: the imported `documents['watch/targets.json']` as the base, overlaid by `watch_targets` rows
     (a row wins).
3. **Routes**, with the old bodies, answers and error texts:
   - `GET /api/watch`: `{companies, labels, note}`, from the old `view()`;
   - `POST /api/watch_target` `{name, urls[], candidate_id?, active?}`;
   - `POST /api/watch_ack` `{id, status: reviewed|dismissed, note?}`.
4. **The page:**
   - **Watchlist:** the old `WatchedCompanies` panel (rows, the "{n} new" badge, the "machine triage predates new
     evidence" badge, "Official pages to watch" with Save pages, the TriggerList with Reviewed and Dismiss);
   - **Deal Flow:** the candidate detail's "On WATCH — sensors" section;
   - **"Check now" stays deferred** until 037b, with ONE wording on both pages: "Page checks arrive with the WATCH
     sensors port.".

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) The watched set: every candidate whose status is `watch`, plus the active targets.**
  - The old app watched only its inbox's `watch` decisions, because Scout had its own monitoring. With Deal Flow and
    Scout Intake merged, the 20 imported Scout planner leads that are MONITORING are `watch` candidates in Deal Flow
    already.
  - So the Watchlist shows the same set Deal Flow shows as WATCH: about 21 companies on the real snapshot, instead of
    the old 1. They have no pages and no extra sources, so in 037b they cost nothing until pages are added.
  - Declared. It is a product choice for Mohamed (made under his standing instruction, and recorded for him). The
    alternative is inbox-origin only, for parity.
- **(b) The writes, each one short transaction:**
  - `watch_target` takes a session-independent advisory transaction lock on `<schema>.watch` (derived at run time),
    re-reads the current row and upserts it. It keeps the old merge rules (first 6 URLs; the old URL regex; `active`
    false only if the body says `false`; it never touches a candidate).
  - `watch_ack` takes the same lock, checks that the trigger exists in the overlay ("no such trigger"), and appends a
    status line. There is no state check, as before: acknowledging twice appends twice.
  - `ensure_intake_open` closes `pz` before the import, as for every writer.
- **(c) The URL check stays the old regex at save.** The private-host refusal happens at fetch in 037b (`core/net`)
  and is recorded as a page failure, as the old fetch did.
- **(d) The view keeps the old details:**
  - `triage_predates_evidence` compares the current proposal's `proposed_at`, rendered in the old
    `%Y-%m-%dT%H:%M:%S` form, with the newest trigger's `first_observed` as strings;
  - `machine_proposal` comes from the current proposal;
  - companies are sorted `(-open, name.lower())`;
  - each company shows its 10 newest triggers.
- **(e) The page keeps the old texts,** including the TriggerList's "page check" for a non-scan trigger. The old
  mislabel of news triggers is kept for parity, declared, and revisited in 037b once news triggers exist.

## Verification
- **Oracle** (old interpreter, frozen `ledger.now_ts`, writes outside a scratch data folder blocked): the old
  `watch.view()`, `set_target` and `acknowledge` over an INVENTED world.
  - **The world:** inbox `watch` candidates, one with `also_seen` sources and a triage proposal; active and inactive
    targets; a triggers log with status lines, a re-acknowledgement and malformed lines.
  - **Compared after each step:** the answers, the log lines and the view.
  - 0 differences, with (a) declared and normalised in one place (the old watched set gains the merged `watch`
    candidates).
- **Hosted:**
  - two concurrent `watch_target` calls on one company lose no update;
  - an ack of an unknown id: "no such trigger", with no row;
  - nothing is written on `pz` before the import;
  - the archive-then-rows overlay is read identically by Conviction, Today, Health and the Map;
  - the `dedupe_key` uniqueness holds against a second insert;
  - no table other than the two watch tables changes.
- **Real snapshot:** the view and every reader of the log read back as before. The only difference is (a)'s watched
  set, with its count reported.
- **Browser:**
  - mocked: the panel, Save pages, Reviewed and Dismiss, the Deal Flow section, no overflow;
  - preview database: Save pages for a watched candidate, read back;
  - the capture of the Watchlist.

## Questions for Codex
1. Is the 037a / 037b split right?
2. (a): watch every `watch` candidate (the merged meaning), rather than inbox-origin only?
3. (b): one advisory lock for both writes, and the old "no state check" on acknowledgement?

## H-374 plan verdict

**REVISE.** I support the store/sensor split, the declared inclusion of Scout leads, and a schema-scoped transaction lock shared by both writers. Repeated acknowledgements can append status events in lock order. Save-time URL parity is reasonable while 037a performs no fetch.

1. Include Health in the target overlay. At `health/inputs.py:98`, Health reads targets directly from the imported document. Its event input already comes through Conviction, but switching that reader alone leaves the active manual target count stale. Specify how Health and the Watchlist use the same watched set. Test a manual company without a candidate through activation and deactivation, and a Scout-only WATCH candidate, comparing both views.
2. Specify the first save for an imported target. Under the lock, merge from the effective record (live row if present, otherwise imported target). Reading only the current row can discard imported checks and creation time. Seed an imported target with both fields, save its pages twice, and verify the retained metadata and the final URL list.

### Claude — plan revision 2

Codex's two points are taken. The split, the merged WATCH set, the shared lock and the save-time URL check stand as
approved.

**1. Health uses the same effective targets and watched set as the Watchlist.**
- **One module, `watch/targets.py`,** gives every reader the same answer:
  - **the effective targets:** the imported `documents['watch/targets.json']` targets as the base, overlaid by
    `watch_targets` rows (a row wins, per key);
  - **the watched set (a):** every candidate with status `watch`, keyed `norm_company(name) or id`, then the ACTIVE
    effective targets (`setdefault`, a candidate wins), exactly as the old `watched()`.
- **Its readers:** `GET /api/watch` (the view) and Health (`health/inputs.py`, which today reads targets straight
  from the imported document). Health's watch counts (`watch_counts`: companies, active manual targets, open
  triggers) come from the same functions. Health's event input already comes through Conviction's loader, which
  switches to the one trigger reader (Scope 2).
- **Tests (hosted):**
  - a MANUAL company with no candidate: saved, then counted on the Watchlist and in Health; deactivated (`active:
    false`), then gone from both; reactivated, then back in both;
  - a Scout-only WATCH candidate (a planner lead, no target): listed on the Watchlist and counted in Health;
  - the two views compared at each step: the same company keys, the same counts.

**2. The first save of an imported target merges from its effective record.**
- Under the lock, `watch_target` reads the EFFECTIVE record for the key: the live row if there is one, otherwise the
  imported target. Then it applies the old `set_target` merge:
  - it keeps `added_at` and `checks`;
  - it updates `name`, `urls`, `candidate_id`, `active` and `updated_at`;
  - it writes the whole record as the row.
- So the first save never drops the imported checks or the creation time, and later saves merge from the row.
- **Test (hosted):** an imported target is seeded with `added_at` and a `checks` entry per URL. Its pages are saved
  twice: first two URLs, then a different list of three.
  - After each save, `added_at` is the imported one and `checks` keeps its imported entries, since 037a runs no
    checks and does not prune them, as the old `set_target` did not;
  - `urls` is the latest list, at most 6, and `updated_at` is the save's time;
  - the oracle's old `set_target` over the same world gives the same records.

## H-376 plan verdict

**APPROVE.** Revision 2 resolves both H-375 findings. Health and the Watchlist will derive membership from the same candidates and effective targets. The proposed tests cover a manual target through deactivation and reactivation and a Scout-only candidate without a target. The first save will read the imported record under the lock, and the second will read the live row. Comparing both saves with the legacy oracle will check that replacing the URL list preserves the creation time and check history.

### Claude — implementation

**Storage** (migration 0027)
- **`watch_targets`:** `key` primary key, `record json`, an identity `ord`, `created_at` and `updated_at`. DELETE is
  refused.
- **`watch_events`:** `seq`, `kind` (trigger|status), `trigger_id`, `dedupe_key`, `line json` and `recorded_at`.
  - `dedupe_key` is UNIQUE where `kind = 'trigger'`, and a check ties `dedupe_key` to triggers only.
  - UPDATE and DELETE are refused.
- RLS is on, with no grants. A PGlite block covers 0027 (87 in all).

**Domain** (`watch/`)
- **`log.py`, the ONE trigger reader:** `load_events` returns the archived `watch/triggers.jsonl` lines, then the rows
  by `seq`, plus `parse_text`, `triggers`, `open_triggers` and `append_status`. Conviction's loader (and so Today,
  Home and Health) and the Map's loader (`map/inputs.py`, `inputs_model.py`) now read it.
- **`targets.py`:**
  - `effective_targets`: the imported targets overlaid by rows, a row winning in place;
  - `effective_record`;
  - the pure `watched()` in the old order, under decision (a);
  - `watch_candidates`: every `watch` candidate, read as old inbox records in inbox order, so the Scout leads come
    after the inbox ones, together with the current proposals.
- **Health** (`health/inputs.py`, `inputs_model.py`, `core.watch_counts`) uses the same effective targets and
  watched set (revision 2).
- **`view.py`:** the old `view()` (`LABEL`, `NOTE`, the sort, the 10 newest, `triage_predates_evidence` with the old
  `proposed_at` form, `machine_proposal`).
- **`writes.py`:** `set_target` (the first save merges from the EFFECTIVE record, revision 2) and `acknowledge`.
  Each write runs its pure checks, then `ensure_intake_open`, then ONE lock,
  `pg_advisory_xact_lock(hashtext(<schema> || '.watch'))`.

**Routes** (the old paths under `/api`, as the jobs port's `/api/catchup`)
- `GET /api/watch` → `{companies, labels, note}`.
- `POST /api/watch_target` → `{ok, target}`; a 400 with the old texts.
- `POST /api/watch_ack` → `{ok, kind, trigger_id, status, at, note}`; a 400 for "status must be reviewed or dismissed"
  or "no such trigger".
- Both writes: a 409 before the import, and a 400 for a body that is not a JSON object.

**Page**
- **The Watchlist's "Watched companies" panel:** every old control and text, live. That covers the name link, the
  "{open} new" badge, the amber "machine triage predates new evidence" badge, the pages details with the whitespace
  split and Save pages, the per-URL check lines, the TriggerList with Reviewed and Dismiss, and the empty state.
- **Deal Flow's "On WATCH — sensors" section.**
- **"Check now"** is deferred, with ONE wording on both pages: "Page checks arrive with the WATCH sensors port.". The
  two old differing wordings are gone.
- **The invalidations:**
  - Save pages: watch and Health;
  - an acknowledgement: watch and Today, plus Home, Health, the Conviction pipeline and case, and the Map intel (every
    reader of the trigger log).
- **Not reproduced:** the panel shows an error box with Retry when its read fails, where the old panel showed
  nothing. Kept for parity: "page check" for non-scan triggers (e), and "Loading watch state…" when the view does not
  list the company.

**Declared differences** (all in `parity_watch_store.normalise`, plus Health's (m))
- **(a)** The old view, with the watched set extended by the merged `watch` candidates.
- **Health real (m):** its watch counts equal the Watchlist route's own.
- **`urls` that is not a list of strings** gets a 400; the old code crashed with a 500.
- **A BOM-prefixed archived log:** its first line is now read by every reader. That was already the Map's rule
  (H-201); the old Conviction, Today and Health skipped it. A hosted test covers it.
- **Errors:** the old `ApiError` 400, with each answer's status code.
- **Deviation:** the imported targets are read from the byte-exact `legacy_documents` archive first, then
  `documents`. The content is the same, and the old key order is kept.

**Verification (all pass)**
- **Goldens, check and hosted** (`parity_watch_store`), 22 steps over an invented world (9 companies with (a), 8
  without). Each step compares the answer and status, the log lines, the effective targets, the view, and the log as
  Conviction, Today, Health, Home and the Map read it. Exactly the two watch tables change.
- **Real snapshot** (`parity_watch_store real`):
  - 0 differences on the view, a save and a "no such trigger" ack, and every reader matches the old `_events()`;
  - only `watch_targets` changed;
  - **the watched set is 21 companies:** the old 1 plus the 20 Scout planner leads, with 0 targets and 0 triggers.
- **The other real parities**, after the loader switch: Conviction, Today, Health (watch count +20 companies, 0
  open), Home and the Map all pass.
- **Hosted:** `test_watch_hosted` (9), covering:
  - a manual target activated, deactivated and reactivated, against Health;
  - a Scout-only WATCH candidate;
  - an imported target saved twice, keeping `added_at` and `checks`;
  - concurrent saves losing no update;
  - an unknown ack;
  - nothing before the import;
  - the `dedupe_key` uniqueness;
  - only the watch tables changing.

  The existing Map, Health, Conviction, Today and Home hosted files (64) also pass.
- **Unit:** `test_watch_store_unit.py` (12).
- **Vitest:** `WatchedCompanies.test.tsx` and `DealFlowWatch.test.tsx` (21).
- **E2e:**
  - `watch-mocked.spec.ts` (10);
  - the preview's new "Save pages for a watched company, read back" in `network.spec.ts` (Check now deferred, the
    toast, the URL read back);
  - with `deal-flow.spec.ts` and `health.spec.ts`: 32 pass and one is skipped by design. Two Health overflow cases
    timed out during the 12-minute combined run, and pass alone (3/3).
- **Capture, old vs new:** the same panel. The differences are (a)'s 21 companies, against the old scratch copy's
  empty panel, and the preview's watched people from the e2e writes. The capture now waits for `/api/watch`
  (`settle`).
- **Gate:** backend 1,958, frontend 983, PGlite 87.

**For 037b:** the trigger writer must also check the ARCHIVED lines' dedupe keys, since the unique index covers rows
only.

## H-378 implementation verdict

**REVISE.** A malformed Save pages request can clear a company's saved URLs. In `watch/writes.py`, `parse_target` applies `or []` before checking the type. I confirmed that explicit `false`, `0`, `""`, `{}` and `null` each parse as an empty list. The writer then replaces the existing URL list. All 12 WATCH unit tests passed, but their malformed inputs miss these values.

Default a missing `urls` field to the existing empty-list behavior and validate every explicitly supplied value. Cover these five values at the route, checking for HTTP 400 and preservation of previously saved pages. Keep an explicit empty list as the valid way to clear pages.

### Claude — implementation revision 2 (H-379)

Codex's point is taken: `parse_target` applied `or []` before checking the type, so a supplied `false`, `0`, `""`,
`{}` or `null` parsed as an empty list and the save replaced the existing pages with nothing.

**The fix** (`watch/writes.py::parse_target`): `raw = body.get("urls", [])`.
- Only an ABSENT field defaults to the empty list, the old behaviour for a missing field.
- Every supplied value is validated: anything that is not a list of strings is a 400, "urls must be a list of
  strings", before any write.
- An explicit `[]` is still the valid way to clear the pages.

**Regression** (`test_a_malformed_urls_value_is_a_400_and_keeps_the_saved_pages`, hosted, through the route, one
case each for `false`, `0`, `""`, `{}` and `null`):
- the pages are saved first;
- the malformed save gets the 400, the table fingerprint is unchanged, and `GET /api/watch` still shows both pages;
- then `urls: []` clears them with a 200.

Under the old `or []`, each case would have answered 200 and wiped the pages.

**Verification (all pass):** the WATCH unit tests (12), the new hosted cases (5), `parity_watch_store check`, and the
gate (backend 1958, frontend 983, PGlite 87).

## H-380 implementation verdict

**APPROVE.** Revision 2 resolves H-379. Only an omitted `urls` field gets the default. Each of the five malformed values now fails validation before the route opens a transaction. The hosted regression checks the 400 response, the database fingerprint and the two saved pages, then verifies that an explicit empty list clears them. I reran all 12 WATCH unit tests successfully and reviewed the five hosted cases. Claude reports that all five passed.
