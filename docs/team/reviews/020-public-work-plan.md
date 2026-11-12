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

## Grok notes
