import { describe, expect, it } from "vitest";

import { intel, pins, PINS_NOW } from "../test/fixtures";
import { berlinDay, berlinDayPlus } from "./dates";
import { NOT_PORTED } from "./deferred";
import { applyFilters, DEFAULT_FILTERS, hav } from "./filter";
import { linkTarget } from "./links";
import type { Filters, MapData } from "./types";
import {
  activeEcosystems,
  coverageGaps,
  dueText,
  ecoRadius,
  eventsNearby,
  gapText,
  linkedCompanies,
  linkedPeople,
  localHit,
  parseMode,
  peopleAtEvent,
  pinAt,
  resultRows,
  unplacedText,
  visibleTotal,
} from "./view";

const run = (f: Partial<Filters> = {}, d: MapData = pins()) => applyFilters(d, { ...DEFAULT_FILTERS, ...f }, PINS_NOW);
const slugs = (f: Partial<Filters>) => run(f).startups.map((s) => s.slug);
const ids = (f: Partial<Filters>) => run(f).events.map((e) => e.id);

describe("Map filters (the old mapFilter, the old e2e assertions)", () => {
  it("the defaults: startups and events on, people / universities / hubs off but counted", () => {
    const v = run();
    expect(v.counts).toEqual({ start: 8, ev: 7, ppl: 4, org: 4, hub: 2 });
    expect(v.people).toEqual([]);
    expect(v.orgs).toEqual([]);
    expect(ids({})).not.toContain("summer-founder-meetup"); // more than a day past
  });

  it("the layers: people, universities & labs, then hubs, in that order", () => {
    const v = run({ lyPpl: true, lyOrg: true, lyHub: true });
    expect(v.people).toHaveLength(4);
    expect(v.orgs.map((o) => o.kind)).toEqual(["university", "lab", "university", "university", "hub", "hub"]);
    expect(run({ lyStart: false, lyEv: false }).counts).toMatchObject({ start: 0, ev: 0 });
  });

  it("≤100 km from the home base shrinks every layer (great-circle distance)", () => {
    expect(hav(49.0069, 8.4037, 49.3988, 8.6724)).toBeCloseTo(47.8, 1);
    const v = run({ dist: 100, lyPpl: true, lyOrg: true, lyHub: true });
    expect(v.startups.map((s) => s.slug)).toEqual(["otterfield-analytics", "brightforge-ai"]);
    expect(v.events.map((e) => e.id)).toEqual(["forge-demo-day", "neckar-builders-night", "alder-energy-day"]);
    expect(v.people.map((p) => p.id)).toEqual(["p-mara-lindqvist", "p-teo-marchetti"]);
    expect(v.counts).toEqual({ start: 2, ev: 3, ppl: 2, org: 2, hub: 1 });
    expect(run({ dist: 250 }).counts.start).toBe(3); // + Zürich
    expect(run({ dist: 500 }).counts.start).toBe(5); // + the two in Munich; Berlin is just beyond
  });

  it("min scores, stage and event type", () => {
    expect(slugs({ minS: 60 })).toEqual(["lumen-ledger", "northwind-assure", "skylark-freight", "otterfield-analytics", "fernhollow-materials"]);
    expect(ids({ minE: 70 })).toEqual(["forge-demo-day", "spree-founder-dinner", "alpine-robotics-hackathon", "isar-defence-meetup"]);
    expect(slugs({ stage: "pre_company" })).toEqual(["otterfield-analytics"]);
    expect(slugs({ stage: "grant_angel" })).toEqual(["kestrel-robotics", "quillmark"]);
    expect(ids({ evType: "hackathon" })).toEqual(["alpine-robotics-hackathon"]);
  });

  it("the time window, on the browser clock: this week, this weekend (one event), 30 days, incl. past", () => {
    expect(ids({ time: "7" })).toEqual(["forge-demo-day", "spree-founder-dinner", "alpine-robotics-hackathon", "main-wine-evening"]);
    expect(ids({ time: "weekend" })).toEqual(["forge-demo-day"]);
    expect(ids({ time: "30" })).toHaveLength(6);
    expect(ids({ time: "30" })).not.toContain("alder-energy-day");
    expect(ids({ time: "past" })).toHaveLength(8);
    // an undated event shows only under "All upcoming" and "Incl. past"
    const d = pins();
    d.events[0].start = "";
    expect(applyFilters(d, { ...DEFAULT_FILTERS, time: "all" }, PINS_NOW).events.map((e) => e.id)).toContain("forge-demo-day");
    expect(applyFilters(d, { ...DEFAULT_FILTERS, time: "weekend" }, PINS_NOW).events).toEqual([]);
    expect(applyFilters(d, { ...DEFAULT_FILTERS, time: "past" }, PINS_NOW).events).toHaveLength(8);
  });

  it("the Project A theme comes from the archetype number; no archetype never matches", () => {
    expect(slugs({ theme: "defence" })).toEqual(["kestrel-robotics", "skylark-freight"]);
    expect(slugs({ theme: "frontier" })).toEqual(["fernhollow-materials"]);
    expect(slugs({ theme: "regulated" })).toEqual(["quillmark", "otterfield-analytics"]);
    expect(slugs({ theme: "industrial_autonomy" })).toEqual(["skylark-freight"]);
  });

  it("the status: verified, provisional, sent to Manager, conflict-gated", () => {
    expect(slugs({ status: "verified" })).toEqual(["skylark-freight"]);
    expect(slugs({ status: "provisional" })).toHaveLength(7);
    expect(slugs({ status: "omar" })).toEqual(["skylark-freight"]);
    expect(slugs({ status: "gated" })).toEqual(["northwind-assure"]);
  });
});

describe("Map view logic", () => {
  it("the results list: startups then events by score, then people; the total leaves orgs out", () => {
    const v = run({ lyPpl: true, lyOrg: true });
    const rows = resultRows(v);
    expect(rows.slice(0, 3).map((r) => r.name)).toEqual(["Northwind Assure", "Fernhollow Materials", "Lumen Ledger"]);
    expect(rows[8]).toMatchObject({ name: "Forge Demo Day & Pitch Night", sub: "Karlsruhe · 09-27", num: 82, sq: true });
    expect(rows.at(-1)).toMatchObject({ name: "Jonah Weller", sub: "CTO", num: "" });
    expect(rows).toHaveLength(8 + 7 + 4);
    expect(visibleTotal(v)).toBe(19);
    expect(rows.find((r) => r.name === "Kestrel Robotics")?.sub).toBe("Munich");
  });

  it("the local search: first substring over startups → events → people → orgs (events and orgs with their city)", () => {
    const d = pins();
    expect(localHit(d, "FORGE")?.sel).toEqual({ kind: "startup", id: "brightforge-ai" });
    expect(localHit(d, "karlsruhe")?.sel).toEqual({ kind: "event", id: "forge-demo-day" });
    expect(localHit(d, "lindqvist")?.sel).toEqual({ kind: "person", id: "p-mara-lindqvist" });
    expect(localHit(d, "rheinfeld")).toEqual({ sel: { kind: "org", id: "Rheinfeld Research Lab" }, at: { lat: 49.0128, lng: 8.4244 } });
    expect(localHit(d, "nowhere at all")).toBeNull();
    expect(localHit(d, "")).toBeNull();
    expect(pinAt(d, { kind: "org", id: "Forge Hub" })).toMatchObject({ lat: 49.0094 });
    expect(pinAt(d, { kind: "eco", id: "Munich" })).toBeUndefined();
  });

  it("the panel's cross-links; a person pin has no city, so nobody is 'to meet there' (decision e)", () => {
    const d = pins();
    const kestrel = d.startups[0];
    expect(linkedPeople(d, kestrel).map((p) => p.id)).toEqual(["p-jonah-weller"]);
    expect(eventsNearby(d, kestrel).map((e) => e.id)).toEqual(["isar-defence-meetup"]);
    expect(linkedCompanies(d, d.people[3]).map((s) => s.slug)).toEqual(["kestrel-robotics"]);
    expect(peopleAtEvent(d, d.events[0])).toEqual([]);
    d.people[0].city = "karlsruhe";
    expect(peopleAtEvent(d, d.events[0]).map((p) => p.id)).toEqual(["p-mara-lindqvist"]);
  });

  it("the modes, the intelligence lists and the small texts", () => {
    expect(["opportunity", "go", "gaps", "explore"].map(parseMode)).toEqual(["opportunity", "go", "gaps", "explore"]);
    expect(parseMode(null)).toBe("opportunity");
    expect(parseMode("satellite")).toBe("opportunity");
    const geo = intel();
    expect(activeEcosystems(geo).map((e) => e.city)).toEqual(["Munich", "Berlin"]);
    expect(coverageGaps(geo).map((e) => e.city)).toEqual(["Munich", "Berlin", "Tallinn"]);
    expect(coverageGaps(geo).map(gapText)).toEqual([
      "weak: founder formation",
      "coverage not assessed",
      "weak: universities / research · under-covered (not 'cold')",
    ]);
    expect(unplacedText({ deal_flow: 12, scout: 2 })).toBe("12 deal flow · 2 scout");
    expect(ecoRadius(geo.ecosystems[0])).toBeCloseTo(18.5);
    expect(ecoRadius({ ...geo.ecosystems[0], early: 20, high_signal_events: 9 })).toBeCloseTo(9 + 8 * 1.6 + 4 * 1.5);
    expect(dueText("SUGGESTED: follow up within 48h while the conversation is warm")).toBe("follow up within 48h while the c");
    expect(dueText(undefined)).toBe("");
  });
});

describe("Map links (decision d)", () => {
  it("routes that exist stay links, /news included (review 028a)", () => {
    expect(linkTarget("/conviction?company=Kestrel Robotics")).toEqual({ to: "/conviction?company=Kestrel Robotics" });
    expect(linkTarget("/deal-flow?candidate=cand-1")).toEqual({ to: "/deal-flow?candidate=cand-1" });
    expect(linkTarget("/network?person=p-1")).toEqual({ to: "/network?person=p-1" });
    expect(linkTarget("/news")).toEqual({ to: "/news" });
    expect(linkTarget("/news?event=n-1")).toEqual({ to: "/news?event=n-1" });
    expect(linkTarget(null)).toEqual({ to: null, reason: null });
    expect(linkTarget("")).toEqual({ to: null, reason: null });
  });

  it("/scout-intake opens the absorbed Deal Flow candidate when it names one, otherwise it is text with the merge reason", () => {
    expect(linkTarget("/scout-intake")).toEqual({ to: null, reason: NOT_PORTED.scoutIntake });
    expect(linkTarget("/scout-intake?candidate=cand 7")).toEqual({ to: "/deal-flow?candidate=cand+7" });
    expect(linkTarget("/scout-intake?item=si-3")).toEqual({ to: "/deal-flow?candidate=si-3&ns=scout_intake" });
  });
});

describe("the sourcing-day default date (decision g)", () => {
  it("is the Berlin calendar day + 7, not the UTC day", () => {
    const lateEvening = new Date("2026-11-12T23:30:00Z"); // 00:30 on 13 Nov in Berlin
    expect(berlinDay(lateEvening)).toBe("2026-11-13");
    expect(berlinDayPlus(lateEvening, 7)).toBe("2026-11-20");
    expect(new Date(lateEvening.getTime() + 7 * 864e5).toISOString().slice(0, 10)).toBe("2026-11-19"); // the old UTC rule
    expect(berlinDayPlus(new Date("2026-06-30T22:30:00Z"), 7)).toBe("2026-07-08"); // summer time, UTC+2
    expect(berlinDayPlus(new Date("2026-12-28T12:00:00Z"), 7)).toBe("2027-01-04");
    expect(berlinDayPlus(new Date("2026-03-28T12:00:00Z"), 7)).toBe("2026-04-04"); // across the clock change
  });
});
