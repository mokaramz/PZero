import { describe, expect, it } from "vitest";

import { dayLabel, timeLabel, travelLine } from "../components/bits";
import { audienceSignal, costLine, evFormat, ladderLevel, peopleIn, priceText, tierTone } from "./eventUtil";
import type { EventRecord } from "./types";

const ev = (p: Partial<EventRecord>): EventRecord => ({ id: "e", name: "Synthetic Meetup", sc: { total: null, band: "", evidence: [] }, ...p });

describe("eventUtil (ported verbatim from the old module)", () => {
  it("price line and price text", () => {
    expect(costLine(ev({ price_state: "free" }))).toBe("FREE");
    expect(costLine(ev({ price_state: "price range", price: { low: 10, high: 20, currency: "EUR" } }))).toBe("10–20 EUR");
    expect(costLine(ev({ price_state: "paid", price: { amount: 15 } }))).toBe("15");
    expect(costLine(ev({}))).toBe("PRICE UNKNOWN");
    expect(priceText({ availability: "https://schema.org/SoldOut" })).toBe("sold out");
    expect(priceText("about 20 EUR")).toBe("about 20 EUR");
  });

  it("format: stored, else inferred and labelled", () => {
    expect(evFormat(ev({ format: "physical" }))).toBe("Physical");
    expect(evFormat(ev({ format: "hybrid" }))).toBe("Hybrid");
    expect(evFormat(ev({ name: "Online founder webinar" }))).toBe("Virtual (inferred)");
    expect(evFormat(ev({}))).toBe("");
  });

  it("ladder bands, tiers and the stated audience", () => {
    expect(ladderLevel(null, 25)).toEqual(["NOT ENOUGH INFORMATION", "neutral"]);
    expect(ladderLevel(18, 25)).toEqual(["HIGH", "green"]);
    expect(ladderLevel(10, 25)).toEqual(["MEDIUM", "amber"]);
    expect(ladderLevel(9, 25)).toEqual(["LOW", "red"]);
    expect(tierTone(ev({}))).toBe("amber");
    expect(audienceSignal(ev({ notes: "mostly founders" }))).toEqual(["FOUNDER-HEAVY (stated)", "green"]);
  });

  it("people whose location mentions the event city", () => {
    const ppl = [{ id: "a", location: "Berlin, Germany" }, { id: "b", location: "Munich" }, { id: "c" }];
    expect(peopleIn(ppl, "berlin").map((p) => p.id)).toEqual(["a"]);
    expect(peopleIn(ppl, undefined)).toEqual([]);
  });
});

describe("bits", () => {
  it("times, travel and day headings", () => {
    expect(timeLabel("16:00")).toBe("4:00 PM");
    expect(timeLabel("00:30")).toBe("12:30 AM");
    expect(timeLabel("")).toBe("Time not stated");
    expect(travelLine(0)).toBe("in Karlsruhe");
    expect(travelLine(2.5)).toBe("2.5 h from Karlsruhe");
    expect(travelLine(null)).toBe("");
    expect(dayLabel("2026-11-11", "2026-11-11")).toEqual(["Today", "Wednesday"]);
    expect(dayLabel("2026-11-12", "2026-11-11")).toEqual(["Tomorrow", "Thursday"]);
    expect(dayLabel("2027-01-04", "2026-11-11")).toEqual(["4 Jan 2027", "Monday"]);
    expect(dayLabel("", "2026-11-11")).toEqual(["Date not stated", ""]);
  });
});
