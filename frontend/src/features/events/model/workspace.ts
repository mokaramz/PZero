/** Events workspace logic — pure functions behind the Events page (views, filters, day groups, calendar).
 *
 * Nothing here scores an event: tiers, ordering numbers and Scout 00 classes come from the backend; this module only
 * decides where an item is SHOWN. A Scout 00 suggestion (a report not yet on Events) is its own item kind and is never
 * presented as tracked, planned or verified. */
import type { EventRecord, ScoutReport } from "./types";

export type ViewKey = "upcoming" | "priority" | "planned" | "suggestions";
export type WsFilters = {
  days: "" | "7" | "30" | "90";
  area: string;
  theme: string;
  type: string;
  date: string;
  founders: "" | "medium" | "high";
  investors: "" | "yes";
  confidence: "" | "structured";
  general: boolean;
  past: boolean;
};

export const DEFAULT_FILTERS: WsFilters = { days: "", area: "", theme: "", type: "", date: "", founders: "", investors: "", confidence: "", general: false, past: false };

export type Item =
  | { kind: "event"; id: string; name: string; date: string; time: string; days: number | null; area: string; themes: string[]; type: string; e: EventRecord }
  | { kind: "suggestion"; id: string; name: string; date: string; time: string; days: number | null; area: string; themes: string[]; type: string; r: ScoutReport };

export const STRONG_ORDER = 59;
const tier = (e: EventRecord) => e.eligibility?.tier || "NEEDS REVIEW";

export function itemsOf(events: EventRecord[], reports: ScoutReport[]): Item[] {
  return [
    ...events.map((e): Item => ({
      kind: "event", id: e.id, name: e.name, date: e.when?.start_date || "", time: e.when?.start_time || "", days: e.days_until ?? e.when?.days_until ?? null,
      area: e.place?.area_label || e.city || "Location not stated", themes: e.themes ?? [], type: e.type && e.type !== "UNKNOWN" ? e.type : "", e,
    })),
    ...reports
      .filter((r) => !r.tracked_event_id)
      .map((r): Item => ({ kind: "suggestion", id: r.key, name: r.name, date: r.date, time: "", days: r.days_until, area: r.place?.area_label || r.city, themes: r.themes, type: "", r })),
  ];
}

export function isPriorityEvent(e: EventRecord): boolean {
  if (e.past || e.status === "skipped") return false;
  if (e.status === "planned") return true;
  if (e.scout && (e.scout.p_class === "P1" || e.scout.p_class === "P2")) return true;
  return tier(e) === "HIGH-SIGNAL" && (e.sc?.total ?? 0) >= STRONG_ORDER;
}
export const isPriority = (it: Item) => (it.kind === "event" ? isPriorityEvent(it.e) : it.r.p_class === "P1" || it.r.p_class === "P2");

/** Why an item is priority — the label on the card ("Planned", "Scout 00 P1", "Strong evidence"). */
export function priorityWhy(it: Item): string {
  if (it.kind === "suggestion") return `Scout 00 ${it.r.p_class}`;
  if (it.e.status === "planned") return "Planned";
  if (it.e.scout && ["P1", "P2"].includes(it.e.scout.p_class)) return `Scout 00 ${it.e.scout.p_class}`;
  return "Strong evidence";
}

/** Card (rich) or one quiet line: an item earns a card when it carries real signal; title-only listings stay a line. */
export function isRich(it: Item): boolean {
  if (it.kind === "suggestion") return true;
  const e = it.e;
  return isPriorityEvent(e) || e.status === "planned" || e.status === "attended" || tier(e) === "HIGH-SIGNAL" || !!e.scout || !!e.human_verified;
}

export const VIEWS: Array<[ViewKey, string]> = [
  ["upcoming", "Upcoming"],
  ["priority", "Priority"],
  ["planned", "Planned"],
  ["suggestions", "Scout suggestions"],
];

export function inView(it: Item, v: ViewKey, f: Pick<WsFilters, "general">): boolean {
  if (v === "priority") return isPriority(it);
  if (it.kind === "suggestion") return v === "upcoming" || v === "suggestions";
  const e = it.e;
  if (v === "planned") return e.status === "planned";
  if (v === "suggestions") return !!e.scout && tier(e) === "NEEDS REVIEW" && !e.human_verified;
  return tier(e) !== "REJECTED" || f.general;
}

export function investorRelevant(e: EventRecord): boolean {
  const net = e.assessment?.networking;
  return ["demo_day", "vc", "accelerator"].includes(e.type || "") || net === "HIGH" || net === "MEDIUM" || /\b(investors?|vcs?|angels?)\b/i.test(e.name);
}

/** Every filter (and the view). `skip` leaves one filter out — for its own option counts and the calendar dots. */
export function visible(items: Item[], v: ViewKey, f: WsFilters, skip: keyof WsFilters | null = null): Item[] {
  return items
    .filter((it) => {
      const attended = it.kind === "event" && it.e.status === "attended";
      if (f.past ? !attended : attended || (it.kind === "event" && it.e.past)) return false;
      if (!inView(it, v, f)) return false;
      if (skip !== "days" && f.days && (it.days == null || it.days > Number(f.days))) return false;
      if (skip !== "area" && f.area && it.area !== f.area) return false;
      if (skip !== "theme" && f.theme && !it.themes.includes(f.theme)) return false;
      if (skip !== "type" && f.type && it.type !== f.type) return false;
      if (skip !== "date" && f.date && it.date !== f.date) return false;
      if (it.kind === "event") {
        const fb = it.e.assessment?.founder;
        if (f.founders === "high" && fb !== "HIGH") return false;
        if (f.founders === "medium" && fb !== "HIGH" && fb !== "MEDIUM") return false;
        if (f.investors && !investorRelevant(it.e)) return false;
        if (f.confidence && !String(it.e.assessment?.confidence || "").startsWith("STRUCTURED")) return false;
      } else if (f.founders || f.investors || f.confidence) return false;
      return true;
    })
    .sort((a, b) => (a.date || "9999").localeCompare(b.date || "9999") || (a.time || "99").localeCompare(b.time || "99"));
}

export function counts(items: Item[], key: "area" | "theme" | "type"): Array<[string, number]> {
  const m = new Map<string, number>();
  for (const it of items) for (const v of key === "theme" ? it.themes : [it[key]]) if (v) m.set(v, (m.get(v) ?? 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

export type DayGroup = { day: string; rich: Item[]; quiet: Item[] };

/** Chronological day groups. `cutoff` (ISO date) limits the list; the rest is counted for "Show N later events". */
export function dayGroups(items: Item[], cutoff = "9999-12-31"): { groups: DayGroup[]; rest: number } {
  const groups: DayGroup[] = [];
  let rest = 0;
  for (const it of items) {
    const day = it.date || "";
    if (day && day > cutoff) {
      rest += 1;
      continue;
    }
    let g = groups.find((x) => x.day === day);
    if (!g) groups.push((g = { day, rich: [], quiet: [] }));
    (isRich(it) ? g.rich : g.quiet).push(it);
  }
  groups.sort((a, b) => (a.day || "9999").localeCompare(b.day || "9999"));
  return { groups, rest };
}

export const addDays = (iso: string, n: number) => {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

/** 42 ISO dates (Monday-first) covering the month `ym` ("2026-11"). */
export function monthGrid(ym: string): string[] {
  const [y, m] = ym.split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1, 1));
  const lead = (first.getUTCDay() + 6) % 7;
  return Array.from({ length: 42 }, (_, i) => new Date(Date.UTC(y, m - 1, 1 - lead + i)).toISOString().slice(0, 10));
}

export type DayMark = { n: number; priority: boolean; planned: boolean };
export function dayMarks(items: Item[]): Map<string, DayMark> {
  const m = new Map<string, DayMark>();
  for (const it of items) {
    if (!it.date) continue;
    const x = m.get(it.date) ?? { n: 0, priority: false, planned: false };
    x.n += 1;
    x.priority ||= isPriority(it);
    x.planned ||= it.kind === "event" && it.e.status === "planned";
    m.set(it.date, x);
  }
  return m;
}

export const shiftMonth = (ym: string, n: number) => {
  const [y, m] = ym.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1 + n, 1)).toISOString().slice(0, 7);
};
