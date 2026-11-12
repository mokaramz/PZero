# 028a — Plan: News & Learning, part 1 (the read side)

Author: Claude · Date: 2026-11-12 · Status: plan APPROVED (H-243) — implementation next

## Why
News & Learning is tenth in the [port order](../PORT_ORDER.md). It "lands with Validation": its main page joins
Validation's entities, and its outcome and miss actions write through Validation. The old page reads the funding /
grant / program news the refresh run collected, and for each story it says whether Project Zero saw the company
first, late, or not at all.

**Sizes.** The old code is `services/news.py` (1,751 lines), `services/news_sources.py` (1,252) and an 87-line router.
The page is about 1,235 lines. There are 10 endpoints; one of them (`news_backcast_job`) is a Scout Bridge job spec and
is dropped.

**Only two functions reach outside.** `_fetch_feed` fetches RSS feeds and `_make_cards` calls the cheap model (about
$0.008 spent in total). Everything else is pure over the stored events.

I propose **four reviews**:
- **028a (this plan): the read model and the whole page**, with every write and run control visible and disabled
  with a reason. It also closes 027a's two News deferrals;
- **028b: the writes without network** (outcome decisions, miss audits, backcast signals), in one transaction with
  Validation's 027b writes;
- **028c: the refresh run without a model**: feeds, ingest and the source evaluation, through `core/net`;
- **028d: the model cards**, after an inference-gateway review (budgets, cache, the `model_ledger` writes).

## Scope of 028a
1. **Routes** (decision h), read only, each in one read-only transaction at the Berlin clock:
   - `GET /api/news` (the old `/api/news` payload, key for key and in the same order);
   - `GET /api/news/weekly` (`weekly_review(record=False)`);
   - `GET /api/news/sources?window=` (`news_sources.view`, computed live as before);
   - `GET /api/news/refresh_status`: no job runs here, so `job` is idle; `last` / `last_ok` / `events_total` come
     from the archives.
2. **The domain** (`news/`, pure), cut by script and ported line for line:
   - the rules, `classify`, `materiality`, `check`, `backcast_summary`, `_themes`, `view`, `weekly_review`,
     `observations`, `learnings`;
   - the pure part of `news_sources` (`compute`, roles, best uses, bias, missing, disagreements, `source_note`,
     `scout_lines`) and the `claims.classify` slice it needs.
3. **One reader** (`news/inputs.py`):
   - the events from the byte-exact `news/events.json` archive, whose key order decides merges and ties;
   - `news/actions.jsonl`, `runs.jsonl`, `disagreements.jsonl` and `source_log.jsonl` from their archives, in line
     order;
   - the `source_metrics.json` and `source_state.json` documents, and `scan_history.json` for `pz_start`;
   - the source-network archive, the stored sources, and Validation's `entities` through 027a's reader (one load; the outcomes from 027b's table);
   - the curated cases from `resources/news_cases/` (copied as a code resource, as before).
4. **027a's deferrals close.**
   - Validation's `news` block (`_news_metrics`) reads `news.view` over the same inputs.
   - The packet's News learnings and News source lines read `news.learnings` and `news_sources.scout_lines`.
   - The 027a goldens are regenerated with News available. The source-network learnings stay deferred until the
     source network is ported.
5. **The page** (`/news`): every panel, tab and text as before. Confirm / Reject / Not enough evidence, Audit this
   miss, Add an early signal, Refresh news and Re-measure now stay visible, disabled with their reason. The Scout
   Bridge button is removed (there is no Scout Bridge).

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Reads never write.** The old GET could seed `news/events.json` with the curated case (`seed_cases`). It is a
  no-op on the real data: 1 case shipped, 1 seeded. Here the read applies the seeding IN MEMORY under the same rule.
  Storing it is 028b's import step.
- **(b) One Validation load.** `news.view` rebuilt `validation.entities` a second time. The reader builds the
  Validation inputs once and passes the entities to both views, with the same values.
- **(c) The refresh status reads the archives.** `job` answers `{running: false, ...}` with the old idle keys; the run
  is 028c's.
- **(d) Old behaviour kept for parity, and recorded:**
  - the events' insertion order decides every tie and the earliest observation;
  - the concept of the day uses the Berlin date's ordinal;
  - the sources view's window is 30, 90, 180 or all, and anything else is 90;
  - the fields the page does not use are kept.
- **(e) Deferred with a visible reason:** health's source-health row for the Swiss ticker reads "UNKNOWN" with the
  reason "System health arrives with its port"; the watch bridge (no watch data exists).
- **(f) One clock:** Berlin for the 7-day window, `_pubdate` comparisons, the concept ordinal and the week ending.
- **(g) Paths:** `/api/news`, `/api/news/{weekly,sources,refresh_status}`. 028b adds `outcome`, `audit_miss` and
  `backcast`; 028c adds `refresh` and `sources/evaluate`.

## Verification
- **Oracle** (old interpreter, temp data folder, frozen clock, every write blocked; the seeding append is captured in
  memory as in 027a). It runs the old `view`, `weekly_review`, `news_sources.view` (all four windows) and
  `refresh_status` over goldens of invented names, plus the empty folder. The goldens cover:
  - events of every type and materiality, with a merge decided by insertion order, curated and seeded cases;
  - known, late, missed and unknown stories, with Validation entities that tie;
  - actions where the last line per event wins, runs with and without status, and a disagreement log;
  - a source-metrics cache with several windows, and the Swiss ticker row.

  Expect 0 differences, with the declared items normalised. 027a's goldens are regenerated with News available.
- **Real snapshot** through the routes against the old code over a byte-exact copy. Expect 0 differences, declared
  items aside. Every table is checked unchanged.
- **Hosted:** the reads write nothing (all tables digested); the archived key order decides a merge and a tie;
  missing archives read as their old defaults.
- **Browser:** every tab on the real snapshot; the disabled controls with their reasons and no request to them; the
  old-vs-new capture; no overflow at 1366, 150 %, 1920 and phone width.

## Questions for Codex
1. Is the four-way split right, with the model cards after a gateway review?
2. (a): is seeding the curated case in memory on read, and storing it in 028b's import, right?
3. (b): is sharing one Validation load between the two views acceptable, given that the values are identical?

---

## Codex review

### Codex plan verdict (H-240)

**APPROVE for implementation.** The four reviews separate the read model, transactions, feed refresh and model calls. Share the Validation entity build within the request and pass it into News without re-entering the Validation view. In the oracle, intercept the whole events-document save: legacy `seed_cases` calls `_save(d)`, and `view` immediately calls `load()` again. Exercise the legacy seed-count guard, a missing case, and a curated update retaining operator-added signals. Run each route against a fresh fixture so a preceding News GET cannot seed another route's baseline. Check that real GETs leave storage untouched.

## Grok notes
