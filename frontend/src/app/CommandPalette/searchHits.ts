import type { Tone } from "@/components/ui";
import type { NavItem } from "../nav";

export type Pipeline = { signals?: Array<{ slug: string; company: string; one_liner?: string; location?: string; sc?: { provisional?: number } }> };
export type People = { people?: Array<{ id: string; name: string; role?: string; location?: string }> };
export type Events = { events?: Array<{ id: string; name: string; city?: string; start?: string }> };

export type HitKind = "PAGE" | "COMPANY" | "PERSON" | "EVENT" | "ASK";
export type Hit = { kind: HitKind; name: string; meta: string; to: string };

export const HIT_TONE: Record<HitKind, Tone> = { PAGE: "neutral", COMPANY: "blue", PERSON: "green", EVENT: "amber", ASK: "neutral" };

const MAX_HITS = 12;
const ASK_MIN_CHARS = 3;

/**
 * Global search results for `query`: pages (only when something is typed), then pipeline companies, people and
 * events (every one while the query is empty), capped at 12, then — for a real question — "Ask PZ Associate" (read-only:
 * it opens the Associate page and asks once).
 */
export function searchHits(
  query: string,
  { pages, pipeline, people, events }: { pages: NavItem[]; pipeline?: Pipeline; people?: People; events?: Events },
): Hit[] {
  const s = query.trim().toLowerCase();
  const has = (...xs: Array<string | undefined>) => !s || xs.join(" ").toLowerCase().includes(s);
  const r: Hit[] = [];
  for (const i of pages) if (s && has(i.label)) r.push({ kind: "PAGE", name: i.label, meta: "", to: i.path });
  for (const c of pipeline?.signals ?? [])
    if (has(c.company, c.one_liner, c.location))
      r.push({
        kind: "COMPANY",
        name: c.company,
        meta: [c.location, c.sc?.provisional].filter((x) => x !== undefined && x !== "").join(" · "),
        to: `/conviction?company=${encodeURIComponent(c.slug)}`,
      });
  for (const p of people?.people ?? [])
    if (has(p.name, p.role, p.location))
      r.push({ kind: "PERSON", name: p.name, meta: [p.role, p.location].filter(Boolean).join(" · "), to: `/network?person=${encodeURIComponent(p.id)}` });
  for (const e of events?.events ?? [])
    if (has(e.name, e.city))
      r.push({
        kind: "EVENT",
        name: e.name,
        meta: [(e.start ?? "").slice(0, 10), e.city].filter(Boolean).join(" · "),
        to: `/events?event=${encodeURIComponent(e.id)}`,
      });
  const out = r.slice(0, MAX_HITS);
  if (s.length >= ASK_MIN_CHARS)
    out.push({ kind: "ASK", name: `Ask PZ Associate: “${query.trim()}”`, meta: "", to: `/associate?q=${encodeURIComponent(query.trim())}` });
  return out;
}
