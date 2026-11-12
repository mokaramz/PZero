/** Pure view logic of the Map page (the old `MapPage` / `MapPanel` / `MapCanvas` inline code, unchanged in behaviour). */
import { LAYER_COLOR } from "./colors";
import type { Visible } from "./filter";
import type { GeoEco, GeoIntel, MapData, MapEvent, MapPerson, MapStartup, Mode, Selection } from "./types";

export const MODES: Array<{ value: Mode; label: string }> = [
  { value: "opportunity", label: "Opportunity" },
  { value: "go", label: "Where to go" },
  { value: "gaps", label: "Coverage gaps" },
  { value: "explore", label: "Explore" },
];

/** `?mode=` is read once; an unknown or missing value opens the default mode, Opportunity. */
export function parseMode(raw: string | null): Mode {
  return MODES.some((m) => m.value === raw) ? (raw as Mode) : "opportunity";
}

type At = { lat: number; lng: number };

/** The local search: the first case-insensitive substring match over startups → events → people → orgs (an event or
 *  an org also matches on its city). Null when nothing matches (the page then asks `map/search`). */
export function localHit(d: MapData, q: string): { sel: Selection; at: At } | null {
  const s = q.toLowerCase();
  if (!s) return null;
  const cand: Array<{ n: string; sel: Selection; at: At }> = [
    ...d.startups.map((x) => ({ n: x.company, sel: { kind: "startup", id: x.slug } as Selection, at: x })),
    ...d.events.map((x) => ({ n: `${x.name} ${x.city}`, sel: { kind: "event", id: x.id } as Selection, at: x })),
    ...d.people.map((x) => ({ n: x.name, sel: { kind: "person", id: x.id } as Selection, at: x })),
    ...d.orgs.map((x) => ({ n: `${x.name} ${x.city}`, sel: { kind: "org", id: x.name } as Selection, at: x })),
  ];
  const hit = cand.find((c) => c.n.toLowerCase().includes(s));
  return hit ? { sel: hit.sel, at: { lat: hit.at.lat, lng: hit.at.lng } } : null;
}

/** Where a pin selection sits, to fly there (undefined when it is no longer on the map). */
export function pinAt(d: MapData, s: Selection): At | undefined {
  if (s.kind === "startup") return d.startups.find((x) => x.slug === s.id);
  if (s.kind === "event") return d.events.find((x) => x.id === s.id);
  if (s.kind === "person") return d.people.find((x) => x.id === s.id);
  if (s.kind === "org") return d.orgs.find((x) => x.name === s.id);
  return undefined;
}

export type ResultRow = { key: string; color: string; sq: boolean; name: string; sub: string; num: string | number; sel: Selection; at: At };

/** "Visible results": the top 12 startups and 8 events by score, then the first 8 people. */
export function resultRows(v: Visible): ResultRow[] {
  return [
    ...v.startups
      .slice()
      .sort((a, b) => b.score - a.score)
      .slice(0, 12)
      .map((s) => ({
        key: `s${s.slug}`,
        color: LAYER_COLOR.startup,
        sq: false,
        name: s.company,
        sub: (s.location || "").split(",")[0],
        num: s.score,
        sel: { kind: "startup", id: s.slug } as Selection,
        at: s,
      })),
    ...v.events
      .slice()
      .sort((a, b) => b.score - a.score)
      .slice(0, 8)
      .map((e) => ({
        key: `e${e.id}`,
        color: LAYER_COLOR.event,
        sq: true,
        name: e.name,
        sub: `${e.city || ""} · ${(e.start || "").slice(5, 10)}`,
        num: e.score,
        sel: { kind: "event", id: e.id } as Selection,
        at: e,
      })),
    ...v.people.slice(0, 8).map((p) => ({
      key: `p${p.id}`,
      color: LAYER_COLOR.person,
      sq: false,
      name: p.name,
      sub: p.role || "",
      num: "" as string | number,
      sel: { kind: "person", id: p.id } as Selection,
      at: p,
    })),
  ];
}

/** The header count of "Visible results" (startups + events + people; orgs are not counted, as before). */
export const visibleTotal = (v: Visible) => v.startups.length + v.events.length + v.people.length;

/** Opportunity mode's list: every ecosystem that is not UNDER-COVERED, the first 14. */
export const activeEcosystems = (geo: GeoIntel) => geo.ecosystems.filter((e) => e.state !== "UNDER-COVERED");

/** Coverage gaps: weak or unassessed ecosystems, most companies + events first, the first 16. */
export function coverageGaps(geo: GeoIntel): GeoEco[] {
  return geo.ecosystems
    .filter((e) => e.coverage.weak.length || !e.coverage.assessed)
    .sort((a, b) => b.companies + b.events - (a.companies + a.events))
    .slice(0, 16);
}

export function gapText(e: GeoEco): string {
  return (
    (e.coverage.assessed ? `weak: ${e.coverage.weak.join(", ").toLowerCase()}` : "coverage not assessed") +
    (e.state === "UNDER-COVERED" ? " · under-covered (not 'cold')" : "")
  );
}

/** "12 deal flow · 3 scout" — what the intelligence could not place. */
export function unplacedText(unplaced: Record<string, number>): string {
  return Object.entries(unplaced)
    .map(([k, n]) => `${n} ${k.replace("_", " ")}`)
    .join(" · ");
}

/** An ecosystem circle grows with EARLY signals and high-signal events (capped), never with raw volume. */
export const ecoRadius = (e: GeoEco) => 9 + Math.min(e.early, 8) * 1.6 + Math.min(e.high_signal_events, 4) * 1.5;

/** The "Follow-ups due" card text: the next action without the SUGGESTED prefix, 32 characters. */
export const dueText = (nextAction: string | undefined) => (nextAction || "").replace("SUGGESTED: ", "").slice(0, 32);

/* ---- the detail panel's cross-links ---- */

export const linkedPeople = (d: MapData, s: MapStartup): MapPerson[] =>
  d.people.filter((p) => p.company && p.company.toLowerCase() === String(s.company).toLowerCase());

export const eventsNearby = (d: MapData, s: MapStartup): MapEvent[] =>
  d.events.filter((e) => e.city && s.location && String(s.location).toLowerCase().includes(String(e.city).toLowerCase())).slice(0, 3);

/** People whose `city` is the event's — person pins carry no city (decision e), so this is empty on real answers. */
export const peopleAtEvent = (d: MapData, e: MapEvent): MapPerson[] =>
  d.people.filter((p) => p.city && e.city && String(p.city).toLowerCase() === String(e.city).toLowerCase()).slice(0, 5);

export const linkedCompanies = (d: MapData, p: MapPerson): MapStartup[] =>
  d.startups.filter((s) => p.company && s.company && s.company.toLowerCase() === String(p.company).toLowerCase());
