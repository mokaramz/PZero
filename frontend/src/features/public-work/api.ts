/**
 * The Public work endpoints (review 020) — the ONE place their paths live. The payloads are the old ones
 * (`/api/content`, `/api/content_save`, `/api/content_delete`) under new paths.
 *
 * - `GET content` → `{items, …}`, the items in the order the server keeps them.
 * - `POST content/save {id?, title, platform, kind, url, inbound, notes}` → `{ok, id}`; a bad body or a non-string id
 *   is a 400 `{ok:false, error}`, and nothing is saved.
 * - `POST content/delete {id}` → `{ok}`.
 */
import { useApi, useAction } from "@/lib/hooks";
import type { ContentPayload, ItemFields } from "./model/item";

export const CONTENT = "content";
export const SAVE = "content/save";
export const DELETE = "content/delete";

/** What a write makes stale: the list. */
export const CONTENT_KEYS = [CONTENT];

/** The old action labels (Background activity and the "✕ … failed" / "✓ … — done" toasts). */
export const LABEL = { save: "Saving", delete: "Deleting" } as const;

/** A new item sends every field; an edit sends `{id, …}` without the non-text values it leaves untouched (`saveBody`). */
export type SaveBody = Partial<ItemFields> & { id?: string };
export type SaveResult = { ok: boolean; id: string };

export function useContent() {
  return useApi<ContentPayload>(CONTENT);
}

export function useSaveItem() {
  return useAction<SaveBody, SaveResult>(SAVE, { invalidates: CONTENT_KEYS, label: LABEL.save, success: "Saved" });
}

/** As before, the delete keeps the standard "✓ Deleting — done" outcome; the drawer adds its own "Deleted" toast. */
export function useDeleteItem() {
  return useAction<{ id: string }, { ok: boolean }>(DELETE, { invalidates: CONTENT_KEYS, label: LABEL.delete });
}
