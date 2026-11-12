/** The browser filters (the old `mapFilter.ts`, line for line). They use the browser clock (decision e). */
import type { Filters, MapData } from "./types";

/** Mirrors themes.py archetype→theme mapping, for map filtering only (v1 ARCH_THEMES). */
const ARCH_THEMES: Record<number, string[]> = {
  2: ["industrial_autonomy"],
  3: ["regulated"],
  4: ["regulated"],
  5: ["defence"],
  6: ["defence", "industrial_autonomy", "physical_world"],
  7: ["industrial_autonomy"],
  8: ["physical_world"],
  9: ["regulated", "physical_world"],
  10: ["frontier", "defence"],
  11: ["frontier"],
  12: ["industrial_autonomy"],
  14: ["frontier", "physical_world"],
};

/** Great-circle distance in km between (a, b) and (c, d) as (lat, lng). */
export function hav(a: number, b: number, c: number, d: number): number {
  const R = 6371;
  const r = (x: number) => (x * Math.PI) / 180;
  const dl = r(c - a);
  const dg = r(d - b);
  const h = Math.sin(dl / 2) ** 2 + Math.cos(r(a)) * Math.cos(r(c)) * Math.sin(dg / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export const DEFAULT_FILTERS: Filters = {
  q: "",
  lyStart: true,
  lyEv: true,
  lyPpl: false,
  lyOrg: false,
  lyHub: false,
  time: "all",
  dist: 0,
  stage: "",
  evType: "",
  minS: 0,
  minE: 0,
  theme: "",
  status: "",
};

/** v1 applyMapFilters: returns what is visible plus per-layer totals within the distance radius. */
export function applyFilters(d: MapData, f: Filters, now = new Date()) {
  const H = d.home;
  const inDist = (o: { lat: number; lng: number }) => !f.dist || hav(H.lat, H.lng, o.lat, o.lng) <= f.dist;
  const themeOk = (arch: string) => {
    if (!f.theme) return true;
    const m = /^#(\d+)/.exec(arch || "");
    return !!(m && (ARCH_THEMES[Number(m[1])] ?? []).includes(f.theme));
  };
  const statusOk = (s: MapData["startups"][number]) =>
    !f.status ||
    (f.status === "verified"
      ? !!s.verified
      : f.status === "provisional"
        ? !s.verified
        : f.status === "omar"
          ? !!s.sent_to_omar
          : f.status === "gated"
            ? s.conflict === "potential_conflict"
            : true);
  const startups = f.lyStart
    ? d.startups.filter((s) => inDist(s) && (!f.stage || s.stage === f.stage) && s.score >= f.minS && themeOk(s.archetype) && statusOk(s))
    : [];
  const day = 86_400_000;
  const events = f.lyEv
    ? d.events.filter((e) => {
        if (!inDist(e) || (f.evType && e.type !== f.evType) || e.score < f.minE) return false;
        if (!e.start) return f.time === "all" || f.time === "past";
        const t = new Date(e.start).getTime();
        if (f.time === "past") return true;
        if (t < now.getTime() - day) return false;
        if (f.time === "7") return t - now.getTime() <= 7 * day;
        if (f.time === "30") return t - now.getTime() <= 30 * day;
        if (f.time === "weekend") return !!e.when?.weekend;
        return true;
      })
    : [];
  const pplAll = d.people.filter(inDist);
  const uniAll = d.orgs.filter((o) => o.kind !== "hub" && inDist(o));
  const hubAll = d.orgs.filter((o) => o.kind === "hub" && inDist(o));
  return {
    startups,
    events,
    people: f.lyPpl ? pplAll : [],
    orgs: [...(f.lyOrg ? uniAll : []), ...(f.lyHub ? hubAll : [])],
    counts: {
      start: startups.length,
      ev: events.length,
      ppl: pplAll.length,
      org: uniAll.length,
      hub: hubAll.length,
    },
  };
}

export type Visible = ReturnType<typeof applyFilters>;
