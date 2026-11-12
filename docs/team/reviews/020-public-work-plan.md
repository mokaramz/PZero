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

## Grok notes
