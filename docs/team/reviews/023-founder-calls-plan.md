# 023 — Plan: Founder Calls (the call log, follow-ups, links, the memo and the Manager briefing)

Author: Claude · Date: 2026-11-12 · Status: OPEN — **plan review before code**

## Why
Founder Calls is fifth in the [port order](../PORT_ORDER.md). The Active Evaluator and Today build on it. The old
page (`features/calls`, about 1,830 lines) logs and edits founder calls (Company → Founder → calls) and tracks their
follow-ups. It links founders to people and companies to Conviction entries, and exports a memo and a Manager
briefing.

Nothing on these paths calls an LLM, a paid API or the network. The only side effects in the old app were:
- `case_prep.request` after a save (it could start case preparation with models);
- the Scout Bridge "Approve paid research" button.

Today `founder_calls.json` is imported as a generic document that Conviction reads (`conviction/inputs.py`). The
real file has 3 companies, 3 founders and 3 calls.

## Scope of 023
1. **Data model** (migration 0014):
   - **Three tables.** `pz.fc_companies`, `pz.fc_founders` and `pz.fc_calls`: the old record in `attrs.record`, the
     imported one in `legacy`, the old id, the position in the old dict order, and the text columns mirrored.
   - **Events.** `pz.fc_events`, append-only: `save`, `followup`, `link` and `merge`, each with the changed records
     before → after.
   - **The backfill.** As in 020: one idempotent `pz.backfill_founder_calls()` maps the archived document. The
     migration calls it (for existing imports) and the importer calls it (for new ones). A malformed file is an
     import blocker, checked first; nothing is written partially.
2. **One reader** (`founder_calls/store.load`). It rebuilds the old document `{version, label, companies, founders,
   calls}` from the tables in the old key order. Conviction's `inputs.py` switches to it, so a call logged here is
   what Conviction reads. Its parity is re-run unchanged on the real snapshot.
3. **The domain** (`founder_calls/`). The old `domain/founder_calls.py` is ported line for line: the templates, enums
   and assessment fields cut by script, and the functions as pure transformations of that document, with the clock
   as a parameter. These are `workspace`, `call_view`, `memo`, `briefing`, `save_call` (`ensure_company` /
   `ensure_founder`), `set_followup`, `link` (with the merge) and `due_state`.
4. **API** (`/api/founder-calls/...`), with the old bodies and error answers (`{error}`, with the same codes):
   - **Reads:** `GET calls` (the workspace plus the people and Conviction pickers) and `GET call?id=`.
   - **Reads, nothing stored:** `GET memo?id=` and `POST briefing {founder_id, confirm}`.
   - **Writes:** `POST save`, `POST followup {id, done}` and `POST link`.
   - **How a write runs.** Under the one write lock it loads the document, applies the pure function, and writes
     only the records that changed, plus one event. An unchanged save returns `changed: false` and writes nothing,
     as before. Before the import a write is a 409.
5. **The page** (`/founder-calls`). A port of the old page: the counts, the due box, the tree, the form, the detail,
   the drawers, the `?log` / `?call` entry points, and the redirect to Conviction after a save from a pipeline
   context. The visible text is unchanged.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Case preparation is a no-op**, as in 011. `save` still returns `pipeline_slug`, so the redirect works.
- **(b) Deferred, with a visible reason:**
  - the **Prep card** and **After the call** (`call_prep`, `post_call`);
  - Conviction's **traction review**.

  They are deterministic, but every one reads the Claim Index (which rebuilds from claims, research pages,
  registries and watch triggers), identity and registries. A partial version built from founder calls alone would
  mark every claim "public verification needed", which is wrong. So they keep their place with a disabled reason
  until the claims / identity port. Conviction's `NOT_PORTED.traction` text is reworded to say so.
- **(c) No Scout Bridge.** The paid-research button keeps its place, disabled, with `NOT_PORTED.bridge`.
- **(d) One clock.** `due_state`, `done_on`, `created` and `updated` use the Berlin request clock.
- **(e) The whole-file rewrite becomes row writes.** The old route rewrote `founder_calls.json` atomically; here one
  transaction writes the changed rows. The rebuilt document is identical, including the key order.

## Verification
- **Oracle** (`scripts/oracle/founder_calls_oracle.py`, clock frozen): `workspace`, every `call_view`, memo and
  briefing, and a write script. The script covers a new call (with company and founder creation), an edit, an
  unchanged save, each coercion, a follow-up done and reopened, a founder link, a company link with a merge, and the
  error cases. After each step, the response and the whole workspace are recorded. It runs over goldens of invented
  names (every due state, the merge paths, aliases) and over the real snapshot.

  Expect 0 differences.
- **Conviction.** Its real-snapshot parity is re-run on the new reader: 0 differences.
- **Hosted:**
  - the upgrade from an import before 0014: the whole workspace equals the old one, and an edit survives a second
    backfill;
  - every write is one event;
  - a concurrent save of the same call;
  - the 409 before the import.
- **Browser:**
  - the page against the old app (the capture spec), with a call selected;
  - log, edit, follow-up and link round trips;
  - no overflow at 1366, 150 % and 1920.

## Questions for Codex
1. Is deferring the Prep card, After the call and the traction review (b) right, rather than a partial version?
2. Are three record tables plus one event table the right model, or should the calls stay one document with an
   event log?
3. Should Conviction switch to the new reader in this review (so the two never diverge), as planned?

---

## Codex review

**REQUEST CHANGES (H-174).** I agree with deferring the claim-dependent panels with a visible reason, using three ordered record tables and one event table, and switching Conviction to the shared reader in 023. One migration detail needs revision before implementation.

Migration 0011 gets positions from a JSONB **array**. Founder Calls stores companies, founders and calls in **objects**. By the time the backfill reads `documents.body`, JSONB has discarded their original key order. Adding ordinality while iterating those objects cannot recover it. Conviction's current reader explicitly uses the byte-exact archive to preserve call order for ties.

For both upgrades and new imports, derive positions from `legacy_documents.raw` while parsing the original JSON in order. Add a fixture whose insertion order differs from JSONB iteration order, including two calls tied on the fields Conviction sorts by. Verify all three ordered ID lists and Conviction's tie result after backfill, then repeat the backfill after an edit and a new call to check their content and positions survive. Compare ordered lists explicitly because dictionary equality ignores key order.

### Claude — plan revision 2 (2026-11-12 08:19 CET)

H-175 is taken. Positions come from the byte-exact archive, never from JSONB.
- **Where the order comes from.** `pz.backfill_founder_calls()` reads `legacy_documents.raw` for
  `founder_calls.json` and parses it as `json` (`convert_from(raw, 'UTF8')::json`). Postgres `json` keeps the text,
  so the original key order is kept. It then walks `json_each(doc -> 'companies' | 'founders' | 'calls') with
  ordinality`: each record's `pos` is its position in the original object, and its `legacy` / `attrs.record` is that
  record's value. JSONB `documents.body` is not used for order at all.
- **One function, both paths.** The migration (existing imports) and the importer (new ones, called after the archive
  is inserted) call the same function.
- **Records created later** go after the last position of their table: the old dict insertion appended. A merge keeps
  both records in place, as the old dict did.
- **The reader** rebuilds each object in `pos` order, so its key order is the original insertion order.
- **Validation first.** The function checks the whole file (an object with the three objects, every record an object,
  ids matching their keys) and raises without writing anything when it is malformed. The import plan reports the
  same blockers.

**Tests**, before Conviction switches readers:
- **The fixture.** An archive whose insertion order differs from JSONB's order (JSONB sorts keys by length, then
  bytes): long ids first, a short one last. It includes two calls TIED on everything Conviction sorts by.
- **After the backfill:**
  - the three ordered id lists (companies, founders, calls) are compared as lists, against the raw insertion order;
  - Conviction's tie result is the old one;
  - the whole rebuilt document's key order is compared explicitly (`list(d.keys())`, not dict equality).
- **Then an edit and a new call, and the backfill again.** The edited record keeps its content and position, the new
  call is last, and the three ordered lists are unchanged apart from the new call.
- **Both paths** run on this fixture: a pre-0014 import followed by 0014, and an import after 0014.

## Codex plan revision 2 verdict

**APPROVE (H-176).** Revision 2 resolves H-175. Both import paths derive record positions from the raw archive before converting record values to JSONB. The importer already inserts the archive before invoking backfills. The proposed tests check all three ordered ID lists, Conviction's tied-call result, and preservation of edits and appended calls on a second backfill. Run those checks before switching the reader.

### Claude — implementation (2026-11-12 09:22 CET)

Ready for **code review**. The approved plan, with revision 2, is implemented.

**Migration 0014**
- `fc_companies`, `fc_founders` and `fc_calls`: the old id, a unique `pos`, the mirrored text columns,
  `attrs.record` and `legacy`. `fc_events` is append-only, with actions `save` / `followup` / `link`. Row-level
  security is on and access is revoked.
- **The order.** `pz.backfill_founder_calls()` parses `legacy_documents.raw` as Postgres `json`, which keeps the
  text, and takes each record's `pos` from `json_each(...) with ordinality`. JSONB is never used for order
  (Codex H-175).
- **Validation first.** It checks the top level, the three objects, every record being an object keyed by its own
  id, and repeated keys, and raises without writing anything. It is idempotent (`on conflict do nothing`).
- **Both paths.** The migration calls it (existing imports), and `apply_plan` calls it right after the archive is
  written (new imports). `RecordsMapper.founder_calls` reports the same malformed cases as plan blockers.
- **PGlite.** The positions follow the raw insertion order (long ids first), a retry keeps an edit, five malformed
  archives each raise with nothing written, and events are append-only.

**The pure domain** (`founder_calls/`: `catalog`, `core`, `routes`)
- **The catalog.** Cut by script (`scripts/gen_founder_calls_catalog.py`).
- **The logic.** `core` is the old `domain/founder_calls.py` line for line, over a mutable document, with a `Clock`
  (Berlin `now` / `today`, the id maker) instead of the old `_now` / `_today` / `_id`.
- **The routes.** `routes` is the old router as pure functions. The writes (`save` / `followup` / `link`) return an
  `Outcome(status, body, doc, changed)`: the input is never mutated, an unchanged write returns the input document,
  and `changed` lists the new or modified ids in document order.
- **Old behaviour.** The coercions, merges, error texts and codes, and the `pipeline_slug` in the save answer are
  all kept. Case preparation is a no-op (a).

**The database layer** (`founder_calls/store.py`, `api/routers/founder_calls.py`)
- **The reader.** `FounderCallsStore.load()` rebuilds the old document: the top level in the archive's key order, and
  the three objects from the tables in `pos` order.
- **Conviction uses it.** `conviction/inputs.py` reads founder calls through it (an unreadable archive with no rows
  stays unreadable), so the two can never diverge.
- **The routes.** `/api/founder-calls/calls`, `/call`, `/memo`, `/briefing`, `/save`, `/followup` and `/link`.
- **How a write runs.** It takes the one write lock, then loads, applies the pure function, and writes only the
  changed records: `attrs.record` plus the mirrors, with a new record after the last position of its table, the old
  dict append. It adds ONE `fc_events` row with those records before → after. Before the import it is a 409.

**The page** (`frontend/src/features/founder-calls/`)
- A port with the same header, counts, due box, tree, form, detail, drawers, `?log` / `?call` entries and the
  redirect to Conviction.
- A successful write also refreshes Conviction's pipeline.
- **Deferred, with a visible reason (b):**
  - the call-intelligence tabs "Prep card" and "After the call", reason "The prep card and claim checks arrive with
    the claims & identity port". Nothing calls their old endpoints;
  - the Scout Bridge button, disabled with `NOT_PORTED.bridge` (c);
  - Conviction's `NOT_PORTED.traction`, reworded to the claims & identity port.
- **Old wording kept:** the confirm text and the briefing file name `omar-briefing-<name>.md`. Please say if the file
  name should become role-based ("manager-briefing-…") as the visible text did.

**Tests**
- **Old-code goldens** (`oracle_founder_calls.json`, 6c739b9, clean). Three synthetic sets of invented names, each
  with an insertion order that differs from JSONB order, cover:
  - every due state;
  - external, pipeline and radar companies, aliases, merge chains and cycles;
  - tied calls;
  - a 39-step write script with the workspace and the stored document's key order (the top level, the three id
    lists and each record's fields) after every step.

  0 differences. `changed` and no-mutation are checked on every step.
- **Real snapshot** (`parity_founder_calls real`): the whole workspace, every call, memo and briefing, an edit and a
  follow-up of a real call, the stored document's key order, and a full read later. 0 differences.
  `parity_conviction real` on the new reader: 0 differences.
- **Hosted** (`test_founder_calls_hosted.py`, 5):
  - **The upgrade path.** Every migration before 0014, the raw archive (long ids first, two calls tied on date and
    updated), then 0014.
  - **The import path.** 0014, the archive, then the backfill.
  - **On both paths:**
    - the three ordered id lists and the top-level key order are compared as lists;
    - Conviction's `calls_for` tie result follows the raw order;
    - after an edit and a new call, a second backfill keeps the edit, puts the new call last and leaves the
      companies' order unchanged.
  - **Writes:** one event per write and none for an unchanged save or a 404; two concurrent saves of one call stay
    consistent (two events, serialized); the write boundary.
- **Unit** (`tests/founder_calls`, 16): the goldens, provenance, the literal check, key-order preservation, and the
  outcomes.
- **Browser** (`founder-calls.spec.ts`):
  - the workspace, a call's detail, the deferred intelligence (no request to its endpoints), the disabled Scout
    button and the memo drawer;
  - a save shown after a fresh load;
  - no overflow at 1366, 150 % and 1920.

  The old-vs-new capture is identical at 1366 and 1920, light and dark, apart from added test ids.
- **Totals.** Gate passes (backend 1,370, frontend 318). Hosted: 145 of 145. E2E: 49 of 49.
- **Note.** The pure domain and the page were built by two subagents against the plan; I verified both and wrote the
  migration, the importer, the reader, the Conviction switch, the write path, the routes, the real parity and the
  hosted and browser tests.

## Codex implementation verdict

**REQUEST CHANGES (H-178).** The ordered backfill addresses H-175 for archived records. One supported path still rebuilds a different document. When an import has no `founder_calls.json`, the first successful save starts from `core.empty()`, whose first keys are `version` and `label`. On a fresh read, `FounderCallsStore.load()` reconstructs only `companies`, `founders` and `calls`. I reproduced this with the store reader and simulated query results for one saved call. Applying `core.loaded()` afterward puts the two missing keys last.

Preserve the pre-save empty-store result, then use the legacy empty document as the reconstruction baseline once rows exist without an archive. Add a database regression that saves through the API after an import lacking this file, reopens the store, and compares the document content and ordered top-level keys against the legacy first save. All 16 local Founder Calls unit tests passed.

Keep `omar-briefing-<name>.md` for this port. It matches the legacy download and retaining it preserves the existing export convention.

### Claude — revision 2 (2026-11-12 09:31 CET)

H-179 is fixed. The shared reader now applies the old `load()` defaulting (`core.loaded`) to the archive, or to the
empty document when there is none, and only then substitutes the three ordered tables. A first save without an
archived file therefore reads back as the old first save wrote it: `version` and `label`, then the three objects, in
the old empty document's order. An archive missing a top-level key gets it appended, as before.

**Regression** (hosted). A schema with no archived `founder_calls.json`, then a first save. The fresh database read's
top-level keys equal the old empty document's, compared as a list, and its `version` / `label` equal the old
defaults. There is one company, one founder and one call. With the old reader this test fails.

The legacy briefing file name `omar-briefing-…` is kept, as you asked.

The real-snapshot parity was re-run on the changed reader: 0 differences. Gate passes. Hosted Founder Calls: 6 of 6.

## Codex implementation revision 2 verdict

**APPROVE (H-180).** The reader still returns `None` before the first save when both archive and tables are empty. Once rows exist, it rebuilds the document from the legacy defaults and puts `version` and `label` before the three record collections. The hosted regression saves through the API and checks key order, metadata values and collection counts in a fresh transaction. I reran all 16 local Founder Calls tests successfully. Claude reports all six hosted tests passed and the real-snapshot comparison found zero differences.

## Grok notes
