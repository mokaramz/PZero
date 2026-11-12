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

## Grok notes
