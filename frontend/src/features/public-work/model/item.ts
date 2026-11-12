/** A public-work item (an idea, a draft or a published piece) and the drawer's form over it.
 *
 *  The server keeps every field as the JSON value it was sent (the old routes stored anything), so an item's fields
 *  are `unknown` at this boundary (Codex H-149): they are shown through `textOf`, a link only for an http(s) string,
 *  and an edit never rewrites a non-text value the operator did not touch. */
import type { Tone } from "@/components/ui";

export type Item = {
  id: string;
  title?: unknown;
  platform?: unknown;
  kind?: unknown;
  url?: unknown;
  notes?: unknown;
  inbound?: unknown;
  created?: unknown;
  status?: unknown;
};

export type ContentPayload = { items: Item[] };

export const PLATFORMS = ["linkedin", "x", "blog", "other"];
export const KINDS = ["idea", "draft", "published"];

/** A stored value as text: a string as it is, nothing as "", any other JSON value in its JSON form. */
export function textOf(v: unknown): string {
  if (typeof v === "string") return v;
  if (v === undefined || v === null) return "";
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

/** The url to link to: an http(s) string only (anything else is shown as text, never as a link). */
export const linkOf = (v: unknown): string | null => (typeof v === "string" && /^https?:\/\//i.test(v) ? v : null);

/** The old table cell: the inbound, else the notes (`x.inbound || x.notes`), as text. */
export const inboundOrNotes = (x: Item): string => textOf(x.inbound || x.notes);

/** The status badge: published green, draft amber, anything else neutral. */
export const kindTone = (kind?: unknown): Tone => (kind === "published" ? "green" : kind === "draft" ? "amber" : "neutral");

/** The fields the form edits and the save sends. */
export type ItemFields = { title: string; platform: string; kind: string; url: string; inbound: string; notes: string };
export const FIELD_NAMES = ["title", "platform", "kind", "url", "inbound", "notes"] as const;

/** The form's starting values: the item's own (as text), or the defaults for a new one. An unknown platform / kind
 *  falls back to linkedin / idea. */
export function fieldsOf(item: Item | null): ItemFields {
  const pick = (v: unknown, list: string[], fallback: string) => (typeof v === "string" && list.includes(v) ? v : fallback);
  return {
    title: textOf(item?.title),
    platform: pick(item?.platform, PLATFORMS, "linkedin"),
    kind: pick(item?.kind, KINDS, "idea"),
    url: textOf(item?.url),
    inbound: textOf(item?.inbound),
    notes: textOf(item?.notes),
  };
}

/** What a save sends. A new item: every field (the old form). An edit: `{id, …fields}`, except a field whose stored
 *  value is not text (a number, a list, an object, an explicit `null`) and which the operator did not touch: it is
 *  left out, so the server keeps the value as it is (Codex H-149 / H-151). Only an ABSENT field is sent as the form
 *  shows it, as the old form did. */
export function saveBody(item: Item | null, f: ItemFields, touched: ReadonlySet<keyof ItemFields>): Partial<ItemFields> & { id?: string } {
  if (!item) return { ...f };
  const out: Partial<ItemFields> & { id?: string } = { id: item.id };
  for (const k of FIELD_NAMES) {
    const raw = item[k];
    const keep = raw !== undefined && typeof raw !== "string" && !touched.has(k); // null included
    if (!keep) out[k] = f[k];
  }
  return out;
}
