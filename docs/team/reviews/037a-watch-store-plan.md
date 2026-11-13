# 037a — Plan: WATCH, part 1 (the store, one trigger reader, the view, pages and acknowledgements)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-377) — implementation next

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
