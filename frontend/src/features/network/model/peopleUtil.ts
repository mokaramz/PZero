/**
 * The Network client rules, ported verbatim from the old `peopleUtil.ts` (review 013): segment chips, the strength
 * scale, names. Both dates are the client's UTC date (the old quirk, kept on purpose — the server's "today" is
 * Europe/Berlin): `today()` defaults "log contact" and a new person's last interaction, `isNewMonth` reads the UTC month.
 * `useMedia` moved to `@/lib/useMedia`.
 */
import type { Person } from "./types";

export const OMAR_ID = "p-omar-hedeya";

export const pplCity = (p: Person) => (p.location || "").split(",")[0].trim();

export const initials = (name: string) =>
  name
    .split(" ")
    .map((x) => x[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();

export const firstName = (name: string) => name.split(" ")[0];

export const STRENGTH_WIDTH: Record<string, string> = { met_once: "25%", warm: "60%", strong: "85%", close: "100%" };
export const STRENGTH_TONE: Record<string, "faint" | "amber" | "green"> = { met_once: "faint", warm: "amber", strong: "green", close: "green" };

export function startupsOf(p: Person): string[] {
  const s = Array.isArray(p.startups) ? p.startups : p.startups ? String(p.startups).split(",") : [];
  return s.map((x) => x.trim()).filter(Boolean);
}

/** Company + associated startups, company first (v1 `linked`). */
export function linkedNames(p: Person): string[] {
  const names = startupsOf(p);
  if (p.company && !names.includes(p.company)) names.unshift(p.company);
  return names;
}

export const stripSuggested = (s: string | undefined) => (s || "").replace("SUGGESTED: ", "");

export const NEW_STATES = [
  "introduction path identified",
  "introduction requested",
  "contacted",
  "replied",
  "first meeting completed",
  "active relationship",
  "trusted relationship",
  "opportunity introduced",
];

const isFp = (p: Person) => ["maybe", "high", "building"].includes(p.founder_potential || "");
const isIntro = (p: Person) => p.radar_state === "introduction requested" || p.boardy?.status === "introduction requested";
const isNewMonth = (p: Person) => {
  const mo = new Date().toISOString().slice(0, 7);
  return (p.state_history ?? []).some((h) => NEW_STATES.includes(h.to || "") && String(h.on || "").startsWith(mo));
};
const isDormant = (p: Person) => (p.days_since_touch || 0) > 60 && ["strong", "close"].includes(p.relationship_strength || "");
const isChain = (p: Person) => !!p.introduced_by || !!(p.recommended ?? []).length;
const viaOmar = (p: Person) => String(p.introduced_by_name || p.intro_route || "").toLowerCase().includes("omar");
const atEvents = (p: Person) => !!(p.events ?? []).length || String(p.discovery || "").toLowerCase().includes("event");

export type Segment = { id: string; label: string; test: (p: Person) => boolean; red?: boolean };

/** Segment chips (v1 pplSegs), in the old order. City segments are `c:<city>`. */
export const SEGMENTS: Segment[] = [
  { id: "all", label: "All", test: () => true },
  { id: "fp", label: "Founder potential", test: isFp },
  { id: "due", label: "Due", test: (p) => !!p.due, red: true },
  { id: "watch", label: "Watch", test: (p) => !!p.watch },
  { id: "chain", label: "Chains", test: isChain },
  { id: "intro", label: "Intro requests", test: isIntro },
  { id: "newmonth", label: "New this month", test: isNewMonth },
  { id: "dormant", label: "Dormant high-value", test: isDormant },
  { id: "opps", label: "With opportunities", test: (p) => !!(p.opportunities ?? []).length },
  { id: "omar", label: "Via Omar", test: viaOmar },
  { id: "boardy", label: "Via Boardy", test: (p) => !!p.boardy?.status },
  { id: "events", label: "Met at events", test: atEvents },
];

export function segmentTest(seg: string): (p: Person) => boolean {
  if (seg.startsWith("c:")) return (p) => pplCity(p) === seg.slice(2);
  return SEGMENTS.find((s) => s.id === seg)?.test ?? (() => true);
}

/** The four most common cities with their counts (ties keep first-seen order), for the city chips. */
export function topCities(people: Person[], n = 4): Array<[string, number]> {
  const c: Record<string, number> = {};
  for (const p of people) {
    const x = pplCity(p);
    if (x) c[x] = (c[x] || 0) + 1;
  }
  return Object.entries(c)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n);
}

export const today = () => new Date().toISOString().slice(0, 10);
