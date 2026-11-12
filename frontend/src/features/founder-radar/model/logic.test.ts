import { afterEach, describe, expect, it, vi } from "vitest";

import { ID, radar } from "../test/fixtures";
import {
  CLAIM,
  GOLD,
  INSUF,
  NO_FILTERS,
  RESEARCH,
  STRONG,
  companyMatch,
  frBucket,
  frMatch,
  frTier,
  inSegment,
  nextStep,
  radarPeople,
  segmentCounts,
  sortPeople,
  sourceOptions,
  themeOptions,
  unknownBands,
  type Filters,
} from "./logic";
import type { Person } from "./types";

const d = radar();
const NS = d.network_states!;
const byId = (id: string) => d.people.find((p) => p.id === id)!;
const person = (o: Partial<Person> = {}): Person => ({ id: "p-x", name: "X", ...o });
const f = (o: Partial<Filters>): Filters => ({ ...NO_FILTERS, ...o });

afterEach(() => vi.useRealTimers());

describe("tiers and buckets", () => {
  it("frTier: dismissed, a Network state, watchlisted / researching, else radar", () => {
    expect(frTier(person({ radar_state: "dismissed" }), NS)).toBe("dismissed");
    expect(frTier(person({ radar_state: "contacted" }), NS)).toBe("network");
    expect(frTier(person({ radar_state: "watchlisted" }), NS)).toBe("watchlist");
    expect(frTier(person({ radar_state: "researching" }), NS)).toBe("watchlist");
    expect(frTier(person({ radar_state: "detected" }), NS)).toBe("radar");
    expect(frTier(person(), NS)).toBe("radar");
  });

  it("frBucket: the signal's bucket, else insufficient", () => {
    expect(frBucket(person({ signal: { bucket: GOLD } }))).toBe(GOLD);
    expect(frBucket(person())).toBe(INSUF);
  });

  it("radarPeople leaves out user-provided Network contacts without evidence", () => {
    const ids = radarPeople(d).map((p) => p.id);
    expect(ids).not.toContain(ID.hana);
    expect(ids).toContain(ID.nils); // radar-detected, in the Network, with evidence
    expect(ids).toHaveLength(d.people.length - 1);
  });

  it("segmentCounts and inSegment agree on the fixture", () => {
    const P = radarPeople(d);
    expect(segmentCounts(P, NS)).toEqual({ gold: 0, claim: 6, research: 1, insuf: 2, watchlist: 1, network: 1, dismissed: 1 });
    expect(P.filter((p) => inSegment(p, "claim", NS)).map((p) => p.id)).toEqual([ID.mira, ID.jonas, ID.ilka, ID.teo, ID.sana, ID.grain]);
    expect(P.filter((p) => inSegment(p, "insuf", NS)).map((p) => p.id)).toEqual([ID.oskar, ID.petra]);
    expect(P.filter((p) => inSegment(p, "research", NS)).map((p) => p.id)).toEqual([ID.rhea]);
    expect(P.filter((p) => inSegment(p, "watchlist", NS)).map((p) => p.id)).toEqual([ID.wren]);
    expect(P.filter((p) => inSegment(p, "network", NS)).map((p) => p.id)).toEqual([ID.nils]);
    expect(P.filter((p) => inSegment(p, "dismissed", NS)).map((p) => p.id)).toEqual([ID.dana]);
    expect(P.filter((p) => inSegment(p, "gold", NS))).toEqual([]);
  });

  it("gold counts Gold now and Strong investigation", () => {
    const P = [person({ id: "a", signal: { bucket: GOLD } }), person({ id: "b", signal: { bucket: STRONG } }), person({ id: "c", radar_state: "watchlisted", signal: { bucket: GOLD } })];
    expect(segmentCounts(P, NS).gold).toBe(2);
    expect(inSegment(P[1], "gold", NS)).toBe(true);
    expect(inSegment(P[2], "gold", NS)).toBe(false); // a watchlisted Gold person is in Watchlisted only
  });
});

describe("frMatch", () => {
  const oskar = byId(ID.oskar);

  it("the free text is searched over the whole record, lower-cased", () => {
    expect(frMatch(oskar, NO_FILTERS, "")).toBe(true);
    expect(frMatch(oskar, NO_FILTERS, "stream-processing")).toBe(true); // inside an evidence claim
    expect(frMatch(oskar, NO_FILTERS, "nobody")).toBe(false);
  });

  it("status, identity, region, country, source and theme", () => {
    expect(frMatch(oskar, f({ status: "unknown" }), "")).toBe(true);
    expect(frMatch(oskar, f({ status: "researcher" }), "")).toBe(false);
    expect(frMatch(oskar, f({ identity: "resolved" }), "")).toBe(true);
    expect(frMatch(byId(ID.mira), f({ identity: "resolved" }), "")).toBe(false);
    expect(frMatch(oskar, f({ region: "DACH" }), "")).toBe(true);
    expect(frMatch(oskar, f({ region: "Nordics" }), "")).toBe(false);
    expect(frMatch(oskar, f({ country: "CH" }), "")).toBe(true);
    expect(frMatch(oskar, f({ country: "DE" }), "")).toBe(false);
    expect(frMatch(oskar, f({ source: "GitHub — builders in Zürich" }), "")).toBe(true);
    expect(frMatch(oskar, f({ source: "GitHub — builders in Kiel" }), "")).toBe(false);
    expect(frMatch(oskar, f({ theme: "ROBOTICS" }), "")).toBe(true);
    expect(frMatch(oskar, f({ theme: "ocean" }), "")).toBe(false);
  });

  it("the city matches the start of the location, case-insensitively", () => {
    expect(frMatch(oskar, f({ city: "zür" }), "")).toBe(true);
    expect(frMatch(oskar, f({ city: "Kiel" }), "")).toBe(false);
  });

  it("evidence checks: entrepreneurial, technical, warm path", () => {
    expect(frMatch(oskar, f({ ent: true }), "")).toBe(true);
    expect(frMatch(oskar, f({ tech: true }), "")).toBe(false);
    expect(frMatch(byId(ID.rhea), f({ tech: true }), "")).toBe(true);
    expect(frMatch(person({ evidence: [{ category: "technical_theme", claim: "", source: "" }] }), f({ tech: true }), "")).toBe(true);
    expect(frMatch(byId(ID.ilka), f({ warm: true }), "")).toBe(true);
    expect(frMatch(oskar, f({ warm: true }), "")).toBe(false);
  });

  it("signal age and recent activity use the browser clock (decision g)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-12T12:00:00Z"));
    const p = person({ last_signal: "2026-11-09" });
    expect(frMatch(p, f({ age: "7" }), "")).toBe(true);
    vi.setSystemTime(new Date("2026-11-30T12:00:00Z"));
    expect(frMatch(p, f({ age: "7" }), "")).toBe(false);
    expect(frMatch(p, f({ age: "30" }), "")).toBe(true);
    expect(frMatch(person(), f({ age: "90" }), "")).toBe(false); // no signal date never matches an age filter
    expect(frMatch(p, f({ recent: true }), "")).toBe(true); // ≤ 90 days
    vi.setSystemTime(new Date("2027-06-01T12:00:00Z"));
    expect(frMatch(p, f({ recent: true }), "")).toBe(false);
    expect(frMatch(person({ evidence: [{ category: "trajectory", claim: "", source: "" }] }), f({ recent: true }), "")).toBe(true);
  });
});

describe("companyMatch", () => {
  const C = d.companies!;
  const names = (q: string) => C.filter((c) => companyMatch(c, q, d.people)).map((c) => c.name);

  it("company name, claimed names, claimed aliases and the linked person's name — no fuzzy match", () => {
    expect(names("")).toEqual(["Kelpwise GmbH", "Borealis Robotics", "Quillstone AI", "Grainline Labs"]);
    expect(names("borealis")).toEqual(["Borealis Robotics"]);
    expect(names("sana okafor")).toEqual(["Quillstone AI"]);
    expect(names("gideon")).toEqual(["Grainline Labs"]); // a claimed alias
    expect(names("kelpwyse")).toEqual([]);
  });

  it("finds a company through the linked record's current name", () => {
    const P = d.people.map((p) => (p.id === ID.teo ? { ...p, name: "Teodor Haarberg-Lind" } : p));
    const c = C.find((x) => x.name === "Borealis Robotics")!;
    expect(companyMatch({ ...c, founders: c.founders.map((x) => ({ ...x, name: "", claimed_name: "" })) }, "haarberg-lind", P)).toBe(true);
  });
});

describe("ordering and the next step", () => {
  it("sortPeople: Gold first, then the ordering, then the newest signal", () => {
    const P = [
      person({ id: "a", last_signal: "2026-01-01", signal: { bucket: STRONG, ordering: 9 } }),
      person({ id: "b", last_signal: "2026-02-01", signal: { bucket: GOLD, ordering: 1 } }),
      person({ id: "c", last_signal: "2026-03-01", signal: { bucket: STRONG, ordering: 9 } }),
      person({ id: "d", signal: { bucket: CLAIM } }),
    ];
    expect(sortPeople(P).map((p) => p.id)).toEqual(["b", "c", "a", "d"]);
    expect(P.map((p) => p.id)).toEqual(["a", "b", "c", "d"]); // not in place
  });

  it("nextStep per bucket", () => {
    expect(nextStep(person({ signal: { bucket: RESEARCH } }))).toBe("Investigate founder status (company, spinout, stealth) before anything else");
    expect(nextStep(byId(ID.ilka))).toBe("Source the missing company facts in the qualification queue: founded, funding");
    expect(nextStep(byId(ID.mira))).toBe("Resolve identity, then confirm founder status on the source");
    expect(nextStep(person({ signal: { bucket: GOLD } }))).toBe("Reach out via the access path this week");
    expect(nextStep(person({ signal: { bucket: STRONG, missing: ["access path"] } }))).toBe("Close the missing fact: access path");
    expect(nextStep(person())).toBe("Collect attributed evidence or dismiss");
  });

  it("unknownBands lists the NOT ENOUGH INFORMATION bands (the first underscore read as a space)", () => {
    const b = byId(ID.oskar).signal!.bands as Record<string, string>;
    expect(unknownBands(b, false)).toBe("technical depth, talent magnet, technical theme_overlap");
    expect(unknownBands(b, true)).toBe("technical depth, talent magnet");
  });

  it("theme and source options, sorted and unique", () => {
    expect(themeOptions(d.people)).toEqual(["autonomy", "ocean", "robotics", "sensing"]);
    const src = sourceOptions(d.people);
    expect(src).toEqual([...src].sort()); // code-unit order, as before: capitals first
    expect(src[0]).toBe("Borealis Robotics official site");
    expect(src.at(-1)).toBe("authorized import");
    expect(src).toContain("GitHub — builders in Zürich");
    expect(new Set(sourceOptions(d.people)).size).toBe(sourceOptions(d.people).length);
  });
});
