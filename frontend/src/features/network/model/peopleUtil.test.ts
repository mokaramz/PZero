import { afterEach, describe, expect, it, vi } from "vitest";

import {
  firstName,
  initials,
  linkedNames,
  NEW_STATES,
  OMAR_ID,
  pplCity,
  SEGMENTS,
  segmentTest,
  startupsOf,
  STRENGTH_TONE,
  STRENGTH_WIDTH,
  stripSuggested,
  today,
  topCities,
} from "./peopleUtil";
import type { Person } from "./types";

const P = (extra: Partial<Person> = {}): Person => ({ id: "p-x", name: "X Y", ...extra });
const seg = (id: string) => segmentTest(id);
const berlinDate = (d: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Berlin" }).format(d);

function at(iso: string) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(iso));
}

afterEach(() => vi.useRealTimers());

describe("peopleUtil — names and scales (verbatim)", () => {
  it("city, initials, first name", () => {
    expect(pplCity(P({ location: " Berlin , Germany" }))).toBe("Berlin");
    expect(pplCity(P({ location: "Karlsruhe" }))).toBe("Karlsruhe");
    expect(pplCity(P())).toBe("");
    expect(initials("Lena Vogt")).toBe("LV");
    expect(initials("Anna Maria van Berg")).toBe("AM");
    expect(initials("cher")).toBe("C");
    expect(initials("")).toBe("");
    expect(firstName("Tariq Haddad")).toBe("Tariq");
    expect(OMAR_ID).toBe("p-omar-hedeya");
  });

  it("startups from a list or a comma string; linked names put the company first, once", () => {
    expect(startupsOf(P({ startups: [" A ", "", "B"] }))).toEqual(["A", "B"]);
    expect(startupsOf(P({ startups: "A, B,," }))).toEqual(["A", "B"]);
    expect(startupsOf(P())).toEqual([]);
    expect(linkedNames(P({ company: "Co", startups: ["A"] }))).toEqual(["Co", "A"]);
    expect(linkedNames(P({ company: "A", startups: ["A", "B"] }))).toEqual(["A", "B"]);
    expect(linkedNames(P())).toEqual([]);
  });

  it("stripSuggested removes the first 'SUGGESTED: ' only", () => {
    expect(stripSuggested("SUGGESTED: call SUGGESTED: x")).toBe("call SUGGESTED: x");
    expect(stripSuggested("SUGGESTED:call")).toBe("SUGGESTED:call");
    expect(stripSuggested(undefined)).toBe("");
  });

  it("the strength scale", () => {
    expect(STRENGTH_WIDTH).toEqual({ met_once: "25%", warm: "60%", strong: "85%", close: "100%" });
    expect(STRENGTH_TONE).toEqual({ met_once: "faint", warm: "amber", strong: "green", close: "green" });
  });
});

describe("peopleUtil — segments", () => {
  it("keeps the old order, labels and the red Due count", () => {
    expect(SEGMENTS.map((s) => [s.id, s.label])).toEqual([
      ["all", "All"],
      ["fp", "Founder potential"],
      ["due", "Due"],
      ["watch", "Watch"],
      ["chain", "Chains"],
      ["intro", "Intro requests"],
      ["newmonth", "New this month"],
      ["dormant", "Dormant high-value"],
      ["opps", "With opportunities"],
      ["omar", "Via Omar"],
      ["boardy", "Via Boardy"],
      ["events", "Met at events"],
    ]);
    expect(SEGMENTS.filter((s) => s.red).map((s) => s.id)).toEqual(["due"]);
  });

  it("founder potential: maybe, high, building — not none or unset", () => {
    for (const v of ["maybe", "high", "building"]) expect(seg("fp")(P({ founder_potential: v }))).toBe(true);
    for (const v of ["none", "", undefined]) expect(seg("fp")(P({ founder_potential: v }))).toBe(false);
  });

  it("due and watch are the server's flags", () => {
    expect(seg("due")(P({ due: true }))).toBe(true);
    expect(seg("due")(P({ due: false }))).toBe(false);
    expect(seg("watch")(P({ watch: true }))).toBe(true);
    expect(seg("watch")(P())).toBe(false);
  });

  it("chains: an introducer or at least one recommendation", () => {
    expect(seg("chain")(P({ introduced_by: "p-a" }))).toBe(true);
    expect(seg("chain")(P({ recommended: ["p-b"] }))).toBe(true);
    expect(seg("chain")(P({ introduced_by: "", recommended: [] }))).toBe(false);
    // the resolved name alone is not a chain
    expect(seg("chain")(P({ introduced_by_name: "A" }))).toBe(false);
  });

  it("intro requests: the radar state or the Boardy status, exactly", () => {
    expect(seg("intro")(P({ radar_state: "introduction requested" }))).toBe(true);
    expect(seg("intro")(P({ boardy: { status: "introduction requested" } }))).toBe(true);
    expect(seg("intro")(P({ radar_state: "introduction path identified" }))).toBe(false);
    expect(seg("intro")(P({ radar_state: "Introduction requested" }))).toBe(false);
  });

  it("dormant high-value: more than 60 days and strong or close", () => {
    expect(seg("dormant")(P({ days_since_touch: 60, relationship_strength: "strong" }))).toBe(false);
    expect(seg("dormant")(P({ days_since_touch: 61, relationship_strength: "strong" }))).toBe(true);
    expect(seg("dormant")(P({ days_since_touch: 61, relationship_strength: "close" }))).toBe(true);
    expect(seg("dormant")(P({ days_since_touch: 400, relationship_strength: "warm" }))).toBe(false);
    expect(seg("dormant")(P({ days_since_touch: null, relationship_strength: "close" }))).toBe(false);
  });

  it("opportunities, Boardy, via Omar, events", () => {
    expect(seg("opps")(P({ opportunities: [{}] }))).toBe(true);
    expect(seg("opps")(P({ opportunities: [] }))).toBe(false);
    expect(seg("boardy")(P({ boardy: { status: "matched" } }))).toBe(true);
    expect(seg("boardy")(P({ boardy: {} }))).toBe(false);
    expect(seg("omar")(P({ introduced_by_name: "Omar Hedeya" }))).toBe(true);
    expect(seg("omar")(P({ intro_route: "via OMAR" }))).toBe(true);
    // the introducer's name wins over the route when both are set (`||`, as before)
    expect(seg("omar")(P({ introduced_by_name: "Lena", intro_route: "Omar" }))).toBe(false);
    expect(seg("events")(P({ events: [{}] }))).toBe(true);
    expect(seg("events")(P({ discovery: "Met at the Hannover Messe EVENT" }))).toBe(true);
    expect(seg("events")(P({ discovery: "Boardy" }))).toBe(false);
  });

  it("new this month: a relationship state reached in the client's UTC month", () => {
    at("2026-11-11T12:00:00Z");
    const h = (to: string, on: string) => P({ state_history: [{ to, on }] });
    expect(NEW_STATES).toHaveLength(8);
    for (const s of NEW_STATES) expect(seg("newmonth")(h(s, "2026-11-01"))).toBe(true);
    expect(seg("newmonth")(h("contacted", "2026-10-31"))).toBe(false);
    expect(seg("newmonth")(h("watching", "2026-11-05"))).toBe(false);
    expect(seg("newmonth")(P())).toBe(false);
  });

  it("new this month reads the UTC month, not Berlin's, around midnight on the 1st", () => {
    at("2026-11-30T23:30:00Z"); // already 1 December 00:30 in Berlin
    expect(berlinDate(new Date())).toBe("2026-12-01");
    expect(seg("newmonth")(P({ state_history: [{ to: "contacted", on: "2026-11-05" }] }))).toBe(true);
    expect(seg("newmonth")(P({ state_history: [{ to: "contacted", on: "2026-12-01" }] }))).toBe(false);
  });

  it("cities are c:<city>; an unknown segment lets everyone through", () => {
    expect(seg("c:Berlin")(P({ location: "Berlin, Germany" }))).toBe(true);
    expect(seg("c:Berlin")(P({ location: "Berlin-Mitte" }))).toBe(false);
    expect(seg("bogus")(P())).toBe(true);
    expect(seg("all")(P())).toBe(true);
  });

  it("top cities: most people first, at most four, ties in first-seen order, no empty city", () => {
    const ps = ["Munich", "Berlin", "Berlin", "Paris", "Rome", "Oslo", "", "Munich"].map((c, i) => P({ id: `p${i}`, location: c ? `${c}, X` : "" }));
    expect(topCities(ps)).toEqual([
      ["Munich", 2],
      ["Berlin", 2],
      ["Paris", 1],
      ["Rome", 1],
    ]);
  });
});

describe("peopleUtil — today() is the client's UTC date (the old quirk)", () => {
  it("one hour before Berlin midnight both agree", () => {
    at("2026-11-11T21:59:59Z");
    expect(today()).toBe("2026-11-11");
    expect(berlinDate(new Date())).toBe("2026-11-11");
  });

  it("after Berlin midnight the client still says yesterday until UTC midnight", () => {
    at("2026-11-11T23:30:00Z");
    expect(berlinDate(new Date())).toBe("2026-11-12");
    expect(today()).toBe("2026-11-11");
    at("2026-11-12T00:00:00Z");
    expect(today()).toBe("2026-11-12");
  });

  it("in summer time the gap is two hours", () => {
    at("2026-07-01T22:30:00Z");
    expect(berlinDate(new Date())).toBe("2026-07-02");
    expect(today()).toBe("2026-07-01");
  });
});
