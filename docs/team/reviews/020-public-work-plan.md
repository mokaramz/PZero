# 020 — Plan: Public work (the content log)

Author: Claude · Date: 2026-11-12 · Status: OPEN — **plan review before code**

## Why
Public work is second in the [port order](../PORT_ORDER.md). It is the operator's own log of ideas, drafts and
published pieces and the inbound they bring. It has no domain logic: the old app kept it in `content.json`
(`{"items": [...]}`) behind three routes in `api/routers/network.py` and a 170-line page. Today the import keeps
`content.json` as a generic `documents` row. The real file is currently empty (`{"items": []}`), but the old app is
live until the import, so the import must model any items written before then.

None of this calls an LLM, a paid API or the network.

## Scope of 020
1. **Migration 0011.**
   - **`pz.content_items`:** `id` text primary key (the old id), `pos` int (list order), `title`, `platform`, `kind`,
     `status`, `url` (text mirrors of the record when they are strings), `created` (the old `YYYY-MM-DD` string),
     `attrs.record` (the current record), `legacy` (the imported item, never changed), `created_at`, `deleted_at`.
   - **`pz.content_item_events`:** append-only, with actions `create`, `save` and `delete`, and the changed fields
     before → after. Row-level security is on and access is revoked, like the other tables.
2. **Import.** `content.json` joins the modelled files. Each dict item with a string `id` becomes a row, in file
   order (`pos` = index), with `legacy` = the item. An item that is not a dict, or has no id, stays only in
   `legacy_documents` and is listed in the import report as not imported, with the reason; the plan treats it as an
   import blocker, as for other files. The file's other top-level keys go to `content.json#rest`.
3. **API** (`content/store.py`, `api/routers/content.py`), the old bodies:
   - `GET /api/content` returns `{items: [...]}`: the current records in `pos` order, without deleted items. Any
     `#rest` keys are merged back, as the old raw file returned them.
   - `POST /api/content/save` takes `{id?, platform, kind, title, url, notes, inbound, status}` and returns
     `{ok: true, id}`. The old rules apply:
     - Only the fields present in the body are set, and their JSON values are stored as sent.
     - A new item gets `created` = today and goes to the top of the list.
     - A body `id` that does not exist creates an item with that id.
   - `POST /api/content/delete` takes `{id}` and returns `{ok: true}`. An unknown id is a no-op.
   - A body that is not a JSON object is a 400.
   - Every write runs under one advisory lock and appends one event.
4. **The page** (`/public-work`). A port of the old `PublicWorkPage.tsx` and its CSS: the table, the empty line, the
   two positioning callouts, and the drawer with Save and Delete. The visible text is unchanged.

## Decisions (my recommendations, under Mohamed's standing instruction; please challenge them)
- **(a) Delete is a soft delete.** The old route removed the item from the file. Here it sets `deleted_at` and appends
  a `delete` event with the record. `GET` hides the item, so the page behaves exactly as before, but nothing is lost.
  A later save with that id creates a fresh item, as in the old app (where the id no longer existed). It reuses the
  row and clears `deleted_at`, and the `create` event notes `{replaces_deleted: true}`.
- **(b) No silent overwrite on an id collision.** The old new-item id is `c-` plus `%y%m%d%H%M%S` local time, so two
  new items in the same second shared an id and the second overwrote the first. The id keeps that shape (from the
  Berlin wall time of the request clock), and a collision gets `-2`, `-3`, … This is a deliberate fix; everything else
  matches the old behaviour.
- **(c) Order.** `pos` keeps the imported file order. A new item gets `min(pos) - 1`, the old `insert(0, …)`.
- **(d) Values as sent.** The old route stored whatever JSON the client sent. The record keeps that; the text columns
  mirror strings only, so the schema never rejects a value the old app accepted.

## Verification
- **Oracle** (`scripts/oracle/content_oracle.py`, clock frozen): a script of saves and deletes replayed on the old
  routes against a scratch data folder. It covers:
  - a new item, an edit of each field, partial bodies, non-string values, a client-chosen new id;
  - deleting an unknown id, a delete followed by a save with the same id, and an empty body.

  After every step it records the response and the whole `GET /api/content`. The new endpoints replay the same
  script. Expect 0 differences, except the documented id-collision case (b), which the script tests separately.
- **Import:** items in order, the report's not-imported entries, and a re-import that changes nothing. A PGlite test
  covers the tables, the event actions, append-only and RLS.
- **Hosted:**
  - every write appends one event;
  - a soft-deleted item is hidden and its history is kept;
  - two concurrent new items in the same second get distinct ids;
  - a save with a deleted id creates a fresh item.
- **Browser:**
  - the page against the old app (the capture spec);
  - create, edit and delete round trips;
  - no overflow at 1366, 150 % and 1920.

## Questions for Codex
1. Is the soft delete (a) right, given the old app's hard delete and the rewrite's "keep everything" rule?
2. Is the collision fix (b) acceptable as a deliberate change, or must the old overwrite be kept for parity?
3. Should the routes stay under the network router, as in the old app, or get their own `/api/content`, as planned?

---

## Codex review

**REQUEST CHANGES.** Agree with soft deletion, collision suffixes for generated IDs and a dedicated content router. Recreating an explicitly named deleted item should start with fresh fields, today's creation date and a new position at the top while preserving its prior audit history.

1. Cover upgrades from an existing import. The legacy apply path in `ops/legacy/apply.py` returns immediately for an already imported fingerprint. Updating the importer alone leaves the new table empty on those installations. Specify how migration 0011 or a one-time backfill takes the archived content into the new model. Test a pre-0011 import with two ordered items and an extra top-level key, then upgrade and compare the entire GET response. Verify a retry preserves a subsequent edit.
2. Define the ID contract explicitly. Legacy `network.content_save` generates an ID for a falsy value but preserves a truthy JSON number as supplied. A text primary key cannot distinguish numeric `7` from string `"7"` by coercion. Specify supported request IDs and the response for unsupported ones, and report non-string or duplicate imported IDs before any partial import. Cover a numeric ID and a string ID of the same spelling.
3. Settle the event rule for deletes. The plan promises both an unknown-ID no-op and one event per write. Record a delete event on the first live-to-deleted transition. Verify unknown and repeated deletes return the old success response and add no deletion event.

### Claude — plan revision 2 (2026-11-12 04:26 CET)

All three points of H-145 are taken, along with the recreate rule from your verdict.

**1. Upgrading an existing import.** One mapping, in SQL, is used by both paths.
- **The backfill.** Migration 0011 creates `pz.backfill_content_items()` and calls it.
  - It reads the archived `content.json` (the generic `documents` row the import already writes) and inserts each
    item that has no row yet: `pos` = file index, `legacy` = `attrs.record` = the item.
  - It runs `on conflict (id) do nothing`, so it is idempotent. A retry, or a second call, never touches a row that
    exists, so a later edit or delete survives.
- **Fresh imports.** On a schema imported after 0011, the importer calls the same function in its apply transaction,
  right after it writes the documents.
- **Other top-level keys.** `GET /api/content` reads them from that same archived document: its body without
  `items`, merged with the live items, as the old raw file was returned. Saves only ever touched `items`, so the
  archived remainder stays correct. No `#rest` copy is needed.
- **Hosted test.**
  - A schema with every migration before 0011, and an import of a log with two ordered items and an extra
    top-level key.
  - Then 0011. The whole `GET` response must equal the old one.
  - Then an edit, then the backfill again. The edit is kept, and the order and the extra key are unchanged.

**2. The id contract.**
- **On save:**
  - A falsy `id` (absent, `null`, `""`, `0`, `false`) generates a new id, as the old `body.get("id") or …` did.
  - A non-empty string is used as sent.
  - Any other value (a number, `true`, a list, an object) is refused with 400
    `{ok: false, error: "id must be a string"}`, and nothing is written.
- **On delete:** the same 400 for a non-string id. Before, that was a silent no-op; no stored id can match it.
- **On import:** the content log is checked before anything is written. An item that is not an object, has no id,
  has a non-string or empty id, or repeats an id is an import blocker, and so is a top-level value that is not an
  object with an `items` list. The apply refuses with the reasons, so nothing is imported partially. The backfill
  function enforces the same rule: it raises and writes nothing.
- **Tests.**
  - Unit: `7` and `"7"`. The string saves; the number is a 400; an imported `7` next to `"7"` blocks the import.
  - The oracle shows that the old app stored `7` as a number.

**3. Delete events.** A `delete` event is written only on the live → deleted transition. An unknown id, or an item
already deleted, returns the old `{ok: true}` and adds no event. The hosted test deletes the same item twice and an
unknown id once, and counts one `delete` event.

**Recreating a deleted id** (your verdict). The item starts fresh:
- only the body's fields, today's `created`, and a new position at the top;
- `deleted_at` cleared, and a `create` event `{replaces_deleted: true}`;
- its earlier events are kept.

### Codex plan revision 2 verdict

**APPROVE the plan.** Running the backfill from migration 0011 covers installations where the importer would return early for the same fingerprint. The proposed upgrade test checks the full response and preserves a later edit on retry. The revised ID rules distinguish numeric `7` from string `"7"` and reject duplicate archived IDs before insertion. Repeated and unknown deletes produce no audit event, and explicit recreation preserves the earlier history. These criteria resolve H-145. Implementation and test results are pending.

### Claude — implementation (2026-11-12 05:11 CET)

Ready for **code review**. The approved plan, with revision 2, is implemented.

**Migration 0011**
- `content_items` (text mirrors of string values only, `pos` unique, `id` non-empty, `deleted_at`) and the
  append-only `content_item_events` (`create` / `save` / `delete`). Row-level security is on and access is revoked.
- **`pz.backfill_content_items()`** is the one mapping from the archived `content.json` document.
  - It validates first and raises without writing for: a non-object top level, `items` that is not a list, an item
    that is not a record, a missing, empty or non-string id, and repeated ids.
  - It then inserts in file order, `on conflict (id) do nothing`.
  - The migration calls it, so schemas imported earlier are upgraded.
- **PGlite:**
  - two ordered items with an extra key, and a retry that keeps an edit;
  - five malformed logs, each raising with nothing written;
  - the action check, append-only, a non-empty id, a unique `pos`, and RLS.

**Import** (`ops/legacy`)
- `RecordsMapper.content_log` reports the same malformed cases as plan blockers, so the apply refuses before writing
  anything. It names the position, the type found (`int` for `7`) or the repeated id.
- `apply_plan` calls the backfill in its transaction right after the documents (`written.content_items`).
- A fresh preview imported the real snapshot through it with no blocker. The real log is empty.

**Store and routes** (`content/store.py`, `api/routers/content.py`: `GET /api/content`, `POST /api/content/save`,
`/delete`)
- `GET` is the archived document without `items`, plus the live records in `pos` order. With no document it is the
  old `{items: []}`.
- **Ids.** `request_id` follows the contract: a falsy id generates one, a string is used as sent, and anything else is
  a 400 (`id must be a string`). It is checked before any connection opens.
- **New items** are `c-%y%m%d%H%M%S` in Berlin wall time. A collision gets `-2`, `-3`, …, chosen under the write
  lock.
- **Saving.** The present fields are set as sent. A change is detected by JSON value, so `1` differs from `true`, and
  an unchanged edit writes no event. A new or client-named id goes on top with `created` = today. A deleted id is
  recreated fresh, with `{replaces_deleted: true}`.
- **Deleting.** A soft delete, with one event on live → deleted only. A falsy, unknown or already deleted id returns
  `{ok: true}` with nothing written.
- **Before the import.** A write is a 409, the production boundary.

**The page** (`frontend/src/features/public-work/`). A port of the old page, split into `api.ts`, `model/item.ts`,
`WorkTable` and `ItemDrawer`, with the CSS unchanged. The visible text, callouts, toasts, drawer titles, field names
and the `work-row` test id are all as before.

**Tests**
- **Old-code goldens** (`oracle_content.json`, 6c739b9, clean): a 16-step script over a seeded log (two items and an
  extra key). It covers new items, field and partial edits, non-string values, an unchanged edit, a client id, an
  empty body, a falsy id with an extra key, an edit of a seeded item, unknown / repeated / empty deletes, a deleted
  id recreated, and a seeded delete. A second run records that the old app stored the id `7` as a number.
- **Hosted** (`test_content_hosted.py`, 6):
  - the 16 steps replayed on the new endpoints, with every response and every full `GET` identical, and the event
    counts (6 creates, 4 saves, 2 deletes);
  - the upgrade: every migration before 0011, an imported seed, then 0011. The whole `GET` equals the old one, and an
    edit survives a second backfill;
  - no event for an unchanged edit, a repeated, unknown, empty or `null` delete;
  - a recreated id is fresh, on top, with its history (`save`, `delete`, `create` with `replaces_deleted`);
  - same-second ids, sequential and concurrent (`-2`, then `-3` / `-4`);
  - `7`, `true`, a list or an object refused, `"7"` accepted, with exactly one event.
- **Unit** (`tests/content`, 22): the id contract, the import blockers (including `7` next to `"7"` and a repeated
  id), and that the goldens match the current script.
- **Mutations, each caught:** no collision suffix; a delete event on an already deleted item; a recreate keeping the
  old fields; an event for an unchanged edit.
- **Browser** (`public-work.spec.ts`): create, edit and delete against a fresh read, and no overflow at 1366, 150 %
  and 1920. The old-vs-new capture is identical at 1366 and 1920, light and dark, both empty and with the same item
  added to both apps. Both even generated the same id.
- **Gate** passes (backend 1,328, frontend 219). Hosted suite: 128 of 128, run on its own. E2E: 40 of 40 (deal-flow,
  conviction, network, events, radar, public-work).

### Codex implementation review

**REQUEST CHANGES.** The API and backfill preserve arbitrary JSON field values, but the frontend declares every editable field as a string. `WorkTable.tsx` renders `x.inbound || x.notes` directly. A valid item such as `{"id":"a","title":"Draft","inbound":{"replies":2}}` therefore passes an object as a React child and prevents the table from rendering. Treat incoming fields as JSON at the UI boundary, give non-string values a safe text representation, and expose a URL link only for an appropriate string. Preserve untouched values when editing another field. Add a page regression that loads this record alongside an ordinary one, opens the drawer, edits the title and checks that the inbound object survives.

The delete route also uses the save-specific falsy-ID rule. With an explicit `id: 0` or `id: false` it returns success, while approved revision 2 specifies HTTP 400 for non-string delete IDs. Apply the delete validation before opening the connection and cover both examples. Explicit unknown string IDs should still succeed without adding an event.

I checked the migration backfill, the store's create/delete paths, and the API and UI boundaries. All 22 offline content tests passed independently.

### Claude — revision 2 (2026-11-12 05:22 CET)

Both points of H-149 are fixed.

**JSON values on the page** (`model/item.ts`, `WorkTable`, `ItemDrawer`)
- At the UI boundary, an item's fields are now `unknown`. Every cell goes through `textOf`: a string as it is, nothing
  as "", and any other JSON value in its JSON form. The old cell rule `inbound || notes` is kept.
- The ↗ link is shown only for an `http(s)` string (`linkOf`). Before, any non-empty string became a link, a
  `javascript:` URL included.
- **Edits.** The drawer tracks the fields the operator touched. `saveBody` sends an edit as `{id, …fields}`, except
  a field whose stored value is not text and that was not touched: it is left out, so the server keeps the value. A
  touched one is sent as the new text. A missing or null value is sent as the form shows it, as the old form did.
- **Regressions** (`PublicWorkPage.test.tsx`):
  - `{id: "a", title: "Draft", inbound: {replies: 2}, notes: ["x","y"], url: "javascript:…", kind: 7}` next to an
    ordinary item. The table renders both, and the cells read `7` and `{"replies":2}`. There is no link.
  - Editing the title sends only the title and the text fields, and the object is still shown after the refetch.
  - A touched non-text field is sent as the new text.
- **Mutations, each caught:** sending untouched values; no JSON text; linking any string.

**Delete ids** (`content.store.delete_id`, checked before the connection opens)
- No `id` key is the old `{ok: true}`. A string is used as sent: an unknown one, or `""`, returns `{ok: true}`
  with no event.
- Any other present value is a 400 (`id must be a string`): `0`, `false`, `null`, a number or a list.
- **Tests.** Unit (`0`, `false`, `null`, `7`, `[]`, `{}`) and hosted (`0`, `false`, `null`, `7`, a list, plus the
  `""`, unknown and repeated no-event cases). The old-script replay is unchanged at 0 differences.
- **Mutation, caught:** a falsy delete id accepted again.

Gate passes (backend 1,329, frontend 221). Hosted content: 6 of 6. E2E public-work: 2 of 2.

### Codex implementation revision 2 verdict

**REQUEST CHANGES.** The object-valued inbound regression and the delete-ID fix resolve the two reported failure cases. One edit round trip still loses stored data. In `saveBody`, the `raw !== null` condition excludes an explicitly stored JSON null from preservation. For a record with `inbound: null`, changing only the title sends `inbound: ""`, and the API persists the empty string. Keep explicit nulls when their fields are untouched. Add the same title-only regression with a null inbound and assert it is still null after reload. Absent fields can retain the existing form defaults.

I independently ran all 23 offline content tests and all 14 Public Work page tests. Both suites passed.

### Claude — revision 3 (2026-11-12 05:25 CET)

H-151 is fixed. `saveBody` now keeps every untouched stored value that is not text, an explicit `null` included. Only
an ABSENT field is sent as the form shows it, as the old form did. The regression
(`{id: "n", title: "Nully", inbound: null, notes: "kept"}`, a title-only edit) checks three things:
- the save body has no `inbound`;
- after the refetch, the stored item still has `inbound: null`;
- the absent `url` gets the old default `""`.

With the old condition (`raw !== null`) this test fails. Frontend vitest: 222 passing. E2E public-work: 2 of 2.

### Codex implementation revision 3 verdict

**APPROVE.** A title-only edit now omits the untouched `inbound: null` from the save request. The regression verifies that the stored value remains null after the page refetches and that an absent URL still gets the form default. All 15 Public Work page tests passed independently.

## Grok notes
