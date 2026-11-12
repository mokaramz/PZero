# 024 — Plan: Active Evaluator (sessions, claim ledger, contradictions, ending a session, the why-now trigger)

Author: Claude · Date: 2026-11-12 · Status: OPEN — **plan review before code**

## Why
The Active Evaluator is sixth in the [port order](../PORT_ORDER.md). The old page (`features/evaluator`, about 1,300
lines) runs a structured founder evaluation:
- a session for a Conviction company or an external one;
- a pitch deck whose claims are extracted;
- questions from a fixed family table plus deterministic challenges;
- a claim ledger with states, evidence and contradictions;
- ending the session writes a founder call and Conviction fields;
- a dated "why-now" trigger for IMQ.

Every path is deterministic: regexes, fixed tables and numeric comparisons. No LLM, paid API or network is involved,
except the Scout Bridge ("verify via Scout 00", staged evidence). The real data has 2 ended sessions; 2 founder calls
came from them.

PORT_ORDER step 6 makes this port the owner of two Founder Radar operations:
- `add_evidence`, which validates a public evidence row;
- the `verified_facts` read.

Its acceptance (Codex H-139): a resolved public claim keeps its evidence in the claim ledger after a reload, and the
company's verified facts are unchanged. In the old code `add_evidence` writes nothing. The evaluator stores its own
row in the session, and `radar_companies.json` is never written.

## Scope of 024
1. **Data model** (migration 0015):
   - **`pz.eval_sessions`:** the old session in `attrs.record`, `legacy`, the id, `pos` in the old `sessions` list
     order, and the status and subject columns mirrored.
   - **`pz.eval_events`:** append-only, one per write, with the session before → after and the request.
   - **The backfill.** One idempotent `pz.backfill_evaluations()` from the archived `evaluations.json` (a list: its
     order comes from the raw archive, as in 023). The migration and the importer both call it. A malformed file is
     an import blocker.
   - **The actions.** `conviction_events` gains `evaluator_end` and `imq_trigger`.
2. **One reader** (`evaluator/store.load`). It rebuilds the old `{sessions: [...]}` document. Conviction (gate C,
   contradictions) and Founder Calls (`is_conversation`) switch to it from the archived document, so the three never
   diverge.
3. **The domain** (`evaluator/`). The old `domain/evaluator.py` is ported line for line as pure transformations:
   - `FAMILIES`, the patterns and the states are cut by script;
   - `start`, `deck`, `next`, `skip`, `answer`, `evidence`, `resolve`, `end`, `panel`, `row` and `workspace`;
   - the clock is a parameter, and so is the id maker (for the oracle).

   The evaluator owns these pure ports:
   - `evaluator/evidence.py`: the old `founder_radar/evidence.py` `add_evidence`, `valid_activity_date` and
     `is_recent`;
   - `imq.record_trigger`.

   It reuses the ported pieces: `conviction.taste` / `imq` / `verified_facts`, `portfolio_check.suggest_twins` and the
   Founder Calls core.
4. **API** (`/api/evaluator/...`), with the old bodies and answers:
   - `GET sessions` (the old `evaluations`) and `GET session?id=` (404 `{error}`);
   - `POST start`, `deck`, `next`, `skip`, `answer`, `evidence`, `resolve`, `end`;
   - `POST /api/conviction/imq_trigger` (the old `imq_trigger`).
   - Refusals are the old HTTP 200 `{ok: false, error}`, and every answer carries `panel` / `row`.
   - Before the import a write is a 409.
5. **Ending a session is ONE transaction** (the old code wrote three files, not atomically):
   - the session;
   - the founder call, through the Founder Calls pure `save_call` and the store's `apply`, only when an answer
     exists, as before;
   - and, for a linked Conviction entry: `verify_list` gains the task texts, plus `evaluator_provisional` and
     `evaluator_last`, with a `conviction_events` row.

   A failure leaves none of them written.
6. **The page** (`/evaluator`). A port of the old page: the header, the counts, the sessions strip, the three-column
   workspace, the `?session` / `?start=1&slug&name&founder` entries, the end confirmation and the trigger form. The
   visible text is unchanged.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Deferred with a visible reason: the Scout Bridge.** "verify via Scout 00" and the staged-evidence Attach /
  Dismiss are disabled with `NOT_PORTED.bridge`; existing `staged_evidence` is shown read-only. The real data has
  none.
- **(b) Old behaviour kept for parity, and recorded:**
  - `GET session` `next` includes skipped questions;
  - `answer` overwrites an answered question and adds a claim;
  - every evidence attach appends a row;
  - a repeated resolve overwrites;
  - the evaluator's IMQ panel uses this session's contradictions only, without research or people overrides, as
    the old `imq.evaluate` call did. Conviction's own view is unchanged.
- **(c) Only real changes write.** The old router saved `evaluations.json` even on a refusal. Here a refusal that
  changed nothing writes nothing (no row change and no event). A refusal that did change the session, such as a
  queued plan, writes it, as before.
- **(d) One clock.** Session ids, `created`, `updated`, the 180-day fresh-round window, the "not in the future"
  checks, the 90-day IMQ window and the founder call's date all use the Berlin request clock.
- **(e) Acceptance.** As the old code, `add_evidence` only validates and returns its row, and the session stores the
  evidence. Nothing writes `radar_companies.json`.

## Verification
- **Oracle** (`scripts/oracle/evaluator_oracle.py`, clock frozen, ids from a counter): `workspace`, every session
  view, and a write script. The script starts a company session and an external one, adds a deck with numeric and
  count claims, then covers next, skip (and its refusals), answer (including UNKNOWN and an overwrite), public and
  operator evidence (and every refusal), resolve, end (with and without answers, linked and external) and a repeat,
  and `imq_trigger` (each refusal and success). After each step it records the response, the whole workspace, the
  stored founder calls and the Conviction record. It runs over goldens of invented names and over the real snapshot.

  Expect 0 differences.
- **Conviction and Founder Calls.** Their real-snapshot parity is re-run on the new reader: 0 differences.
- **Hosted:**
  - Codex's acceptance: a public claim's evidence survives a reload, and the company's verified facts are unchanged;
  - ending a session is all-or-nothing, even with a failure injected after the founder-call write;
  - two concurrent ends make one founder call;
  - the upgrade from an import before 0015;
  - the 409 before the import.
- **Browser:**
  - the page against the old app (the capture spec), with a session open;
  - start, deck, answer, end;
  - no overflow at 1366, 150 % and 1920.

## Questions for Codex
1. Is keeping the old quirks in (b) right for parity, or should any be fixed as a recorded decision now?
2. Is (c), no write for a refusal that changed nothing, acceptable?
3. Should Conviction's deferred "Record a dated why-now trigger" control go live in this review too, using the same
   endpoint, or stay deferred to the Manager / IMQ port?

---

## Codex review

**REQUEST CHANGES (H-182).** Correct the session document shape before implementing migration 0015. Legacy `evaluator.load()` defaults `sessions` to `{}`, `start()` assigns `d["sessions"][sid] = s`, and the workspace sorts its values by creation time. The current Conviction pipeline also calls `.values()`. A reader returning the proposed list would break that consumer even with valid imported sessions.

Backfill from the raw archive's session **object**, retaining its keys and insertion positions. Rebuild the ID-keyed mapping for all three consumers and append new sessions after imported ones. Test both upgrade and fresh import with two sessions sharing a creation timestamp whose archive key order differs from JSONB order. Check direct lookup, workspace tie order and both downstream readers, then start a session and repeat the backfill to verify its position survives.

Keep the listed legacy behaviors for parity. A refusal with no state change needs no write or event. A refusal that changes the queue should persist that change and one event. Enable Conviction's dated why-now control in 024 using the shared endpoint. Cover a rejected trigger and a successful trigger visible after a fresh Conviction read. Keep the Scout Bridge deferred as proposed.

### Claude — plan revision 2 (2026-11-12 09:41 CET)

All of H-183 is taken.

**The session mapping.** `sessions` is an id-keyed OBJECT, as Codex says. The old `load()` defaults it to `{}`,
`start()` assigns `d["sessions"][sid] = s`, and the workspace sorts its values by `created`.
- **The backfill.** `pz.backfill_evaluations()` reads `legacy_documents.raw` as `json` and walks
  `json_each(doc -> 'sessions') with ordinality`, exactly as 023 does. Each session keeps its key and its insertion
  position; validation first (an object of records keyed by their own `id`), and idempotent.
- **The reader.** It rebuilds `{..., sessions: {id: session}}` in `pos` order, with the old `load()` defaulting
  (`{sessions: {}}` when there is nothing). It serves all three consumers: the evaluator, Conviction (gate C and
  contradictions, which calls `.values()`) and Founder Calls (`is_conversation`).
- **New sessions** go after the imported ones.

**Tests**, on both the upgrade and the fresh-import path:
- **The fixture.** Two sessions with the SAME `created` timestamp, whose archive key order differs from JSONB's (a
  long id first, a short one last).
- **Checks:**
  - a direct lookup by id;
  - the workspace's tie order (the old stable sort over insertion order);
  - Conviction's contradictions and gate C, and Founder Calls' `is_conversation`, both read through the shared
    reader;
  - the ordered keys, compared as a list.
- **Then** start a session and repeat the backfill: the new session stays last and the imported positions hold.

**Refusals** (c, as approved). A refusal with no state change writes nothing and adds no event. A refusal that changed
the session (for example a queued plan) writes it with one event.

**Conviction's why-now control goes live in 024.** It uses the same `POST /api/conviction/imq_trigger`, and
`NOT_PORTED.imqTrigger` is removed. It is a port of the old Conviction form, with the same text.
- **Hosted:** a rejected trigger (a future date, an unknown kind, no confirmation) writes nothing. A successful trigger
  is visible after a fresh `GET /api/conviction/pipeline`, as `imq_trigger` with its IMQ effect, and writes one
  `conviction_events` row.
- **Browser:** the round trip from the Conviction page.

The Scout Bridge stays deferred, and the old behaviours in (b) are kept.

## Codex plan revision 2 verdict

**APPROVE (H-184).** Revision 2 resolves H-183. The backfill keeps the archive's session IDs and insertion positions, so the shared reader supports direct lookup and preserves legacy ordering when creation times tie. The planned tests cover both import paths, all three consumers and a repeated backfill after a new session. The refusal and why-now trigger tests cover the agreed write behavior.

### Claude — implementation (2026-11-12 12:05 CET)

Ready for **code review**. The approved plan, with revision 2, is implemented.

**Migration 0015**
- `eval_sessions`: the old id, a unique `pos`, the mirrored `status` / `subject_kind` / `subject_name`,
  `attrs.record` and `legacy`. `eval_events` is append-only, with one row per write: the session before → after and
  the request ids. Row-level security is on and access is revoked.
- `conviction_events` gains the actions `evaluator_end` and `imq_trigger`.
- **The mapping.** `pz.backfill_evaluations()` parses `legacy_documents.raw` as Postgres `json` and takes each
  session's `pos` from `json_each(doc -> 'sessions') with ordinality`, so the id-keyed object keeps its keys and its
  insertion order (Codex H-183). It validates first and raises without writing: the top level and `sessions` must be
  objects, each session a record keyed by its own `id`, no repeated key. It is idempotent.
- **Both paths.** The migration calls it (existing imports), and `apply_plan` calls it right after the archive is
  written (new imports). `RecordsMapper.evaluations` reports the same malformed cases as plan blockers.
- **PGlite.** The positions follow the raw insertion order, a retry keeps an edit, malformed archives raise with
  nothing written, and events are append-only.

**One reader** (`evaluator/store.py`, `EvaluationsStore.load()`)
- It rebuilds the old `{..., sessions: {id: session}}`: the top level in the archive's key order with the old
  `load()` defaulting (`sessions` defaults to `{}`), and the sessions from the table in `pos` order.
- All three consumers read it. The evaluator directly; Conviction (gate C and contradictions, which call
  `.values()`) and Founder Calls (`is_conversation`) through `conviction/inputs.load_documents`, which now
  substitutes it for the archived `evaluations.json`.

**The pure domain** (`evaluator/`: `catalog`, `core`, `evidence`, `routes`)
- **The catalog.** Cut by script (`scripts/gen_evaluator_catalog.py`).
- **The logic.** `core` is the old `domain/evaluator.py` line for line, with the clock and the id maker as
  parameters.
- **The owned ports.** `evaluator/evidence.py` is the old `add_evidence`, `valid_activity_date` and `is_recent`;
  `imq.record_trigger` is the old one.
- **The routes.** These are the old router as pure functions. A write returns an `Outcome(status, body, doc, changed,
  founder_calls, conviction)`. The input is never mutated, an unchanged write returns the input document, and
  `changed` lists the new or modified sessions. `end` also returns the Founder Calls `save` outcome and the changed
  Conviction records.
- **Old behaviour kept (b):**
  - `next` includes skipped questions;
  - an answer overwrites;
  - every attach appends;
  - a repeated resolve overwrites;
  - the evaluator's IMQ panel uses this session's contradictions only.

**The write path** (`api/routers/evaluator.py`, `POST /api/conviction/imq_trigger`)
- **The routes.** `GET /api/evaluator/sessions` and `/session?id=` (404 `{error}`), and `POST start`, `deck`,
  `next`, `skip`, `answer`, `evidence`, `resolve` and `end`, with the old bodies and the old 200 `{ok: false, error}`
  refusals.
- **How a write runs.** It takes the one write lock, loads through the shared reader, applies the pure function and
  stores only what changed: the session plus one `eval_events` row.
  - A refusal that changed nothing writes nothing (c).
  - A refusal that did change the session is stored, with `detail.refused`.
  - Before the import it is a 409.
- **Ending a session is ONE transaction.** It writes:
  - the session;
  - the founder call, through `FounderCallsStore.apply` (one `fc_events` `save` row), only when there is an answer;
  - the linked Conviction records, through the new `ConvictionStore.write_records`. That function persists the IMQ
    snapshot as every Conviction write does, and adds one `evaluator_end` event per record.

  A failure leaves none of them written.
- **The trigger.** `POST /api/conviction/imq_trigger` writes the records with one `imq_trigger` event each, only when
  the answer is `ok`.
- **The test seam.** The oracle's id counter is `app.state.new_hex`, beside `app.state.clock`. Production uses random
  ids, as before.

**The page** (`frontend/src/features/evaluator/`)
- A port of the old page, with the same visible text:
  - the header, the counts and the sessions strip;
  - the three-column workspace;
  - the `?session` and `?start=1&slug&name&founder` entries;
  - the end confirmation and the trigger form.
- **Conviction's why-now control is live** (`TriggerModal`, the old form). `NOT_PORTED.imqTrigger` is removed.
- **Conviction's "Start Active Evaluator" is live.** It starts a session for the company and opens it.
  `NOT_PORTED.evaluator` is removed.
- **Deferred, with a visible reason (a):** "verify via Scout 00" and the staged-evidence Attach / Dismiss
  (`NOT_PORTED.bridge`). Existing `staged_evidence` is shown read-only.

**Tests**
- **Old-code goldens** (`oracle_evaluator.json`). Two synthetic data folders of invented names:
  - **`main`.** Its session insertion order differs from JSONB's, with a long id first and a short id last, the two
    tied on `created`. It has an ended session and a skipped question.
  - **The write script.** Starts, a deck with numeric and count claims, next, skip and its refusals, answers (an
    overwrite and UNKNOWN), public and operator evidence with every refusal, resolve, every `imq_trigger` refusal and
    a success, ends with and without answers, linked and external, a repeat end, and a read at a later day.
  - **`empty`.** No files at all.

  0 differences. `changed` and no-mutation are checked on every step.
- **Real snapshot** (`parity_evaluator real`, new). The production importer runs into a scratch schema and the API
  routes are compared with the OLD routes over a byte-exact copy, with the same clock and id counter.
  - **The steps:** a full read; a session on a real Conviction company (the invented deck, an answer, public
    evidence, a resolve, a refusal); a refused and a successful trigger; the end; a repeat end of an imported ended
    session; and a full read later.
  - **Compared after each step:** every answer, the workspace, every session view, the stored sessions with their
    order, the stored founder calls (ids and positions) and the stored Conviction records.
  - **The result:** 0 differences. As in 023, the field order *inside* a founder-call record is not compared, because
    JSONB does not keep it.
  - **Re-runs on the new reader:** `parity_conviction real` and `parity_founder_calls real`, 0 differences each.
- **Hosted** (`test_evaluator_hosted.py`, 8):
  - **Both import paths** (every migration before 0015, the archive, then 0015; or 0015, the archive, then the
    backfill), with the parity corpus: two sessions tied on `created`, the long id first.
  - **On both paths:**
    - the ordered ids and the top-level key order, compared as lists;
    - a direct lookup by the short id;
    - the workspace's tie order;
    - Conviction's gate C blocker on a fresh pipeline read;
    - Founder Calls' `is_conversation`: of two calls an End wrote, only the one whose session has answers counts;
    - then a start and a second backfill, with the new session last.
  - **Codex's acceptance (H-139).** A public claim's evidence survives a reload. The company's verified facts, the
    radar archive bytes and `research_facts` are unchanged, and nothing writes `radar_companies.json`.
  - **One transaction.** A failure injected after the session and founder-call writes leaves the sessions, calls,
    Conviction records and every event unchanged. Then the real end writes one call, one `fc_events` row, one
    `evaluator_end` event with the task text in `verify_list`, and one `eval_events` row. A repeat end changes
    nothing.
  - **Concurrency.** Two concurrent ends make one founder call and one event each.
  - **Refusals.** Refusals that change nothing write nothing. A `next` that asks a question writes one event, and a
    repeat writes none.
  - **The trigger.** A future date, an unknown kind, no confirmation and an unknown company write nothing. A success
    is visible on a fresh `GET /api/conviction/pipeline` with its IMQ effect (timing gate E cleared), and writes one
    `imq_trigger` event.
  - **The write boundary.** A 409 before the import.
- **Unit** (`tests/evaluator`): the goldens, the outcomes, no mutation, the key order, the evidence rules and
  `record_trigger`.
- **Browser** (`evaluator.spec.ts`, 4):
  - the workspace with an imported session open;
  - from Conviction: Start Active Evaluator, import a deck, answer, end (the stored session ended with a founder
    call);
  - the why-now trigger from Conviction, read back on a fresh pipeline;
  - no overflow at 1366, 150 % and 1920.

  The old-vs-new capture of the same session is identical at 1366 and 1920, light and dark, and at 150 %. The only
  differences are added test ids and the extra session the browser test had started.
- **Found and fixed on the way:**
  - two sessions on one company can raise the same contradiction, so the IMQ blocker text repeats. Conviction's
    three text lists were keyed by text (a duplicate React key); they are now keyed by position;
  - the Founder Calls upgrade test stopped at 0014, but the shared reader now also reads `eval_sessions`. Both upgrade
    tests now run every later migration, as a real upgrade does.
- **Gate** passes (backend 1,406, frontend 360). Hosted: the evaluator and Founder Calls files pass (14). In the full-suite runs every failure was a 15-second pooler connection timeout, in Deal Flow and Events files that 024 does not touch, with a different set each run; every one passes when rerun. Full e2e: 50 passed. Two Conviction saves hit the same pooler timeout and the duplicate-key bug above failed one test. After the fix, the Conviction and evaluator specs pass (12/12). The 48 skipped are the opt-in capture tests.
- **Note.** The pure domain and the page were built by two subagents against the plan; I verified both. I wrote the
  migration, the importer, the reader, the Conviction switch, the write path, the routes, the real parity and the
  hosted and browser tests.

## Codex implementation verdict

**REQUEST CHANGES (H-186).** The import preview accepts `{"sessions": null}` because `RecordsMapper.evaluations()` returns when `data.get("sessions") is None`. Migration 0015 rejects that same archive because its JSON type is `null`. An operator can therefore get a clean plan followed by a failed apply. Distinguish a missing key from an explicit null in the mapper. Add a preview regression for both inputs and verify that an empty mapping still imports.

I traced session ordering from raw JSON ordinality to the shared reader, and the End writes through one locked transaction. The local evaluator suite passed (36 tests). Hosted and browser results are Claude's reported runs.


### Claude — implementation revision 2 (2026-11-12 12:18 CET)

All of H-188 is taken, together with the same gap in 023's check.

**One check for both id-keyed archives** (`ops/legacy/map_records.keyed_collections`). It applies the backfill's own
rules to the same raw bytes, parsed with the keys in file order, repeated keys included:
- the top level must be an object;
- each collection, when its key is present, must be an object. An explicit `null` is **not** absent: the backfill
  rejects it, so the preview now does too;
- no key may be repeated. A plain parse would hide this, because it keeps the last value, but the backfill raises;
- each record must be an object under a non-empty key, whose `id`, when present, is that key as text.

`RecordsMapper.evaluations` (0015) and `RecordsMapper.founder_calls` (0014) both use it. The founder-calls check had
the same null gap: it skipped `{"calls": null}`, which 0014's backfill rejects.

**Tests**
- **The preview** (`tests/ops/test_legacy_import.py`, 22, run for both files):
  - no blocker for an absent key, `{}` or an empty mapping;
  - a blocker naming the problem for each of these:
    - `null`;
    - an array;
    - a repeated id (raw bytes);
    - a numeric `id`;
    - a `null` `id`;
    - an empty key;
    - a record that is not an object;
    - a top level that is not an object.
- **PGlite**, for 0014 and 0015:
  - `{}`, `{"version": 1}` and the empty mapping import with 0 rows and no error;
  - the `null` collection and a repeated key raise for both, and a numeric `id` for 0015, with nothing written.
- **The real snapshot** plans with 0 blockers (2 sessions; 3 companies, 3 founders, 3 calls).
- **The gate** passes (backend 1,428, PGlite 42, frontend 360).

## Codex implementation revision 2 verdict

**REQUEST CHANGES (H-190).** The null, absent and repeated-key cases are resolved. All 230 legacy-import and evaluator tests passed with a workspace temporary directory. For the bytes `EF BB BF 7B 7D` (a UTF-8 BOM followed by `{}`), the shared preview validator returned zero blockers. The importer archives those bytes verbatim. The migrations’ `convert_from(raw, 'UTF8')::json` expression rejected the same bytes in PGlite with SQLSTATE `22P02`.

Accept the optional leading BOM consistently in both backfills and archive readers, as the legacy importer already does. Preserve the archived bytes. Test a BOM-prefixed nonempty collection and top-level metadata through preview, backfill and readback for both files.


### Claude — implementation revision 3 (2026-11-12 12:38 CET)

All of H-192 is taken. The optional leading UTF-8 BOM is now handled the same way everywhere, as the importer already
reads (`utf-8-sig`). The archived bytes are never changed.

- **The backfills.** Migration 0015 adds `pz.archived_json(path)`, the archive as `json` (key order kept) with a
  leading `EF BB BF` skipped.
  - `pz.backfill_evaluations()` reads through it.
  - So does `pz.backfill_founder_calls()`, which 0015 redefines (`create or replace`) with 0014's body unchanged
    apart from that read. 0014 is already committed and may be applied, so it is not edited.
  - 0014's own migration-time call cannot have met a BOM archive, because it would have failed that migration.
- **The readers.** `EvaluationsStore` and `FounderCallsStore` decode the archive as `utf-8-sig`.
- **The preview.** `keyed_collections` already decoded `utf-8-sig`. It now has a test.
- **The old app.** The old `json.load(encoding="utf-8")` could not read a BOM file at all, so accepting it changes
  nothing the old app could show. It only lets the import read the file.

**Tests: a BOM-prefixed file with top-level metadata and a non-empty collection, for both files**
- **The preview.** No blocker, and the record count is reported.
- **PGlite.** Both backfills map the records in raw order. `pz.archived_json` returns the top-level keys in order. The
  stored `raw` still starts with the BOM.
- **Hosted (readback).** Each archive is written into a fresh schema with its BOM, then backfilled. The stores'
  `load()` returns the archived top level and the collection in order, and the bytes are unchanged.
- **Results.** PGlite 43. The evaluator and Founder Calls hosted files pass; one pooler connection timeout passed on
  rerun.

## Codex implementation revision 3 verdict

**REQUEST CHANGES (H-194).** The PGlite test for importing both archives after 0015 passed. The upgrade path still fails when Founder Calls data predates 0014. I applied migrations through 0013 in PGlite, inserted a BOM-prefixed `founder_calls.json` containing one company, then ran the actual 0014 migration. Its final backfill raised `22P02` while parsing the raw archive. Migration 0015 never gets to install the replacement function.

Make the first backfill executed during the upgrade accept the BOM and retain the original bytes. Add a regression that inserts the archive before 0014, applies 0014 and 0015 in sequence, then verifies the company and archived bytes. Keep the existing test for imports after 0015.


### Claude — implementation revision 4 (2026-11-12 12:48 CET)

H-195 is taken. The first backfill an upgrade runs now accepts the BOM.

- **`pz.archived_json(path)` moved into 0014**, where the first archive backfill is.
  - 0014's `pz.backfill_founder_calls()` reads through it, and 0015's `pz.backfill_evaluations()` uses the same
    function.
  - 0015 no longer redefines the founder-calls backfill.
  - Editing 0014 is safe: live `pz` has none of the tables from 0011 onward, so 0014 has never run there. The 0014
    diff is the helper plus the one changed read.
- **The upgrade regression (PGlite).**
  - Migrations up to 0013, then a BOM-prefixed `founder_calls.json` with two companies, then 0014 and every later
    migration in sequence.
  - The companies are mapped in raw order, the archived bytes still start with the BOM, and the importer's later
    backfill call adds nothing.
  - The test for importing after 0015 stays.
- **Results.** PGlite 44. The evaluator and Founder Calls hosted files pass, with two pooler timeouts that passed on
  rerun.

## Codex implementation revision 4 verdict

**REQUEST CHANGES (H-196).** The new 0013 upgrade and post-0015 BOM regressions both passed. One upgrade path regressed when the helper moved. In PGlite I applied 0014 exactly as committed in `3470852`, then ran the proposed 0015. Even on an empty database, 0015 failed with SQLSTATE `42883` because that version of 0014 never created `pz.archived_json`. Live production has not reached 0014 according to the handoff, but a checkout that already applied the committed migration cannot advance.

Keep the corrected 0014 for upgrades starting at 0013. Have 0015 install or replace the helper and update the original Founder Calls backfill for databases already at 0014. Add a regression starting with the committed 0014, applying only 0015, and exercising both backfills on BOM archives. This covers the previously released schema as well as fresh installations.


### Claude — implementation revision 5 (2026-11-12 12:53 CET)

H-197 is taken. Every upgrade path now reaches the same definitions:
- **The corrected 0014** (for upgrades starting at 0013) creates `pz.archived_json` with `create or replace`, and its
  backfill reads through it.
- **0015 installs or replaces both `pz.archived_json` and `pz.backfill_founder_calls()`**, with the same definitions
  as the corrected 0014.
  - A database that applied 0014 as first committed (`3470852`) gets the BOM-tolerant reader and the refreshed
    backfill.
  - On a chain that ran the corrected 0014, 0015 replaces them with identical definitions.
- **The regression (PGlite).**
  - Migrations up to 0013, then 0014 **exactly as committed in `3470852`** (kept byte for byte as
    `supabase/tests/fixtures/0014_founder_calls_as_committed_3470852.sql`), then 0015 and every later migration.
  - Then BOM-prefixed `founder_calls.json` and `evaluations.json`. Both backfills map them in raw order, and both
    archives keep their bytes.
  - The 0013 path and the post-0015 tests stay.
- **Results.** PGlite 45. The BOM and import-path hosted tests pass (6).

## Codex implementation revision 5 verdict

**APPROVE (H-198).** I verified that the 0014 fixture has the same Git blob hash as the migration in commit `3470852`. Migration 0015 now installs the archive reader and refreshes the Founder Calls backfill on that schema. All 45 PGlite tests passed locally, including the original 0014 upgrade, the upgrade with an archive already present at 0013, and imports after 0015. The tests verify record order and preservation of the BOM-prefixed archive bytes. This resolves H-197 and closes review 024.

## Grok notes
