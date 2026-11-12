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

## Grok notes
