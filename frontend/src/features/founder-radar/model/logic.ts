/**
 * Pure Founder Radar rules, ported line for line from the old page (`features/founders/logic.ts`, itself v1's frTier,
 * frBucket, frMatch, companyMatch and the segment counts). The signal-age filters keep the browser clock
 * (`Date.now()`, review 026a decision g).
 */
import type { Company, FounderRadar, Person } from "./types";

export const NEI = "NOT ENOUGH INFORMATION";
export const GOLD = "Gold now";
export const STRONG = "Strong investigation";
export const CLAIM = "Founder claim — unverified";
export const RESEARCH = "Research & spinout talent";
export const INSUF = "Insufficient evidence / out of scope";
export const UNRESOLVED = "needs identity resolution";

export type View = "top" | "near" | "research" | "diag";
export type Seg = "gold" | "claim" | "research" | "insuf" | "watchlist" | "network" | "dismissed";

export const SEGMENTS: Array<[Seg, string]> = [
  ["gold", "Gold now + Strong investigation"],
  ["claim", "Founder claims — unverified"],
  ["research", "Research & spinout talent"],
  ["insuf", "Insufficient / out of scope"],
  ["watchlist", "Watchlisted"],
  ["network", "Network"],
  ["dismissed", "Dismissed"],
];

export type Filters = {
  status: string;
  theme: string;
  identity: string;
  region: string;
  country: string;
  city: string;
  source: string;
  age: string;
  ent: boolean;
  tech: boolean;
  recent: boolean;
  warm: boolean;
};

export const NO_FILTERS: Filters = {
  status: "",
  theme: "",
  identity: "",
  region: "",
  country: "",
  city: "",
  source: "",
  age: "",
  ent: false,
  tech: false,
  recent: false,
  warm: false,
};

export type Tier = "radar" | "watchlist" | "network" | "dismissed";

export function frTier(p: Person, networkStates: string[]): Tier {
  const s = p.radar_state || "";
  if (s === "dismissed") return "dismissed";
  if (networkStates.includes(s)) return "network";
  if (s === "watchlisted" || s === "researching") return "watchlist";
  return "radar";
}

export function frBucket(p: Person): string {
  return p.signal?.bucket || INSUF;
}

const daysAgo = (iso: string) => (Date.now() - new Date(iso).getTime()) / 864e5;

/** v1 frMatch: every filter + the free-text query over the whole record. `q` must already be trimmed + lower-cased. */
export function frMatch(p: Person, f: Filters, q: string): boolean {
  const s = p.signal ?? {};
  const ev = p.evidence ?? [];
  if (f.status && s.founder_status_class !== f.status) return false;
  if (f.identity && p.identity_status !== f.identity) return false;
  if (f.region && p.region !== f.region) return false;
  if (f.country && p.country !== f.country) return false;
  if (f.city && !(p.location || "").toLowerCase().startsWith(f.city.toLowerCase())) return false;
  if (f.source && !(p.sources ?? []).some((x) => x.source === f.source)) return false;
  if (f.theme && !JSON.stringify(s.factors ?? {}).toLowerCase().includes(f.theme.toLowerCase())) return false;
  if (f.age && !(p.last_signal && daysAgo(p.last_signal) <= +f.age)) return false;
  if (f.ent && !ev.some((e) => e.category === "entrepreneurial")) return false;
  if (f.tech && !ev.some((e) => e.category === "technical" || e.category === "technical_theme")) return false;
  if (f.recent && !(ev.some((e) => e.category === "trajectory") || (p.last_signal && daysAgo(p.last_signal) <= 90))) return false;
  if (f.warm && s.access?.kind !== "warm") return false;
  return !q || JSON.stringify(p).toLowerCase().includes(q);
}

/** v1 companyMatch: company name + claimed / scout-reported / linked founder names. No fuzzy matching. */
export function companyMatch(c: Company, q: string, people: Person[]): boolean {
  if (!q) return true;
  const names: unknown[] = [c.name];
  for (const f of c.founders ?? []) {
    names.push(f.name, f.claimed_name, ...(f.claimed_aliases ?? []));
    if (f.id) names.push(people.find((p) => p.id === f.id)?.name);
  }
  return names.some((n) => String(n || "").toLowerCase().includes(q));
}

/** People shown in the radar: user-provided Network contacts without evidence stay out (v1 renderFounders). */
export function radarPeople(d: FounderRadar): Person[] {
  const ns = d.network_states ?? [];
  return d.people.filter((p) => !(p.provenance === "user_provided" && ns.includes(p.radar_state || "") && !(p.evidence ?? []).length));
}

export function segmentCounts(P: Person[], ns: string[]): Record<Seg, number> {
  const n: Record<Seg, number> = { gold: 0, claim: 0, research: 0, insuf: 0, watchlist: 0, network: 0, dismissed: 0 };
  for (const p of P) {
    const t = frTier(p, ns);
    if (t !== "radar") {
      n[t]++;
      continue;
    }
    const b = frBucket(p);
    if (b === GOLD || b === STRONG) n.gold++;
    else if (b === CLAIM) n.claim++;
    else if (b === RESEARCH) n.research++;
    else n.insuf++;
  }
  return n;
}

export function inSegment(p: Person, seg: Seg, ns: string[]): boolean {
  const t = frTier(p, ns);
  if (seg === "watchlist" || seg === "network" || seg === "dismissed") return t === seg;
  if (t !== "radar") return false;
  const b = frBucket(p);
  if (seg === "gold") return b === GOLD || b === STRONG;
  if (seg === "claim") return b === CLAIM;
  if (seg === "research") return b === RESEARCH;
  return b === INSUF;
}

export function sortPeople(L: Person[]): Person[] {
  return [...L].sort(
    (a, b) =>
      (frBucket(a) === GOLD ? 0 : 1) - (frBucket(b) === GOLD ? 0 : 1) ||
      (b.signal?.ordering ?? 0) - (a.signal?.ordering ?? 0) ||
      String(b.last_signal || "").localeCompare(String(a.last_signal || "")),
  );
}

/** v1 frCard "Next:" line. */
export function nextStep(p: Person): string {
  const s = p.signal ?? {};
  const bk = frBucket(p);
  if (bk === RESEARCH) return "Investigate founder status (company, spinout, stealth) before anything else";
  if (bk === CLAIM)
    return s.queue_label === "Founder verified — company facts incomplete"
      ? "Source the missing company facts in the qualification queue: " + (s.missing ?? []).join(", ")
      : "Resolve identity, then confirm founder status on the source";
  if (bk === GOLD) return "Reach out via the access path this week";
  if (bk === STRONG) return "Close the missing fact: " + (s.missing ?? []).join(", ");
  return "Collect attributed evidence or dismiss";
}

export function unknownBands(bands: Record<string, string>, skipThemeOverlap: boolean): string {
  return Object.entries(bands)
    .filter(([k, v]) => v === NEI && !(skipThemeOverlap && k === "technical_theme_overlap"))
    .map(([k]) => k.replace("_", " "))
    .join(", ");
}

export function themeOptions(people: Person[]): string[] {
  const raw = people.flatMap((p) => ([] as unknown[]).concat(p.signal?.factors?.project_a ?? []));
  const joined = raw.map((t) => String(t).replace(/^.*themes?: /, "")).join(", ");
  return [...new Set(joined.split(",").map((x) => x.trim()).filter(Boolean))].sort();
}

export function sourceOptions(people: Person[]): string[] {
  return [...new Set(people.flatMap((p) => (p.sources ?? []).map((s) => s.source)))].sort();
}
