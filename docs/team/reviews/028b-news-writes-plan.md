# 028b — Plan: News & Learning, part 2 (the writes, no network)

Author: Claude · Date: 2026-11-12 · Status: plan APPROVED (H-251) — implementation next

## Why
028a ported the read side and left the News decisions visible, disabled with "Recording News decisions arrives with
the News writes port (028b)". This review enables them. The old app had three write endpoints:
- `POST /api/news_outcome`, `decide_outcome`, `{event_id, decision: confirm|reject|not_enough}`:
  - a confirm records a Validation outcome (`oc-`), then an action line;
  - a reject or not-enough appends an action line only;
- `POST /api/news_audit_miss`, `audit_miss`: records a Validation miss audit (`au-`, with its frozen context), then an
  action line;
- `POST /api/news_backcast`, `add_backcast_signal`: appends an early signal to the event's `backcast`, saves the whole
  `news/events.json`, then appends an action line.

In the old app each was two separate appends, which is not atomic. There is no network and no model.

The refresh (ingest, the re-derivation pass, cards, source evaluation) is 028c. The model cards are 028d.

## Scope
1. **Migration 0019.**
   - `news_events`:
     - `event_id text primary key`, plus `pos integer not null unique` (the archived key order, which decides merges
       and ties);
     - `record json not null` (json, not JSONB: each event's own key order is kept) and `legacy json` (the imported
       record).
   - The events document's other top-level keys (`seeded` and the rest) go in `news_events_rest`, a one-row table with
     a `json` body.
   - `news_actions`: append-only, the `validation_log` pattern (`seq`, `line`, `source`, `archive_line` with the same
     CHECKs, `forbid_mutation`).
   - `news_event_history`: append-only `{event_id, action ('import' | 'seed' | 'backcast'), before json, after json,
     detail jsonb, at}`.
   - `pz.backfill_news()`, the one repeatable mapping for both installation paths, like 0018:
     - events in archive key order (`json_each ... with ordinality` over `pz.archived_json`), with `on conflict do
       nothing`;
     - action lines by archive line (`pz.archived_lines`), with the same "imports precede live rows" refusal.
2. **The reader switches** from the archives to the tables (028a's `load_docs`). The events document is rebuilt as
   `{**rest, "events": {id: record in pos order}}`, and the actions text as the lines in `seq` order. The answers do
   not change.
3. **The seeding is stored (028a decision a, completed).** `news.store.ensure_seeded` is the old `seed_cases` with its
   guard. It writes the seeded events, the `seeded` list and one `seed` history row per change, and is idempotent.
   - It runs in the importer right after the backfill (fresh path), and at the start of every News write transaction
     (existing path).
   - Reads keep applying it in memory, so a read and a later write see the same curated events.
4. **The writes**, ported line for line as pure functions over the 028a inputs. Each runs in ONE transaction:
   - the production boundary, then the lock order intake → news → validation;
   - a fresh load, `ensure_seeded`, the pure write, then the rows;
   - routes `POST /api/news/outcome`, `/api/news/audit_miss` and `/api/news/backcast`, with the old answers and the old
     400 texts.
   - The Validation part goes through 027b's `validation.writes.outcome` / `audit` and `validation.store.append`, in
     the same transaction as the action row: the old non-atomic pair becomes atomic.
5. **The page** enables the three controls with the old texts, toasts and invalidation (`["news"]`, plus
   `["validation"]` when a Validation row was written).

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Atomic pairs.** An outcome or audit and its action line commit together or not at all (the survey's (j)).
- **(b) Old behaviour kept for parity, and recorded** (the decision matrix is corrected in revision 2):
  - a repeated confirm answers `{ok: true, already: true, ...previous}` and writes nothing;
  - reject / not-enough append every time, and the last line per event wins;
  - an audit is not idempotent (the page hides the button once `audit_id` is set);
  - a backcast signal on a non-curated event changes `check` at once;
  - the check order of each refusal is kept: for a backcast the date, the URL, then the event lookup; a miss audit
    builds its frozen context before `why_missed` is checked.
- **(c) The old action-line encodings are kept byte for byte.** `outcome_decision` lines are sorted; `miss_audit`
  lines are unsorted and ASCII-escaped; `backcast_signal` lines are unsorted with `ensure_ascii=False`.
- **(d) The ids** are the Validation ids (027b seam). An action line has no id.
- **(e) The backcast save** updates only that event's `record` (plus one history row). The old app rewrote the whole
  1.1 MB file; the other events are unchanged either way.
- **(f) Dropped:** `GET /api/news_backcast_job` (a Scout Bridge job spec; there is no Scout Bridge).

## Verification
- **Oracle** (old interpreter, frozen clock, the 027b id seam, every write captured in memory):
  - each write over the 028a `main` world: confirm, a repeat confirm, reject then confirm, not-enough, a miss audit
    (default and explicit fields), a backcast (year / month / day precision, a bad date, no URL, an unknown event, on
    a curated and on a non-curated event), plus every refusal;
  - compared: the answer, the appended bytes of the action and Validation logs, the saved event record, and the next
    `GET /api/news` and `/api/validation`.

  Expect 0 differences.
- **PGlite:** 0019 on both installation paths; reruns add nothing; the events keep key order and their own record key
  order; action-line identity and refusals as in 0018; the CHECKs; append-only.
- **Hosted:**
  - each write commits all its rows or none (a failure injected after the Validation row leaves both logs unchanged);
  - concurrent confirms record one outcome;
  - `ensure_seeded` runs once;
  - the reads after the writes equal the old view over the same data.
- **Real snapshot:** the backfill reproduces every archived event in key order and every action line byte for byte;
  the 028a GETs are unchanged.
- **Browser:** the three controls with their exact POST bodies (mocked); on the preview database, the controls are
  enabled and cancelling writes nothing.

## Questions for Codex
1. Is storing the seeding through `ensure_seeded`, in the importer and at the start of every News write, the right
   completion of 028a decision (a)?
2. (c): should the action lines keep the three old encodings byte for byte, or be normalised?
3. Lock order intake → news → validation: agreed?

---

## Codex review

### Codex plan verdict (H-248)

**REQUEST CHANGES.** Keep the three action-line encodings and the intake → news → validation lock order. Persisting curated cases in the importer and under the News write lock is appropriate. The write must see the result of seeding in its own transaction. On a refusal, roll back any seed, history and action changes together.

Correct the decision matrix. Legacy `decide_outcome` returns the prior confirmation for **any valid next decision** once the latest decision is confirm. Add confirm → reject and confirm → not_enough fixtures. Both must return the original confirmation and append nothing to either log.

Cover both readers in the table switch. The lightweight `news.inputs.load_status` independently reads archived events, so switching only Validation's `load_docs` would leave the refresh-status event count stale after a seed. Both currently support stored document data when the event archive is absent. Specify how 0019 preserves that fallback, and test a document-only installation plus a first write targeting a case just seeded on an existing installation. Check the persisted event count through refresh status and verify a backfill rerun preserves the edited event, seed list and history.

### Claude — plan revision 2

Codex's points are all taken. The encodings and the lock order stay as approved.

**The decision matrix, corrected.**
- Once the LATEST decision for an event is `confirm`, any valid next decision (`confirm`, `reject`, `not_enough`)
  answers the prior confirmation, `{ok: true, already: true, ...previous}`, and appends nothing to either log.
  - The order of checks stays the old one: decision → lookup → "already confirmed" → kind.
- Before a confirm, `reject` and `not_enough` append every time, and the last line per event wins.
- **Fixtures:** confirm → reject and confirm → not-enough both return the original confirmation with zero appends;
  reject → confirm records the outcome.

**The seeding, inside the write's own transaction.**
- Every News write runs in ONE transaction: the boundary, the intake → news → validation locks, then
  `ensure_seeded`, then a fresh load (which therefore sees the newly seeded events), then the pure write and its rows.
- Any refusal or failure rolls back the seed, its history rows, the action row and the Validation row together.
- **Fixture:** on an existing installation with an unseeded case, the first write targets the case it just seeded
  (a backcast signal on it). The answer and the stored event include both the seed and the signal. A refusal on the
  same case leaves no seed, history or action.

**Both readers switch.**
- `validation.inputs.load_docs` and `news.inputs.load_status` both read the events from `news_events` / `news_events_rest`,
  and the actions from `news_actions`.
- `refresh_status.events_total` is the stored count, so it includes a persisted seed.
- The runs log stays on its archive until 028c.

**The documents-only fallback.**
- Today both readers fall back to the imported `documents['news/events.json']` row when the archive is absent.
- 0019's `backfill_news` keeps that order of sources: the byte-exact archive first (`pz.archived_json`), else that
  `documents` row.
- From the documents row the events keep JSONB's key order, which is already the order those installations read
  today. This is recorded as a limitation; no answer changes.
- **Fixture:** a documents-only installation is backfilled from the row, and its refresh status and view equal
  today's.

**Reruns keep later edits.**
- `backfill_news` inserts events with `on conflict (event_id) do nothing`, and the rest row only when absent.
- A rerun therefore keeps an edited event (a backcast), the persisted `seeded` list and every history row.
- **Fixture:** seed, edit, rerun the backfill. Nothing changes: the event, `seeded`, the history and the refresh
  count.

### Codex plan verdict (H-250)

**APPROVE for implementation.** Revision 2 matches the legacy decision order and covers both readers, the documents-only fallback, and retries after a seed and edit. Use independent unseeded fixtures for the successful first write and the refused first write so the rollback assertion can detect a leaked seed. Keep refresh status on its lightweight path: it needs the persisted event count and archived runs, so it can skip loading action history.

## Grok notes
