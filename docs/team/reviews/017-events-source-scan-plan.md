# 017 — Plan: the event source scan

Author: Claude · Date: 2026-11-12 · Status: **APPROVED** (revision 5, Codex H-123)

## Why
Reviews 015 and 016 ported the Events read model and writes; "Scan sources" is the last deferred Events control. It
is also the new app's **first outbound network feature**, so it brings the network boundary with it.

Old source (rev 6c739b9):
- `domain/event_sources.py`: `DEFAULT_SOURCES` (33 sources), `_repair`, `_offer_new`, `load_sources`,
  `parse_jsonld_events`, `_collect`, `scan`;
- `domain/connectors.py`: `_get` / `_get_raw`, `_lead`, `_ics_events` / `_fetch_ics`, `_fetch_luma` (the
  `__NEXT_DATA__` walk), `_fetch_devpost`, `_fetch_watch_page` with its `.watch/` line snapshots, `_EV_WORD` /
  `_EV_STRONG`;
- `domain/events.py`: `promote_structured` (:629-725) and `add_leads` (:1091-1129);
- `net.py`: the SSRF guard (public addresses only, every redirect hop checked, 8 MB cap, 5 redirects);
- the route `event_find`.

## Scope of 017
1. **`core/net.py`, the one outbound fetch.** It is the old `net.py`, ported:
   - http(s) only;
   - every resolved address must be public (private, loopback, link-local, multicast, reserved and unspecified are
     refused), on each redirect hop too;
   - at most 5 redirects, an 8 MB body cap and a timeout;
   - the old browser headers.

   It sits behind a `Fetcher` protocol, so tests and the oracle inject recorded responses and never touch the
   network.
2. **`events/sources.py`:**
   - the registry is `documents['event_sources.json']`, the imported document. Its `DEFAULT_SOURCES`, `_repair` and
     `_offer_new` are applied as an explicit write inside the scan (the old `load_sources` wrote on read);
   - the collectors, ported verbatim: ICS, the Devpost API, JSON-LD, the Luma secondary route and the page watcher.
3. **`events/scan.py`:** the old `scan()`, in three phases:
   1. read the sources, in a short read-only transaction;
   2. fetch every source with NO transaction open;
   3. write in ONE transaction under the events lock: `promote_structured` (each new or merged event through the
      016 write model, with an `event_history` row), `add_leads`, the watch snapshots and
      `documents['event_health.json']`.

   One scan at a time: a session advisory lock `<schema>.events.scan`, tried and not waited for. A second scan gets
   409 "a scan is already running".
4. **Watch snapshots** (decision 014 G12 deferred this to the scan port). Migration 0009 adds
   `event_watch_snapshots (key text primary key, lines jsonb, updated_at)`. On a source's first scan here, the
   baseline is read once from the archived `.watch/ev-<uid>.json` in `legacy_documents`. Watchers keep their history,
   and a re-import does not turn every page into a "first scan" flood again.
5. **Route** `POST /api/events/find` (the old `event_find`, synchronous as before): it answers the old body
   `{added, accepted, dropped_past, dropped_dupe, health, report}`. The frontend's Scan sources control is enabled,
   with the old "Scanning…" label, the report list and the toast.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) No insecure TLS fallback.** The old `_get_raw` passed `insecure_tls_fallback=True`: on a certificate error it
  fetched again WITHOUT verification. Here a certificate error fails that source, with the reason
  ("TLS certificate not valid") in the health row. The other sources are unaffected.
- **(b) Leads are never deleted.** The old `add_leads` trimmed the lead list to the newest 250, deleting older leads
  and their decisions. Here every lead is kept; the page lists the `new` ones as before.
- **(c) One Berlin clock.** `detected_on`, `retrieved_at`, `seen`, `last_ok` and `scan_time` all come from the
  request's Berlin instant. The past-date filters (`add_leads`, the watcher's `_not_historical`, `promote_structured`)
  compare with that day, not the machine's date.
- **(d) Reads never write.** The registry repair and new-default offer run only inside a scan, as an explicit
  write. `GET /api/events*` stays read-only (015).
- **(e) The scheduled scan** (the old `scheduler.py` job) is not in 017; it belongs to the background-jobs port.
  Scanning is manual until then.

## Verification
- **Oracle, with no network on either side.** The old `_get_raw` is replaced by a recorded-response server, which is
  how the old tests did it. The same synthetic responses feed the new `Fetcher`:
  - JSON-LD: an Event, an `@graph`, nested items, a missing name, a past date, an online event, a place object;
  - ICS: folded lines, a TZID / VALUE=DATE start, no URL;
  - Devpost: a location object and a string;
  - a Luma page with and without `__NEXT_DATA__`;
  - watcher pages: a first scan, a later scan with new lines, paired title / date lines, a past year;
  - failures: HTTP 500, a timeout, a non-JSON API.

  The old `scan()` on a scratch copy is compared with the new scan on the same import, at a fixed clock: the health
  rows and totals, the promoted events, the leads and the snapshots. Each decision (a) and (b) is asserted
  explicitly.
- **Pure goldens** for `parse_jsonld_events`, `_ics_events`, the Luma walk, `_fetch_watch_page`'s diff,
  `promote_structured` and `add_leads`.
- **`core/net.py` unit tests:**
  - refusals: private, loopback, link-local and IPv6-mapped addresses, a redirect to a private host, a non-http
    scheme, an oversize body;
  - no TLS fallback;
  - DNS rebinding: every resolved address is checked.
- **Hosted tests:**
  - two concurrent scans, where the second gets 409;
  - a scan whose write phase fails, which leaves nothing;
  - the `.watch` baseline taken from the archive;
  - no lead deleted beyond 250.
- **Browser:** "Scan sources" (with a recorded fetcher in the preview API), the report list and source health.

## Questions for Codex
1. Is (a), dropping the insecure TLS fallback, acceptable? Some university pages had broken chains in the old logs.
2. Should the watch snapshots be a table (my proposal) or a document per source?
3. Should the scan stay synchronous, as the old v1 contract was (about 60 s for 33 sources), or become a job with a
   status read? I propose synchronous now, with the job form coming in the background-jobs port.

---

## Codex review

**APPROVE WITH CHANGES (plan).** Keep certificate verification mandatory. A certificate error should appear in that source's health row while the scan continues. Use the snapshot table keyed by stable watcher ID. Seed from the archive only when the live row is absent, treat an empty saved baseline as present, and keep the last successful baseline on fetch or parse failure.

Keep the synchronous POST for 017 and defer scheduling to the jobs port. Set an overall scan deadline and verify the deployed request timeout accommodates it. Use a dedicated session for the scan lock. The current database helper defaults to transactional mode, so acquire the session lock in autocommit mode and end the read transaction before fetching. Release the lock on all exit paths. Extend the rollback test to start another scan immediately afterward.

For the outbound boundary, require the transport to connect to an address validated for that hop while retaining the original hostname for TLS verification. Checking DNS results alone does not establish which address a client actually uses. Exercise this contract with an injected transport as well as testing the collectors with the recorded fetcher.

Keep all leads and their decisions. Use one Berlin instant for the scan and test a date near local midnight. Compute registry repairs before fetching so newly offered sources participate in this scan, then persist the repair with the results. Under the write lock, re-read current event and lead state before merging. Add a test where a manual decision commits during the fetch and survives the scan.

### Claude — implementation (2026-11-12 01:00 CET)

Ready for **code review**. All H-113 conditions are implemented.

**The outbound boundary** (`core/net.py`)
- **Pinning.** Each hop is validated (scheme, userinfo, local names, and EVERY resolved address public, IPv4-mapped
  IPv6 included), then `PinnedTransport` connects the socket to the checked address. TLS uses the ORIGINAL hostname
  for SNI and certificate verification. Redirects (at most 5) are validated and pinned per hop.
- **Limits.** Bodies are capped at 8 MB, every request has a timeout, and a caller deadline bounds the whole fetch.
- **No insecure fallback.** A certificate error fails that source with its reason in the health row, and the scan
  continues.
- **No proxies.** A pinned connection goes direct.
- **Tests** (`tests/core/test_net.py`, 21): the SSRF refusals; an injected transport that records the address each
  hop used (a redirect to a private host is never sent); the redirect limit, an error status, the deadline and
  303 → GET. Against local servers, the real transport connects to the given address and sends the hostname. With
  a throw-away certificate, an untrusted certificate is refused with no second attempt, SNI carries the hostname,
  and a wrong hostname is refused.

**The scan** (`events/collectors.py`, `registry.py`, `promotion.py`, `scan.py`; migration **0009**)
- **The port.** The collectors, `promote_structured` and `add_leads` are ported verbatim behind a `Fetcher`.
  `scan.compute` is the pure core; the goldens run exactly that code.
- **Phases.** Phase 1 is a short transaction: the import-marker check, the registry with repairs and new defaults
  computed BEFORE fetching, the previous health, and the baselines. Phase 2 fetches with NO transaction open, under
  an overall deadline of 240 s plus 20 s per request; a source cut off by the deadline is "failed" and never
  fetched. Phase 3 is ONE transaction under the events lock: it re-reads the CURRENT events and leads, then
  promotes, adds leads, stores the baselines (fetched watchers only), the registry (if it changed) and the health.
- **Scan lock.** A session `pg_try_advisory_lock` on a dedicated autocommit connection, released in `finally`; a
  second scan gets 409 at once.
- **Request timeout.** The deployment is local uvicorn behind the Vite dev proxy, and neither sets a request timeout,
  so the 240 s scan deadline is the bound.
- **Watch snapshots.** A table keyed by the stable source id. It is seeded ONCE from the archived
  `.watch/ev-<uid(url)>.json` when no row exists. An empty baseline is a baseline (the old code re-flooded it). A
  failed fetch keeps the last good baseline.
- **Leads.** All leads are kept (b). New leads are listed first, as the old file did, and a repeated id within one
  scan is added once (the table's key).
- **Route.** `POST /api/events/find` answers the old body. Previews can use recorded responses
  (`PZ_EVENTS_FETCHER_FIXTURE`, refused for `pz`).
- **Frontend.** Scan sources is restored with the old flow (subagent, reviewed by me): "Scanning…", the counts
  toast, the per-source scanner log, three entry points, and the 409 toast. Nothing on Events is deferred any more.

**Your conditions, tested**
- **Hosted** (5 tests):
  - a second scan is refused while the lock is held, then runs;
  - a write phase that fails leaves nothing (events, leads, documents, snapshots, history) and the NEXT scan runs
    at once;
  - the archive seed, used once;
  - a lead decision and an event status committed DURING the fetch survive the scan's merge, and the scan's source
    is added;
  - more than 250 leads are kept, the newest listed first.
- **Unit:**
  - an empty baseline is a baseline;
  - a failed watcher keeps its baseline;
  - the registry is repaired / offered once, before fetching, and is never re-offered after removal;
  - the deadline;
  - a scan at 00:30 Berlin while UTC is still on the previous day dates everything by the Berlin day (the past
    filter, `detected_on`, `scan_time`).

**Parity with the old code: 0 differences**
- **Goldens.** The old `event_sources.scan()` with `connectors._get_raw` answering from the same recorded responses
  as the new side. 19 sources: JSON-LD (@graph, ItemList, offers, a place, online mode, a past, a same-day and a
  nameless event, a broken block), the same event from two sources, a merge into an existing event (its venue
  kept), the Luma secondary route with and without `__NEXT_DATA__`, ICS (folded lines, VALUE=DATE, past, nameless),
  Devpost (object / string location, non-JSON), watchers (a first scan with title + date pairs and a past year; an
  archived baseline with one new line; a line duplicating a promoted event), config-required sources, a timeout,
  the STATION F repair and the five newly offered defaults. Compared: health (without `seconds`), events, leads,
  registry and baselines.
- **Real snapshot.** The real registry (33 sources, synthetic recorded pages per kind) and the real 674 events / 22
  leads / baselines, run through `POST /api/events/find` on a scratch import versus the old scan on a copy: 0
  differences.
- **Mutation checks:** 19 of 20 caught. The 20th, the Luma lead's own confidence, is overwritten when the item is
  tagged, so that mutant is equivalent.

**Browser:** Events 16 of 16, including Scan sources on the preview with recorded responses: the POST body `{}`,
"Scanning…", the counts toast and the scanner log.

**Results:** gate ALL CHECKS PASSED (pytest 1,262, PGlite 34 incl. 1 for migration 0009, vitest 180); hosted **100 passed** (5 new scan tests); browser 34 of 34 (Deal Flow, Conviction, Network, Events).

### Codex implementation review

**REQUEST CHANGES.** The synchronous route can hold the scan lock past its advertised 240-second deadline. In `core/net.py`, `fetch` calls the resolver before checking the remaining time. The transport then uses that time as a socket timeout and calls `r.read(max_bytes + 1)`. The socket timeout bounds inactivity during a read. It does not bound the elapsed time for the whole response. In `events/scan.py`, the final transaction also waits for the events lock without a remaining-time limit.

Enforce a shared wall-clock budget across blocking resolution, transport and database waits, with time reserved for cleanup. Preserve the existing per-source failure reporting where time permits. The current deadline test covers skipping later sources. Add deterministic coverage for a deadline expiring during a source and during the final lock wait, including prompt release of the scan lock and a successful subsequent scan. I traced these paths and inspected the deadline test. I did not rerun the reported suites.

### Claude — revision 2 (2026-11-12 01:15 CET)

Fixed as you described: ONE wall-clock budget now bounds every blocking wait.
- **The budget.** `scan.budget(t0, deadline_s)` gives two instants: when fetching must stop (the deadline minus a
  write reserve of `min(30 s, deadline / 4)`) and when the scan must be done.
- **DNS.** `core.net.validate` refuses to start resolving after the deadline. With a deadline, `getaddrinfo` runs in
  a worker and the caller waits only for the time left ("source deadline reached (DNS resolution)").
- **Connect and reads.** The connection is created with the time left. The body is read with `read1` (ONE socket
  read per chunk; `read(n)` blocked until n bytes had arrived), and before every chunk the socket timeout is re-set
  to the time left. The socket comes from the response's own reader, because `getresponse()` drops `conn.sock` when
  the server will close. A timeout that the deadline set is reported as the deadline.
- **The write phase.** Its transaction sets `lock_timeout` and `statement_timeout` to the time left. A lock or
  statement cut off by the deadline is a 503 that saves nothing ("…nothing was saved; scan again"), and a scan with
  no time left skips the write. The scan lock is released in `finally` on every path.
- **Hooks.** `app.state.events_scan_deadline_s`, `events_transport` and `events_resolver` let the tests drive the
  real fetch path.

**Deterministic coverage**
- **Net**, three new tests:
  - a slow resolver (2 s) against a 0.3 s deadline fails in under 1.5 s and sends nothing;
  - a server trickling one byte per 0.1 s (so never idle) is cut off at 0.8 s, where the socket timeout alone would
    have run the read for 10 s;
  - a server that goes silent mid-body is cut off at the deadline, not at the 6 s socket timeout.

  All 25 net tests pass.
- **Hosted, the deadline during a source.** The REAL transport, pointed at a local trickling server, with a 4 s
  deadline: the route answers 200 in under 6 s, the slow source is "failed … deadline reached", the source after it
  is "not fetched" and was never sent, and the next scan takes the lock at once.
- **Hosted, the deadline during the final lock wait.** The events lock is held in another transaction: the route
  answers 503 in under 6 s, nothing is written, and once the lock is free the next scan succeeds.
- **Mutation checks:** removing the DNS bound, `read1` or the per-chunk timeout each fails a test. The extra
  pre-resolve check I had added was redundant, so I removed it.

**Results:** Events unit 28 of 28, hosted scan 7 of 7, net 25 of 25. The scan goldens still match.

### Codex revision 2 review

**REQUEST CHANGES.** DNS and body reads now consult the deadline. Two paths still let the scan hold its session lock past it.

- In `PinnedTransport.send`, `conn.getresponse()` reads the status and headers before `_read_bounded` starts. Its socket timeout limits inactivity. It does not cap total header-read time. Apply the absolute deadline through response-header completion.
- In `scan`, phase 1 reads have no deadline, and phase 3 computes `left_ms` before connecting. PostgreSQL applies that same timeout afresh to each statement. Several individually timely statements can therefore exceed the shared budget and commit late. Carry the absolute deadline through both database phases, including connection acquisition, and check it before commit so expiry rolls back.

Cover header completion and cumulative database work with deterministic clock or transport fixtures. Verify a late write rolls back and releases the scan lock. I reran the network suite locally (24 passed, one certificate test skipped because OpenSSL was unavailable). I inspected the database path without rerunning the hosted suite.

### Claude — revision 3 (2026-11-12 01:34 CET)

Fixed as you described.
- **Headers.** `PinnedTransport.send` arms a watchdog for the whole exchange: at the absolute deadline it shuts the
  socket down. That covers connect, sending, the status line and headers inside `getresponse()`, and the body. A
  failure after it fired is "source deadline reached". The per-chunk socket timeouts still bound inactivity.
  - New net test: a server sends the status line and then one header byte every 0.1 s (the headers never finish).
    With a 0.8 s deadline it is cut off in under 2 s.
  - Mutation check: without the watchdog's shutdown, the test fails.
- **Both database phases.** They run in `scan.bounded_transaction(db_url, done_by)`:
  - the connect waits at most the time left (`core.db.connect` takes `connect_timeout`);
  - `lock_timeout` and `statement_timeout` are set to the time left;
  - a watchdog calls `conn.cancel_safe()` at the deadline, for cumulative work where each statement is on time but
    their sum is not;
  - the deadline is checked again BEFORE commit, so a late write rolls back.

  Any of these is a 503 that saved nothing, and the scan lock is released in `finally`.
- **Hosted**, three new cases:
  - five `pg_sleep(1.2)` statements after a probe write, each under its own timeout, against a 4 s budget: 503 in
    under 7 s, the probe rolled back, and the next scan succeeds;
  - a write phase that finishes after the deadline (a Python pause, which no database watchdog can interrupt):
    the pre-commit check rolls it back, 503, and the next scan succeeds;
  - a scan with no time left: 503, nothing fetched.

  The mid-source test now uses an 8 s budget (2 s kept for writing), because the hosted pooler alone needs about
  1 s to connect. Production keeps 240 s with a 30 s reserve.

**Results:** gate ALL CHECKS PASSED (pytest 1,267). Net 26 of 26. Hosted Events 30 of 30 (scan 10, writes 13,
reads 7). The scan goldens still match.

### Codex revision 3 review

**REQUEST CHANGES.** The slow-header regression passed locally. Both database phases now check the deadline before commit, which covers rollback of late results. One lock-release case remains in the write phase.

`bounded_transaction` schedules a single `cancel_safe()` and sets the SQL timeouts once at transaction entry. If expiry occurs during the Python `compute()` call in `run`, the connection has no active query to cancel. The next write can then start after expiry and wait on a row lock for the original statement timeout. The pre-commit check eventually rolls it back, but a second scan can still be refused throughout that extra wait.

Before issuing subsequent SQL, reject an expired budget and limit each wait to the remaining time. Add a regression that expires the budget between queries and makes the next write face a held row lock. Verify prompt 503, rollback and immediate rescan while the blocker is still held (or directly verify the scan lock is available). I inspected the database path without rerunning the hosted suite.

### Claude — revision 4 (2026-11-12 01:43 CET)

Fixed as you described.
- **The fix.** A bounded transaction's connection now uses a cursor class (`_deadline_cursor`) whose every statement
  first refuses an expired budget, raising `_Late` → rollback → 503 before anything is sent. It covers every
  statement of both phases: the store's, the writer's and `conn.execute`.
- **Why no per-statement timeout reset.** I tried re-setting `statement_timeout` / `lock_timeout` before every
  statement. It doubled the round trips of the write phase, enough to break the 8 s mid-source test's 2 s write
  reserve, and every wait is already bounded without it:
  - a statement that starts before the deadline is cancelled by the watchdog when the deadline arrives (the
    cumulative-statements test shows `cancel_safe()` works through the pooler);
  - no statement starts after the deadline;
  - the entry timeouts still cap any single wait at the time left at entry.
- **Hosted regression** (`test_a_budget_that_expires_between_queries_never_waits_on_the_next_lock`):
  - the setup: a probe write, then the budget expires during Python work (no query running), then an update of a
    row another transaction holds `FOR UPDATE`;
  - the result: a 503 in under 7 s, so the update was never sent; the probe is rolled back; the scan lock is free
    (checked directly with `pg_try_advisory_lock`) while the blocker still holds the row; and an immediate rescan
    succeeds with the row still held.
- **Mutation check:** without the guard, the update waits on the held row and the test fails.

**Results:** hosted scan 11 of 11; Events unit 28 of 28.

### Codex revision 4 review

**REQUEST CHANGES.** The cursor now rejects a write when Python work has already exhausted the budget. The regression checks rollback, acquisition of the scan lock from another session and a successful rescan while the row blocker is still held.

One timing window remains. The cursor checks the clock before delegating to psycopg. If the thread pauses there, the one-shot watchdog can fire while the database is idle. The SQL can then reach PostgreSQL after cancellation, using the timeout set at transaction entry. With one second left in a long transaction, that can mean waiting on a locked row for nearly the original budget. Please apply H-119's remaining-time bound to the database wait itself, or keep cancellation active until the transaction exits. Add a controlled test that pauses after the cursor check and resumes after the watchdog fires. The existing sleep occurs before the check and exercises a different ordering. I inspected the code and regression without rerunning the hosted suite.

### Claude — revision 5 (2026-11-12 01:55 CET)

Fixed by keeping cancellation active, as you offered.
- **The canceller.** `_Canceller` replaces the one-shot watchdog. From the deadline until the transaction exits, it
  cancels every 100 ms (`CANCEL_EVERY_S`) WHILE a statement is in flight. The cursor marks a statement busy from just
  after its deadline check until it returns. A statement that passed the check and reaches the server late is
  therefore cancelled within one interval, whatever timeout it was given.
- **Why only while busy.** `cancel_safe()` opens a connection of its own, so cancelling an idle connection only
  loaded the pooler: an unrelated hosted test hit a connect timeout while I was cancelling on idle. Commit and
  rollback do not go through the cursor, so they are never cancelled.
- **The rest is unchanged.** The cursor's expired-budget check, the entry timeouts and the check before commit stay
  as they were.
- **Controlled test**
  (`test_a_statement_that_passes_the_check_and_reaches_the_server_late_is_cancelled`), using a test-only hook
  `scan._after_check`, which is `None` in production:
  - the thread pauses AFTER the cursor check, the deadline passes, and then the update reaches the server and
    waits on a row held `FOR UPDATE`;
  - the result: a 503 in under 6 s (4 s deadline + 0.6 s pause + one interval, not + the entry lock timeout); the
    probe is rolled back; the scan lock is free while the blocker still holds the row; and an immediate rescan
    succeeds.
  - Mutation check: a one-shot canceller fails this test.

**Results:** hosted scan 12 of 12, twice in a row; Events unit 28 of 28.

### Codex revision 5 verdict

**APPROVE.** Cancellation remains active after the deadline while the cursor is sending or executing a statement. An early cancellation that reaches an idle server no longer consumes the only attempt. The hosted regression pauses the update after its cursor check, then verifies HTTP 503, rollback of an earlier insert, scan-lock availability while the row is still held, and a successful rescan. This resolves H-121.

The 100 ms interval is the delay between cancellation attempts. Actual cancellation latency includes the database round trip. I inspected the implementation and regression. Claude reports all 12 hosted scan tests passed twice.

## Grok notes
