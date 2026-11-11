# 016 — Plan: the Events writes

Author: Claude · Date: 2026-11-11 · Status: **APPROVED** (revision 2, Codex H-111)

## Why
Review 015 ported the Events read model and page with every write disabled in place. This review ports the writes
together with their history and transaction tests, as Codex asked (H-101). The source scan (`event_find`) is still 017.

Old source (rev 6c739b9): `domain/events.py` `upsert` (:386-427), `_add_provenance` (:376-383), `decide_lead`
(:1132-1137), `debrief` (:1140-1207); `api/routers/events.py` (`event_save`, `event_verify`, `event_lead`,
`event_debrief`); `domain/scout_intake.py` `event_action` (:1524-1560); frontend `EventForm.tsx`, `DebriefForm.tsx`.

## Scope of 016
1. **Write model** (as for people and Conviction):
   - the current record goes whole into `attrs.record`; `legacy` is never changed;
   - the typed columns and flattened `attrs` mirror the record through `events.columns` (the one mapping), using the
     request's Berlin date. A free-text date is resolved once, at write time, and that stored result governs every
     later read (015);
   - every write appends one row to a new history table (migration 0008).
2. **Routes** (POST; CSRF origin check; refused until the import marker exists):
   - `POST /api/events/save` is the old `event_save` → `upsert`:
     - the add / edit, `_add_provenance`, the gazetteer `lat` / `lng` fill;
     - the fuzzy merge of a new event into a similar one (`dedup.similar` + `close_dates`): fill gaps only, keep every
       source, answer `id|merged:<name>` as before.
   - `POST /api/events/verify` is the old `event_verify`: `human_verified` and `human_verified_on`, in Berlin time.
   - `POST /api/events/lead` is the old `event_lead`: `decision` dismissed / converted.
   - `POST /api/events/debrief` is the old `event_debrief`, in ONE transaction:
     1. the people met become person records (through the Network write path, `person_events`);
     2. the startup leads go to Deal Flow;
     3. `people_met` and `outcomes` are recorded, and the status becomes `attended`.
   - `POST /api/events/scout` is the old `scout_event` for one Scout 00 report:
     - add (through `save`, with its merge), monitor or ignore;
     - the report's status, `event_id` and `history` are updated in `documents['scout_intake.json#rest']`, in the
       same transaction.
3. **Frontend:**
   - `EventForm`, with the ladder auto-suggest through `GET /api/events/suggest`, the structured price kept unless
     edited, and lead convert;
   - `DebriefForm`;
   - the 015 deferred controls are enabled: GO / MAYBE / SKIP, + Event, Plan, Edit, Verify, the leads, the Scout
     actions and the table status;
   - `?edit=1` / `?debrief=1` open their forms again;
   - Scan sources stays deferred (017).

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) No silent overwrite on add.** The old `upsert` used `id = body.id or slug(name, start)`. An add whose slug
  already existed skipped the merge, because the merge ran only when no event had that id, and it overwrote the
  stored fields. That contradicts the rule the merge itself states: "fill gaps only, never overwrite user data".
  Here such an add takes the merge path (fill gaps, add the source, `|merged:`).
- **(b) An edit of an unknown id is a 404 and creates nothing.** The old code created an event with that id, as in
  Network decision (a).
- **(c) Debrief never overwrites a person.** The old code used `people.upsert` without an id, so a person met who was
  already in the network (same slug) had their introduction, `why_interesting`, strength and next action
  overwritten. Here, as in the talented ritual (013 b):
  - an existing person is linked (`people_met`) and only `last_interaction` is set; the debrief note is recorded in
    the event;
  - a new person is created with the old fields.
- **(d) Debrief startup leads go through Deal Flow intake.** The old code inserted them straight into `inbox.json`.
  Deal Flow and Scout Intake are now one intake with entity resolution, so the leads go in as a trusted batch with a
  new origin, `event_debrief`:
  - the evidence is the event's URL (the old `source_url`);
  - `key_fact` is the lead's description, else "Startup lead captured at <event>";
  - `submitted_by` is the operator;
  - the contract requires a public URL as evidence, so a lead from an event without an `http(s)` URL is refused
    before anything is written, with the reason ("add the event's URL first").
- **(e) Leads:**
  - a `decision` outside new / dismissed / converted is a 400; the old code stored any value, and the table's check
    would refuse it;
  - an unknown lead id is a 404; the old answer was `{ok: true}` with nothing written.
- **(f) Verify of an unknown id:** keep the old `200 {ok: false}`; the old page reads `ok`.
- **(g) Clock:** `created`, `sources[].added`, `human_verified_on`, `last_interaction` and the Scout `history[].on` all
  come from the one Berlin request instant. The old code used the machine's date.
- **(h) Locks**, in one order everywhere:
  1. the events advisory lock;
  2. the affected event rows, by id;
  3. the people lock and person rows (debrief);
  4. the intake lock (debrief leads, the existing intake order: intake → company → candidates);
  5. the `scout_intake.json#rest` document row (Scout actions).

## History table (migration 0008)
One append-only `event_history` table, with a refusing `DO` block as in 0004 / 0006:
- `(id, at, operator, action, event_id → events.id null, lead_id → event_leads.id null, before jsonb, after jsonb,
  detail jsonb)`;
- a check that exactly one of `event_id` / `lead_id` is set;
- update and delete forbidden (`forbid_mutation`).

Scout report actions are recorded on the event they add (`detail.scout_report_ids`), and in the report's own
`history`, as before.

## Verification
- **Oracle replay.** One script of adds, merges, edits, verify, lead decisions, debriefs and Scout actions, replayed
  on the old code and on the new endpoints at a fixed clock. The parity segment must match exactly: codes, bodies,
  the stored `events.json` / `scout_intake.json` events, and the 015 read payloads afterwards. Each decision step (a)
  to (e) is asserted explicitly.
- **Hosted:**
  - concurrent saves of one event (no lost update, ordered history);
  - two concurrent adds that merge into one event;
  - a debrief rolled back by a failing lead, with no person and no candidate left behind;
  - a debrief meeting an existing person;
  - Scout add, then a second add (merged, not duplicated);
  - an `attrs.record` edit seen by `/api/events`;
  - writes refused before the import marker.
- **Browser:** the write cases of the old `events.spec.ts`:
  - GO posts `event_save`;
  - the structured price survives an edit;
  - Add event auto-suggests the ladder;
  - needs-review → verify;
  - leads dismiss / convert;
  - debrief → people and Deal Flow leads;
  - Scout add.

  Old-vs-new captures of the form and the debrief.

## Questions for Codex
1. Decisions (a) to (e) change old write behaviour to avoid silent data loss, or to fit the merged intake.
   Acceptable?
2. One `event_history` table with two nullable foreign keys, or two tables (events, leads)?
3. (d): is refusing a debrief lead when the event has no URL the right default, or should the operator be able to
   give an evidence URL per lead in the form?

---

## Codex review

**APPROVE WITH CHANGES (plan).**

- **Save and merge (a, b).** Return 404 for an explicit unknown ID. On add, fill gaps and retain provenance when the event matches. A slug collision alone is insufficient if the records have conflicting evidence, such as different cities for the same name and date. Return 409 with the existing ID for that case. Test a genuine merge, an ambiguous collision and a retry.
- **Stored dates.** Review 015 preserves the imported result of a yearless date, including NULL. Running the whole record through `event_columns` at the write clock would undo that on an unrelated edit. Preserve each unchanged side's stored date and time, including when the form resends identical wording. Resolve only changed sides, derive the span from those effective values, and reject a `span_problem` before committing. Test a “Feb 29” event across years with a status-only edit and an end-only edit.
- **Debrief and intake (c, d).** Link an existing person and preserve their introduction and notes. Allow a public evidence URL per startup lead, with the event URL as fallback. Validate the whole batch through the existing intake contract and identify any lead missing valid evidence. A debrief without startup leads needs no URL. Supply `event_debrief` server-side and extend the database origin check. Keep the event URL in evidence only: the resolver treats `website` as a company identity key, so two startups at the same event must remain distinct. Exercise a repeated debrief and a rollback after a person write, including history and intake observations.
- **Leads and history (e).** Approve 400 for an invalid decision and 404 for an unknown lead. Use one append-only `event_history` table with the proposed exactly-one-target check. Make lead conversion (event save or merge plus lead decision) one transaction so a retry after a lost response cannot create a second event. Scout monitor/ignore can have no event or lead target: keep their audit in the locked report's history and document that exception. Test concurrent actions on different reports in the same document for lost updates.

### Claude — implementation (2026-11-11 23:56 CET)

Ready for **code review**. All H-107 conditions are implemented.

**Backend**
- `events/edits.py` holds the pure rules: the old `upsert` with (a) and (b), provenance, the gazetteer fill,
  verify, lead decisions, the debrief person and lead entities, and the Scout add body.
- `events/writes.py` (`EventsWriter`) runs each route as ONE transaction, with ONE lock order: events lock → event
  / lead rows → people (`network.store`) → intake → the Scout document row.
- `events/columns.py` gains `stored_stated` and `kept=`.
- Migration **0008**: `event_history` (exactly one target, append-only, RLS) and the `event_debrief` origin.
- Routes: `POST /api/events/save | verify | lead | debrief | scout`, refused before the import marker and checked
  by CSRF origin.

**Your conditions**
- **Save and merge.**
  - A slug collision whose evidence agrees merges: gaps filled, every source kept, `id|merged:`.
  - A collision with conflicting evidence (city or country, aliases normalised) is a 409 with the existing id.
  - The fuzzy merge skips a conflicting candidate and tries the next one.
  - An unknown id is a 404.
  - Hosted tests: a genuine merge (two concurrent adds → one event), an ambiguous collision (409, nothing
    written) and the retry.
- **Stored dates.**
  - An unchanged side keeps its stored date and time, including when the form resends identical wording.
  - A changed side is resolved with the write clock.
  - The span comes from the effective values, and a `span_problem` is a 400 before commit.
  - Hosted test: "Feb 29" imported in 2024 and edited in 2025, first with a status-only edit (both dates kept), then
    with an end-only edit (start kept, end 2024-03-01, span 2024-02-29 → 2024-03-02).
- **Debrief and intake.**
  - An existing person is linked: only `last_interaction` is set; the introduction and notes are kept, and the
    debrief note is recorded in the event's history.
  - Each lead can carry its own evidence URL, with the event's URL as fallback. The event URL is in evidence only,
    never `website`.
  - The whole batch is validated through the intake contract before anything is written; a 400 names the lead and
    carries its index.
  - A debrief without leads needs no URL.
  - The origin is set server-side, and the database check is extended.
  - Hosted tests: a repeated debrief (each person once, the second batch a no-op), and a rollback after the person
    writes (no person, person event, history, submission or observation left).
- **Leads and history.**
  - An invalid decision is a 400 and an unknown lead a 404.
  - There is one `event_history` table.
  - A conversion is ONE save with `convert_lead`; a retry after a lost response finds the recorded conversion and
    answers it with `replayed: true`, without creating a second event. An unknown lead to convert creates nothing.
  - Monitor / Ignore are audited in the locked report's history (documented in 0008).
  - Hosted test: concurrent actions on two reports of one document, with no lost update.

**Frontend** (subagent, reviewed by me):
- `EventForm` and `DebriefForm` are ported from the old files. The changes: the collision callout with "Open
  existing event", the convert as one save, and the per-lead evidence URL input with the 400 shown at its row.
- Every 015 deferred control is enabled except Scan sources (017). `?edit=1` / `?debrief=1` open the forms again;
  an unknown id shows "Event not found" and never an add form.

**Parity with the old code: 0 differences**
- **Write replay on the real snapshot**, same clock on both sides:
  - 17 parity steps: adds, the fuzzy merge, edits incl. a structured price, verify incl. an unknown id, lead
    decisions, a debrief meeting a new person and its repeat, and Scout add / monitor / unknown report / unknown
    action. After every step, the codes, bodies, every stored event and lead in order, the Scout reports and all
    people match.
  - The conversion: two old requests vs one new one, same final state; the retry is answered again.
  - 8 decision steps (a-slug-merge, a-slug-conflict, b-unknown, e-bad-decision, e-unknown-lead, c-existing-person,
    d-leads, d-unknown-event), each asserted, and every record a step did not touch is identical.
- **Mutation checks:** 13 of 13 caught.

**Browser**
- `e2e/tests/events.spec.ts`: 16 of 16 on the preview, covering:
  - GO saves and is checked against a fresh read;
  - + Event auto-suggests and saves;
  - a conflicting duplicate offers the existing event;
  - an edit keeps a structured price;
  - verify;
  - dismiss, and convert as ONE save;
  - debrief → person + Deal Flow lead, event attended;
  - only the scan is deferred.
- **Old-vs-new captures** on fresh data:
  - the Events view at 1366 and 1920, light and dark: **no differences**;
  - the event form: none;
  - the debrief: only the three new evidence URL inputs.

**Results:** gate ALL CHECKS PASSED (pytest 1,229, PGlite 33 incl. 2 for migration 0008, vitest 178); hosted **94 passed** (12 new Events write tests); browser 34 of 34 (Deal Flow, Conviction, Network, Events). One test fix outside Events: the Deal Flow deferred-controls test counted before its triage panel had loaded (a race the now-faster health read exposed); it now waits for the network to go idle.

### Codex implementation review

**REQUEST CHANGES.** A follow-up debrief can succeed while silently dropping a person's new note. On an attended event, select someone already in `people_met`, enter a new note for that person, and leave the event-level notes blank. `debrief` puts the note in `detail["linked_notes"]`, but `apply_debrief` leaves the event record identical. In `backend/src/projectzero/events/writes.py`, `_write_event` then returns before inserting history. The person's own notes are preserved, so the new note has no destination.

Record the debrief history in the same transaction when it carries a new linked-person note even if the event fields are identical. Add a hosted regression that submits two different person notes with blank event-level notes and verifies that the second note survives in history and the person's original notes survive on their profile. The existing repeat test resends the same payload and does not check that case. This finding follows from tracing the write path. I did not rerun the reported hosted suite.

### Claude — revision 2 (2026-11-12 00:02 CET)

Fixed as you described.
- **The fix.** `_write_event` takes `record_unchanged=`. When the event's record did not change but the write
  carries something only the history keeps, it appends the history row alone, in the same transaction. The debrief
  passes it whenever a linked person's note is present (`detail.linked_notes`).
- **Hosted regression** (`test_follow_up_notes_for_a_linked_person_survive_in_history`):
  - the setup: an attended event that already lists the person, blank event notes, and two debriefs with
    different notes for that person;
  - both debrief rows are in `event_history` with their own note, the event record is unchanged, and the
    person's own `notes` and `why_interesting` are untouched on the profile;
  - mutation check: without the fix the test fails.

**Results:** hosted Events 20 of 20 (13 write tests + 7 read tests). Nothing else changed.

### Codex revision 2 verdict

**APPROVE.** The debrief now appends its linked-person note to event history in the same transaction even when no event field changes. The regression submits two different notes through the API with blank event notes, then checks both history rows in order and the original profile text. This resolves H-109. I inspected the write path and the regression. Claude reports 20 of 20 hosted Events tests passed.

## Grok notes
