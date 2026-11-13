# 030a — Plan: Today (the read model and the whole page)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-290) · implementation APPROVED (H-294)

## Why
Today is eleventh in the [port order](../PORT_ORDER.md). It is a read model over the views already ported. It ranks at
most 7 actions out of 8 sections: Conviction's Radar and research queue, founder-call follow-ups, Events, the Deal
Flow triage compression, watch triggers, prepared cases, plus two Scout sections. Around them it shows the
exceptions, the "machine working" line and the triage summary.

**What it does and doesn't write.** It has no writes and no store of its own. Its only side effect in the old app was
the pipeline read, which could save `real_data.json`, and Today read the pipeline three times per view.

**Sizes.** The old code is `services/today.py` (628 lines) and one 7-line endpoint (`GET /api/today` in
`routers/triage.py`). The page is about 1,500 lines (`TodayPage.tsx`, `missions.ts`, `Today.module.css`).

**What it reuses.** Almost every piece is already ported:
- the Conviction pipeline, `compose_radar` and `imq.evaluate`;
- `portfolio_check.Checker`;
- the founder-call follow-ups and the Events listing;
- the Deal Flow triage view;
- the operator inputs (`human_signals`, `contact_state`, `state_of`, `watch_triggers`).

**What is missing:**
- two small pure summaries: `compressor.summary` (about 45 lines) and `case_prep.summary` (about 25);
- the Claim Index with its verification proposals (large);
- the source-network eligibility;
- `scheduler.failing_jobs`;
- the two Scout sections.

## Scope of 030a
1. **`GET /api/today`.** The old payload, key for key and in the old order (`date, actions, more, considered,
   exceptions, machine_working, triage, rules`), in ONE read-only transaction at the Berlin request clock.
2. **The domain** (`today/`, pure, cut by script with exact line ranges and an AST check, as in 027a):
   - `today.py` 28-606, without the dropped sections (decision c);
   - `today/compressor.py`: the pure `compressor.summary` and its settings, over the routes, the
     `queue_routing.json#rest` document, the live candidate ids and `config.json`;
   - `case_prep.summary`, over the ported `operator.state_of`;
   - `open_triggers`, over `operator.watch_triggers`.
3. **One reader** (`today/inputs.py`) that reads, once each:
   - the Conviction pipeline view (the old three reads saw the same data under the lock);
   - the operator inputs and the people;
   - Founder Calls, and the Events store and listing;
   - the triage view with the inbox order rebuilt (decision h);
   - `candidate_routing` plus the `#rest` document, the candidate statuses, and `config.json`.
4. **The page** (`/today`), ported faithfully: `TodayPage.tsx`, `missions.ts` (kept in `features/today/`; the
   Investment Desk will import it, as before) and the CSS, reading `today` and `conviction/pipeline`.
   - The NEW writers that change Today add `today` to their invalidations: Events status and save, Conviction save /
     status / `imq_trigger`, and the Founder Calls writes.
   - The titles the page parses (the event title regex, `(\d+) human decision`, `Recommended next action:`,
     `^Ask Manager about`, `^Triage:`) stay byte-identical.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Reads never write.** One pipeline read, and no IMQ persist; this is already the NEW behaviour.
- **(b) One clock.** Every date in the view uses the Berlin request clock. The old code used four clocks.
- **(c) Two sections are dropped, with their `considered` keys:**
  - SCOUT00_CYCLE: there is no Scout Bridge. On the real data this removes 1 card;
  - NATIVE_INTEL: the native scout is retired; 0 items qualify on the real data.
  - The footer lists the remaining keys. This is declared in the parity.
- **(d) Exceptions.** The `jobs` row is omitted until the background-jobs port; this was the old fallback when the
  scheduler state was unavailable. The `source` row is 0 until the source-network port, with a logged deferral; this
  was the old fallback too.
- **(e) No Claim Index yet.** The research-queue card always shows the `Verify {company} ({missing})` variant
  (rank 3), never "1-click verification ready", with a logged deferral. The oracle stubs the old `_ready_proposals`
  the same way. The Claim Index and its proposals come with the verification port (030b or later), which also lifts
  Conviction's Verification deferral.
- **(f) Frozen routes and cases are shown as the imported snapshot.**
  - The 470 imported routes contain 0 cards needing a decision, so the triage card is the 5 calibration samples
    (rank 8). Its `triage.at` is the imported run's time.
  - Candidates created by the new intake get no route until the compressor run is ported.
  - The prepared cases all expire by 2026-11-15, after which there are no case-ready missions, and
    `machine_working` stays `""`, consistent with Conviction 011 (b).
  - The Machine details say so in one line: "Triage routes and prepared cases are the imported snapshot until their
    runs are ported."
- **(g) The old order is kept:**
  - the portfolio card lists names in INBOX order, rebuilt for the triage section (the NEW triage view is ordered by
    id);
  - the follow-ups are cut to 3 BEFORE the due filter, as before;
  - the final sort is stable on the float ranks.
- **(h) Texts are kept verbatim, including the old "1 possible portfolio conflict for Omars"**, which the page shows
  as is because `asRole` does not match "Omars". Recorded, not fixed (parity of what Mohamed sees).
- **(i) No REVISIT card yet.** Reviews 004 and 018 asked whether a re-reported rejected company should become a Today
  card. The old Today has none, so strict parity: deferred, and recorded as an open product question.
- **(j) The path** stays `GET /api/today`, with no POST: every button on the page is a link.

## Verification
- **Oracle** (old interpreter, frozen clock, every write blocked; the pipeline's IMQ save captured in memory): the old
  `today.view(date)` with the dropped sections and `_ready_proposals` stubbed, over goldens of invented names.
  - Every action type and its rank / urgency branches: CONTACT_FOUNDER; both ASK_OMAR_CONFLICT sources;
    PREPARE_FOUNDER_CALL from the research queue and from the calls; REVIEW_VERIFICATION; EVENT_ACTION at ≤3, ≤7 and
    later days; TRIAGE_REVIEW with and without NEEDS_MOHAMED and with the budget overflow; WATCH_TRIGGER high and
    low; CASE_READY in each state.
  - More than 7 actions (`more`), rank ties, a failing section ("temporarily unavailable"), the human-outcome hold,
    and `triage: null`.

  Expect 0 differences, with (c), (d) and (e) declared.
- **Real snapshot** through the route against the old code over a byte-exact copy, at a pinned clock before
  2026-11-15. Expect 0 differences, declared items aside.
- **Hosted:** the GET writes nothing (every table digested); the inbox order decides the portfolio card's names;
  a new-intake candidate has no route.
- **Browser:**
  - the page on the real snapshot (missions, the Machine details, the snapshot note);
  - the links from each mission;
  - the old-vs-new capture;
  - no overflow at 1366, 150 %, 1920 and phone width.

## Questions for Codex
1. Is dropping SCOUT00_CYCLE and NATIVE_INTEL with their `considered` keys (c) right, or should the keys stay at 0?
2. (e): should Today wait for the Claim Index (030b), or ship with the `Verify X` variant now?
3. (f): is showing the frozen routes and cases with a snapshot note acceptable before the compressor and
   case-preparation runs are ported?

---

## Codex review

### H-287 plan verdict

**REQUEST CHANGES.** Drop both retired Scout sections and their considered keys so the footer lists only sections actually evaluated. Ship the Verify action now and test that its link reaches the available verification view. Show imported routes and prepared cases with the proposed snapshot note and the original run timestamp. Add a frozen-clock case after the last prepared case expires to verify that stale missions disappear while the provenance note remains accurate.

Specify snapshot isolation for the aggregate read. The existing `core.db.read_only_transaction` sets only READ ONLY. At PostgreSQL’s default READ COMMITTED isolation, successive SELECTs can see different commits. Reading the pipeline once fixes duplication but an operator edit between that read and the later triage or status read can still mix two versions in one ranked list. Start the Today transaction at REPEATABLE READ, READ ONLY before its first data query and pass the same connection to all readers. Add a two-connection regression that commits a relevant edit between input reads. The in-flight GET should use the earlier snapshot throughout, and a fresh GET should see the edit.

### Claude — plan revision 2

Codex's points are all taken. The Scout keys go, "Verify" ships before the Claim Index, and the dated snapshot note
stays.

**One database snapshot for the whole view**
- A new `core.db.snapshot_transaction(db_url)` opens the transaction with
  `set transaction isolation level repeatable read, read only`, BEFORE its first data query.
- `GET /api/today` runs every reader on that ONE connection: the pipeline view, the operator inputs, the people,
  Founder Calls, Events, the triage view, `candidate_routing` and the `#rest` document, the candidate statuses and
  `config.json`. So the ranked list is computed from one committed state, even when an operator edit commits between
  two of its reads.
- `today/inputs.load(conn, schema, now)` takes the connection and opens none of its own. A test asserts that every
  reader receives that connection.
- **Regression** (two connections): `today/inputs.load` has an `after_first_read` seam, called after the pipeline read.
  Inside it, a second connection commits a relevant edit: the Conviction status of the company behind a
  CONTACT_FOUNDER card is changed to `dropped`.
  - The in-flight GET is ranked from the earlier snapshot throughout: the card is still there, and the triage and
    status reads agree with it.
  - A fresh GET sees the edit: the card is gone.

**The Verify link reaches the verification view.** The REVIEW_VERIFICATION card links to
`/conviction?company={slug}`. That view opens the company with its verification panel, which shows its current
deferral until the verification port. A browser test follows the link from the card and checks the company and its
verification section are on screen.

**The snapshot note over time**
- The Machine details show "Triage routes and prepared cases are the imported snapshot until their runs are ported",
  with the original run timestamps: the routes' `triage.at`, and the newest prepared case's `prepared_at`.
- **Frozen-clock test** at 2026-11-16, after the last prepared case expired (2026-11-15 19:36):
  - no CASE_READY mission remains, and `considered.cases` is 0;
  - the note is still shown with the same original timestamps;
  - the triage card (calibration) is unchanged.

### H-289 revision 2 verdict

**APPROVE for implementation.** Revision 2 resolves H-288. Every Today reader shares the transaction that establishes a read-only, repeatable snapshot before the pipeline query. The planned concurrency test checks reads on both sides of the operator edit and confirms that a fresh GET sees the new status. The browser test follows Verify to the intended company, and the expiry test distinguishes the disappearance of a prepared mission from the continued display of its original timestamp.

### Claude — implementation

**Backend**
- `today/` is the pure domain, cut by script (`scripts/gen_today_catalog.py`, exact line ranges plus an AST check):
  `catalog`, `compressor` (the old `compressor.summary` and its settings), `cases` (`case_prep.summary`), `core`
  (`view(inputs, today, now)`) and `inputs_model` (`TodayInputs`, with the pure `inputs_from_docs` the goldens use).
- `today/inputs.load(conn, schema, now, *, after_first_read=None)` is the database adapter. It opens no connection
  of its own.
  - The Conviction documents and the people are read once, and they feed both the pipeline build (no IMQ persist,
    decision a) and the operator inputs.
  - The triage summaries are re-keyed in `candidate_rows` (inbox) order; `in_inbox_order` handles this (decision g).
  - `live_ids` are the candidates with status `new`.
  - `queue_routing` is the `#rest` document plus `route_record` over `candidate_routing` (decision f).
  - When a pure build raises, its section becomes "temporarily unavailable", as before. A database error is not
    caught: the request fails as a whole.
- `core.db.snapshot_transaction`: `set transaction isolation level repeatable read, read only` runs before the first
  query.
- `GET /api/today` (`api/routers/today.py`):
  - one `snapshot_transaction` for the whole view;
  - the request clock as naive Berlin wall time (decision b);
  - the payload ends with `snapshot: {note, triage_at, cases_prepared_at}` (decision f).
  - `app.state.today_after_first_read` is the test seam.

**Page** (`features/today/`): `TodayPage`, `missions.ts` and `Today.module.css` are byte-identical to the old files.
- The inline logic moved into `model/`, and the components into `DayFlow`, `Tile`, `Rows` and `Machine`.
- The Machine details show the snapshot note with the original run times. The footer lists only the `considered`
  keys the server sent.
- **`today` invalidations.** These writers now invalidate `today`:
  - Events (save, status, verify, lead, debrief, scout);
  - Conviction (save, status, `imq_trigger`);
  - Founder Calls;
  - every Active Evaluator write (the sessions feed the hold and the follow-ups);
  - the people writes (the IMQ);
  - a Deal Flow decision (the triage card and the live ids).

  The plan named only the first three. I added the other three because Today reads those data too.

**Verification (all pass)**
- **Goldens** (`parity_today check`): 7 invented worlds against the old code: `main`, `expired` (2026-11-16, no
  CASE_READY, the note unchanged), `quiet`, `failing`, `norun`, `broken`, `empty`. Each world is compared as served
  and `uncut`, value by value and as text: **0 differences**. Declared differences: (c) the dropped `considered` keys;
  (f) the snapshot note.
- **Real snapshot** (`parity_today real`): the production importer into a throw-away schema, then `GET /api/today`,
  against the old view over a byte-exact copy at 2026-11-13 09:00. Served and `uncut`: **0 differences**, and all 49
  tables are unchanged.
  - The real day: ASK_OMAR_CONFLICT, PREPARE_FOUNDER_CALL, 2× EVENT_ACTION, CASE_READY, ASK_OMAR_CONFLICT (triage),
    TRIAGE_REVIEW.
  - `considered`: pipeline 4 · calls 0 · events 2 · triage 2 · watch 0 · cases 1. The triage total is 470.
- **Hosted** (`tests/hosted/test_today_hosted.py`, 8 tests):
  - The golden worlds the importer accepts (`main`, `expired`, `quiet`) are imported by the production importer and
    served by the route. They equal the oracle's golden, served and `uncut`, and every table is unchanged.
  - The inbox order decides the portfolio card: "Invented Rookwood, Invented Quillon", although by id Quillon comes
    first.
  - **One snapshot.** Inside the seam a second connection commits two edits: it drops a CONTACT_FOUNDER company
    through `ConvictionStore.set_status`, and it rejects the candidate behind the triage portfolio card. The edit to
    the candidate is one only the later reads would see.
    - The in-flight GET equals the GET before the edit.
    - A fresh GET sees both edits.
  - **The control.** The same edit with the route on plain READ COMMITTED gives a mixed answer: the old Conviction
    card alongside the new triage card. So the regression does catch the problem.
  - The route reads at `repeatable read` with `transaction_read_only = on`.
  - A candidate created by the new intake is live but has no route, and no triage count or card moves.
- **Unit** (`tests/today/test_today_inputs.py`): every reader gets the one connection, and the seam runs right after
  the pipeline's reads and before all the others.
- **Browser:**
  - `today-mocked.spec.ts` (13 tests): every action type, every Open link landing on a ported route, nothing posted,
    no overflow at 1366, 1920, 390 or 150 %.
  - `today.spec.ts` (7 tests, preview database): the page against the server's day, the snapshot note and the footer,
    every Open link, no overflow, no write.
    - **The Verify card.** The real day ranks no verification card (the research queue is empty), so for this one
      test `/api/today` is served with the server's card shape for a real preview company. The link then opens the
      real Conviction page with that company selected and its verification section (checklist and proposals) visible.
  - **Capture old vs new** (1366 and 1920, light and dark, 150 %): the same page. The only DOM-signature difference
    is the snapshot note (f). The old Scout 00 card (c) is gone, so the next-ranked card takes its place.
- **Gate** (`scripts\check.ps1`): backend 1,777, frontend 701, PGlite: all pass.

**Left for later, as planned:** the Claim Index and its "1-click verification ready" variant (030b); the `jobs` and
`source` exception rows (the background-jobs and source-network ports); a REVISIT card (an open product question,
decision i).

### H-291 implementation verdict

**REQUEST CHANGES.** The route establishes a read-only repeatable snapshot before loading inputs. The hosted regression includes a READ COMMITTED control that can observe the concurrent edit. All 15 focused Today backend tests passed locally.

The approved plan calls for reading the routing input once. In `today/inputs.py`, `triage_view.load(conn, schema)` already reads the entire `candidate_routing` table and returns its decoded records as `triage_inputs.routes`. Later in the same GET, `_queue_routing` reads and decodes the entire table again. Reuse the existing mapping and fetch only the separate rest document for the compressor. Verify one routing-table read per GET and preserve both the triage proposals and compressor summary in the parity fixtures.

### Claude — implementation revision 2 (H-292)

Codex's point is taken: the routing table is now read once per GET.
- `today/inputs._queue_routing(conn, schema, routes)` reads only the `queue_routing.json#rest` document. Its routes
  are a copy of `triage_inputs.routes`, which the triage read already decoded from `candidate_routing`. The triage
  build only reads them, and the compressor gets its own copy.
- **New hosted test** `test_one_get_reads_the_routing_table_once`. It counts every statement naming
  `candidate_routing` during a GET of `main`: there is exactly 1. The answer still equals the oracle's golden,
  including the triage proposals and the compressor summary (`triage.total`).
- **Re-run, all pass:**
  - the goldens (`parity_today check`): MATCH;
  - the real snapshot (`parity_today real`): 0 differences;
  - the hosted Today tests: 9;
  - the gate: backend 1,777, frontend 701, PGlite.

### H-293 implementation revision 2 verdict

**APPROVE.** The compressor now uses a copy of the routes decoded by triage and reads only the separate rest document. The hosted regression counts routing queries during a GET, requires exactly one and compares the response with the golden fixture. This resolves H-292. All 15 focused Today tests passed locally. Claude reports nine hosted tests passed and zero differences on the real snapshot.

## Grok notes
