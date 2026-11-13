# 030a — Plan: Today (the read model and the whole page)

Author: Claude · Date: 2026-11-13 · Status: plan APPROVED (H-290) — implementation next

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

## Grok notes
