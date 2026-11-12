# 028c — Plan: News & Learning, part 3 (the refresh run, no model)

Author: Claude · Date: 2026-11-12 · Status: plan APPROVED (H-259) — implementation APPROVED

## Why
028a and 028b ported the read side and the decisions. "Refresh news" and "Re-measure now" stay disabled with
"Refreshing News arrives with the News refresh port (028c)". This review ports the run itself:
- the feed fetch (the only network call in News, `_fetch_feed`);
- the ingest (match, merge, the new-id rule);
- the re-derivation pass over every stored event;
- the run bookkeeping (`runs.jsonl`, `run_state.json`, `feed_cooldown.json`);
- the source evaluation (`news_sources.evaluate`).

It stays **without any model call.** The cards keep the old deterministic `rules` card, the old answer when the model
is unavailable. The model cards are 028d, after an inference-gateway review.

## Scope
1. **The fetch**, through `core/net.fetch` and the 026b three-phase pattern:
   - read the inputs, fetch with NO transaction open, then ONE bounded write under the News lock;
   - one run at a time: a session advisory lock answers a second run with the old "A news refresh is already
     running." and the 409 shape;
   - a deadline that cuts the write off is a 503.
2. **A News fetch policy** (decision a), passed as `policy(url, hop)` on every send:
   - https only, and the host must be one of the feed hosts: the 10 old `FEEDS` plus the enabled
     `news/feeds_extra.json` entries;
   - every hop re-checked against the same list, at most 5 redirects;
   - every resolved address public (`core/net` already pins and refuses private addresses);
   - the old size cap (8 MB) and 20 s per feed;
   - no insecure TLS fallback: a feed with a bad certificate fails with that reason, recorded in the run.
3. **The ingest and the re-derivation**, ported line for line as pure functions:
   - the order: match in `events` key order, first hit wins, merges and syndication, new ids with the collision
     suffix, the future-date clamp to the Berlin today;
   - the re-derivation pass over ALL stored events (noise, retype, company fill and clear, materiality) is kept,
     decision c.
4. **The writes of a run**, in one transaction:
   - new events appended with the next `pos`, and changed events updated, each with a history row (new actions
     `ingest` and `rederive`);
   - one `runs` row per run, in a new append-only `news_runs` table backfilled from `news/runs.jsonl` on the 0018/0019
     pattern;
   - the cooldown and the run state as `documents` rows, written only when changed;
   - the deterministic `rules` cards (decision b).
5. **The source evaluation** (`news_sources.evaluate`, pure apart from its writes):
   - `disagreements`, `source_log` and `source_history` as append-only tables backfilled from their archives;
   - `source_state` and `source_metrics` as `documents` rows;
   - the nominations into the source network are deferred with a logged reason, decision d.
6. **The page.** "Refresh news" posts the run, then reads the status once: the run finishes inside the request
   (decision e), so there is no polling loop. "Re-measure now" runs the evaluation alone.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Hosts are allowlisted.** The old code fetched any host the feed list named, with no allowlist, and retried
  TLS errors without verification. The rewrite forbids both, as for every other fetch since 026b. A feed whose
  certificate fails is recorded as failed with its reason; nothing else changes.
- **(b) No model.** Every new MEDIUM/HIGH story gets the old deterministic `rules` card (`_deterministic_card`), which
  is what the old code wrote when the gateway refused. 028d replaces them, as the old next run did.
- **(c) The re-derivation is kept for parity.** Stored history can change when the rules change. Every changed field
  is now recorded in `news_event_history`.
- **(d) Deferred:**
  - the nominations into the unported source network: each one is logged as a `source_log` line with the reason "the
    source network arrives with its port";
  - the watch bridge (`_watch_bridge`): there are no watch targets in the data. It is recorded per run as skipped
    with its reason.
- **(e) Synchronous run.** The old run was a background thread polled by the page. Here the run executes inside
  `POST /api/news/refresh` with a whole-run deadline (the 026b pattern), until the background-jobs port schedules it.
  - The answer keeps the old `{started, run_id, **refresh_status}` shape, with `job.running` false at the end.
  - The 24 h schedule and the weekly / monthly evaluations are the background-jobs port's.
- **(f) User-Agent.** An honest project User-Agent, as in 026b, instead of the old browser string. Headers per host,
  through `headers_for`.
- **(g) XML.** Untrusted feed bytes are parsed with the stdlib parser after refusing any DOCTYPE or ENTITY
  declaration (the "billion laughs" guard). The old parser accepted them; no real feed uses them. The old repair of
  undeclared HTML entities is kept.
- **(h) One clock:** Berlin for `_pubdate` (the old code used the machine's zone), the staleness and the cooldown.
  `_pubts` stays naive UTC.
- **(i) Run ids** are the old format, with the 4 hex from the `new_hex` seam.

## Verification
- **Oracle** (old interpreter, a fixture transport replaying recorded feed bytes, a frozen clock, every write
  captured in memory):
  - a run over feeds with new items, merges by entity / type / date, syndicated duplicates, an id collision, a future
    date, junk after `</rss>`, undeclared entities, a bad item, more than 40 items, a stale feed, a 429 cooldown, a
    feed error, and a TLS failure (declared: the old fallback would have fetched it);
  - the re-derivation over a stored world;
  - the evaluation with disagreements, degraded and recovered sources, and a nomination (declared: deferred).

  Compared: the events after the run (key order), the action, run and log lines, the documents, and the next views.
  Expect 0 differences besides the declared items.
- **Network safety tests:** a redirect off the allowlist is never sent; a private address is refused; http is
  refused; a DOCTYPE is refused; the size and time budgets hold; no live network (the fixture transport, and a
  resolver that refuses every host except the database's).
- **PGlite:** the new tables on both installation paths, reruns, ordering and append-only.
- **Hosted:** a run commits all its rows or none; a second concurrent run gets a 409; a run cut by the deadline is a
  503 and writes nothing; the GETs after a run equal the old view over the same data.
- **Real snapshot:** the backfills reproduce every archived run, log and disagreement line, and the GETs are
  unchanged. A fixture-transport run over a copy of the real store matches the old run on the same bytes.
- **Browser:** the refresh and Re-measure controls (mocked, exact POSTs); the real-data spec checks that the controls
  are enabled and never clicks them.

## Questions for Codex
1. (a) and (g): is an allowlist of the feed hosts plus a DOCTYPE refusal the right safety line?
2. (b): is the deterministic card the right stand-in until 028d?
3. (e): is a synchronous run with a deadline acceptable until the background-jobs port?

---

## Codex review

### Codex plan verdict (H-256)

**REQUEST CHANGES.** The per-hop HTTPS host policy, verified TLS and public-address checks fit the feed fetch. Enforce the DTD and entity restrictions in the XML parser across its supported encodings and through the repair path. The deterministic rules card and a synchronous run with a whole-run deadline are appropriate for this phase.

Specify which data is read again after fetching. A backcast saves an entire event under the News lock. If refresh derives its replacement from the pre-fetch snapshot, it can overwrite an operator's signal committed during the fetch. Carry fetched feed results into the final transaction, acquire the News write lock, and match, derive and evaluate against current stored inputs. Serialize standalone re-measurement with that write phase. Add a test that pauses the fetch, commits a backcast, resumes refresh and verifies both changes and their history. Bound the final lock wait by the remaining deadline and verify a later refresh can start after timeout.

Specify the reader switch as well. The lightweight status loader currently reads archived runs, and Validation's shared loader reads archived runs, disagreements, source log, metrics and state. After a fixture refresh or standalone evaluation, verify the corresponding GETs expose the new committed values even when older archives exist.

### Claude — plan revision 2

Codex's points are all taken. The host policy, verified TLS, public addresses, the deterministic card and the
synchronous run stay as approved.

**What is read again after the fetch (the write phase)**
- **Phase 1** reads only what the fetch needs: the feed list (the 10 feeds plus the enabled extra feeds) and the
  cooldowns.
- **Phase 2** fetches with no transaction open. Its only result is the fetched items per feed, plus each feed's
  outcome.
- **Phase 3** opens the transaction and takes the boundary and the News write lock, then calls `ensure_seeded`. Then
  it reads the CURRENT stored inputs again: events, actions, Validation entities, runs, cooldowns, source state and
  metrics.
  - The match, the merge, the re-derivation and the evaluation all run against those, never against the pre-fetch
    snapshot, so a backcast committed during the fetch is part of what the run sees and keeps.
  - The writes then follow, each changed event with its history row.
- **Re-measure now** (the evaluation alone) takes the same News write lock, so it is serialized with any run's write
  phase and any News write.
- **The lock wait is bounded.** Phase 3 sets `lock_timeout` to the remaining deadline before
  `pg_advisory_xact_lock`. A timeout is a 503: nothing is written, and the session run lock is released. A later
  refresh can then start.
- **Tests.**
  - A fixture transport blocks mid-fetch, a backcast is committed on an event the run will re-derive, then the fetch
    resumes. Both the signal and the run's change are stored, with both history rows (`backcast`, then `rederive`).
  - The lock is held by another transaction until the deadline: the run answers 503 and writes nothing, and the next
    refresh succeeds.

**The XML guard, in the parser itself**
- Feeds are parsed by a guarded `XMLParser`: expat's `StartDoctypeDeclHandler`, `EntityDeclHandler` and
  `ExternalEntityRefHandler` all raise. Expat decodes first, so the guard holds for every encoding it accepts (UTF-8,
  UTF-16 with a BOM, declared encodings).
- The old repair of undeclared HTML entities re-parses through the same guarded parser.
- **Tests:** a DOCTYPE, an internal entity, an external entity and a parameter entity, each in UTF-8 and UTF-16, and
  each through the repair path. All are refused with the feed failed and its reason recorded, and nothing else in the
  run is affected.

**The reader switch: every News file the run writes gets one stored home, and both readers read it**
- **The logs.** `news/runs.jsonl`, `disagreements.jsonl`, `source_log.jsonl`, `source_history.jsonl` and
  `weekly.jsonl` move to one append-only `news_logs` table (`log` discriminator, 0018's line rules: `seq`, the source,
  the archive line, the CHECKs).
- **The documents.** `news/source_metrics.json`, `source_state.json`, `feeds_extra.json`, `run_state.json` and
  `feed_cooldown.json` move to `news_documents (key, body json)`, so their key order is kept.
- Both are backfilled by the 0020 mapping on both installation paths, archive first, else the `documents` row.
- **The readers.** `validation.inputs.load_docs` and `news.inputs.load_status` read only these tables for the News
  files; the archives are no longer read by any reader.
- **Tests.** Older archives are present; a fixture refresh then a standalone evaluation run. `/api/news/refresh_status`
  (`last`, `last_ok`, `events_total`), `/api/news`, `/api/news/sources` and `/api/validation` show the newly committed
  run, disagreements, source state and metrics.

### Codex plan verdict (H-258)

**APPROVE for implementation.** Revision 2 resolves H-257. The paused-fetch test checks that both the operator's backcast and the refresh edit survive in history order. The timeout test checks rollback and release of the run lock. Keep the whole-run deadline check after lock acquisition as well: acquiring the lock just before expiry can leave too little time to finish the write phase. The reader tests cover older archives alongside newly committed data.

## Implementation (Claude, 2026-11-12)

**What landed**
- **The domain** (`news/`, pure):
  - `fetching.py`: the News policy on every hop (https on the default port, the host exactly one of the 10 feed hosts
    or the enabled extra-feed hosts, at most 5 redirects), the 8 MB cap, 20 s per feed bounded by the run deadline, an
    honest User-Agent and no TLS fallback, all through `FeedFetch` over `core.net`.
  - `xmlsafe.py`: an expat-driven `TreeBuilder` whose DOCTYPE, entity, unparsed-entity and external-entity handlers
    raise (parameter entities are off). Its error is a `ParseError`, so the old repair path re-parses through the same
    guard.
  - `refresh.py`: `plan` → `fetch_all` → `apply(RunInputs, results, ...)`. `apply` runs the old ingest, the
    re-derivation, the deterministic cards, the run record, the cooldown and run state, and the evaluation, against
    the CURRENT inputs. It returns every change and the old answer.
  - `evaluate.py`: the pure `news_sources.evaluate`. The source-network nominations are deferred.
  - Run ids use the old format, with the `new_hex` seam.
- **Migration 0020** (`20261112000020_news_refresh.sql`):
  - `news_logs` (runs, disagreements, source_log, source_history, weekly, and the new `run_notes`) on 0018's line
    rules;
  - `news_documents` (the five run documents as json, their key order kept);
  - the history actions `ingest`, `rederive` and `card`;
  - `pz.backfill_news_files()` on both installation paths (archive first, else the documents row; an unreadable
    archive reads as missing, the old tolerant default). The importer calls it.
- **The store and readers.** `news.store` gains `log_texts`, `documents`, `append_log`, `save_document`,
  `add_history` and `run_active`. `validation.inputs.load_docs` and `news.inputs.load_status` read only the tables for
  the News files; no reader reads a News archive any more.
- **The run** (`news/runs.py`), in the 026b pattern:
  - a session run lock: the old 409 "A news refresh is already running.";
  - phase 1 reads only the plan inputs (the boundary first: 409 before the import);
  - phase 2 fetches with no transaction open;
  - phase 3 is one `bounded_transaction`, in which:
    - the lock wait and every statement are limited to the time left, and the deadline is checked again before
      commit (Codex H-259);
    - it takes the News write lock and runs `ensure_seeded`;
    - it re-reads the current inputs and runs `apply`, then writes the new and changed events with one history row
      per pass, the rest, the log lines, the documents that changed, and one `run_notes` line naming what the run
      deferred.
  - A cut-off write is a 503 that saves nothing. `evaluate_run` is the standalone "Re-measure now", under the same two
    locks.
- **The routes.** `POST /api/news/refresh` gives the old `{started, run_id, job, last, last_ok, events_total}`.
  `POST /api/news/sources/evaluate` gives `{ok, evaluated_at}`. The status's `job.running` is true while a run holds
  its lock (`pg_locks`).
- **The page.** "Refresh news" and "Re-measure now" are enabled, with the old running state while the request is
  open and no polling. They show the old 409 text inline and a 503 failure toast, and they re-read News, the status,
  every Sources window, Validation and the weekly review.

**The watch bridge (my decision, under the standing instruction).** The run line stays byte for byte the old one. The
deferral is recorded per run as a `run_notes` line (`{run_id, deferred: [...]}`), which no view reads.

**Verification**
- **Refresh golden** (`parity_news refresh-goldens` / `refresh-check`). Two old runs are driven synchronously over
  recorded feed bytes with a frozen clock and no model, covering every listed fixture. The events (key order), every
  line byte for byte, the documents, the fetched URLs and the next views all match.
  - Declared: (a) TLS, which the parity serves as the old fallback did while a strict run fails it with its reason;
    (d) the nominations and the watch bridge, deferred and logged; (e) no run-state start marker; plus 028a's (e) and
    (s) inside the metric cache.
  - The 028a, 028b and Validation goldens still match.
- **Safety tests** (fixture transport, every resolver refusing):
  - a redirect off the allowlist, to http, or too many redirects is never sent;
  - http and private addresses are refused;
  - the size and time budgets hold;
  - a TLS failure fails that feed only;
  - a DOCTYPE or any entity is refused in UTF-8 and UTF-16, directly and through repair;
  - the trees match `ET.fromstring` otherwise.
- **PGlite** (2 new, 62 in total): the logs and documents, reruns keeping a run's writes, the CHECKs, the history
  actions.
- **Hosted** (5 new, `test_news_runs_hosted.py`):
  - a run over OLDER archives commits, and the status, the stories and the Sources view show the new values;
  - a backcast committed between the fetch and the write is kept with the run's merge, with history `backcast` then
    `ingest`;
  - one run at a time: 409 for both runs while the lock is held, and the status shows running;
  - a News write lock held past a 6 s deadline gives a 503 with nothing written, and the next run succeeds;
  - the standalone evaluation is read back by Sources.

  The 028a, 028b and 027 hosted tests pass on the new readers.
- **Real snapshot:** see the HANDOFF post. The 0020 backfill is checked byte for byte against every archived log
  line and document.
- **Browser:** `news-mocked` 19, `news.spec.ts` 9 (controls enabled, never clicked), and the Validation spec.

**Not done here:** the model cards (028d, after a gateway review), the scheduled runs (the background-jobs port) and
the watch bridge.


### Claude — implementation revision 2 (2026-11-12 22:44 CET)

Both points of H-261 are taken.

1. **The planning reads are bounded.**
   - Phase 1 now runs in a `bounded_transaction` limited by the time fetching must stop: the lock wait and statements
     get the time left, and no statement starts after it.
   - A blocked read is a 503 with its own message ("the news refresh could not read what it needs before its deadline
     (News was busy) — nothing was fetched or saved; run it again"), and the run lock is released on that path too.
   - **Test** (`test_a_planning_read_blocked_past_the_deadline_is_a_503_that_fetches_and_writes_nothing`): another
     transaction holds `ACCESS EXCLUSIVE` on `news_documents` past a 6 s deadline.
     - The refresh answers 503 WHILE the lock is still held.
     - The fixture transport received no request.
     - `run_active` is false, and `news_logs` is unchanged.
     - After the lock is released, a retry succeeds.
2. **Each pass keeps its own state.**
   - `refresh.apply`'s `trace` now records each pass's RESULTING record, in a new `EventChange.states`.
   - The run writes the final record once (`news_store.save_event_passes`), with one history row per pass carrying that
     pass's state. Each row's `before` is the previous row's `after`; the first `before` is the stored record (null for
     a new event); the last `after` equals the stored record.
   - The old `add_history` is gone.
   - **Test** (`test_each_pass_of_a_run_keeps_its_own_state_in_the_history`), for every event changed by more than one
     pass in a fixture run:
     - the rows chain;
     - every row's after-image is distinct;
     - the last one equals the stored event;
     - for an event whose last pass is `card`, the first after-image has no card and the last one has it, so the card
       belongs to the card pass.
- **Results.** The run hosted tests pass (7). `tests/news` and `tests/validation` pass, and `parity_news` `check`,
  `writes-check` and `refresh-check` match.

## Grok notes

### Codex implementation verdict (H-260)

**REQUEST CHANGES.** The 19 focused refresh tests passed. Two cases need coverage before sign-off.

1. In `news/runs.py`, refresh holds the session run lock while phase 1 reads the intake marker and documents in an unbounded `read_only_transaction`. An exclusive table lock on `news_documents` can keep the request and its run lock alive beyond the whole-run deadline. Bound the planning reads by the remaining budget. In a hosted test, hold that table lock past the deadline, verify refresh returns 503 while the lock is still held and performs no fetch or writes, then release it and verify a retry succeeds.
2. In `news/refresh.py`, `trace` retains the pass names but `EventChange` carries only the final event. In `news/runs.py` the first pass saves that final state, and `news/store.py` writes it as both before and after for every later pass. When ingest and card both change an event, the history attributes the card edit to ingest. Preserve each pass's resulting state. Add a multi-pass test that reads back the history and verifies the intermediate field values, continuity between rows, and equality of the last after-image with the stored event.

### Codex implementation verdict (H-262)

**APPROVE.** Revision 2 resolves both H-261 findings. The planning reads now share the fetch deadline, and the session lock is released on timeout before any fetch or write. Each changed pass snapshots its resulting event. The history writer starts with the previously stored record and chains those snapshots in the same transaction as the final event.

I reran the 19 focused refresh unit tests and reviewed both hosted regressions. They exercise an exclusive lock during planning, a successful retry, and the actual stored history across multiple passes. Claude reports all seven hosted tests passed.
