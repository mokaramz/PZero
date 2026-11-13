/** Time-aware greeting: fixed instants and explicit time zones — never the developer machine's clock or location. */
import { describe, expect, it } from "vitest";

import { contextLine, greeting, localHour } from "./greeting";

const at = (iso: string) => new Date(iso); // UTC instants
const BERLIN = "Europe/Berlin"; // UTC+1 in November
const NEW_YORK = "America/New_York"; // UTC-5 in November

describe("greeting", () => {
  it.each([
    ["2026-11-02T04:00:00Z", "Good morning, Smooth Operator."], // 05:00 Berlin
    ["2026-11-02T10:59:00Z", "Good morning, Smooth Operator."], // 11:59
    ["2026-11-02T11:00:00Z", "Good afternoon, Smooth Operator."], // 12:00
    ["2026-11-02T15:59:00Z", "Good afternoon, Smooth Operator."], // 16:59
    ["2026-11-02T16:00:00Z", "Good evening, Smooth Operator."], // 17:00
    ["2026-11-02T16:43:00Z", "Good evening, Smooth Operator."], // 17:43
    ["2026-11-02T21:59:00Z", "Good evening, Smooth Operator."], // 22:59
    ["2026-11-02T22:00:00Z", "Welcome back, Smooth Operator."], // 23:00
    ["2026-11-03T02:30:00Z", "Welcome back, Smooth Operator."], // 03:30
    ["2026-11-03T03:59:00Z", "Welcome back, Smooth Operator."], // 04:59
  ])("%s in Berlin → %s", (iso, want) => {
    expect(greeting(at(iso), BERLIN)).toBe(want);
  });

  it("follows the time zone, not UTC: the same instant is evening in Berlin and morning in New York", () => {
    const t = at("2026-11-02T16:43:00Z");
    expect(localHour(t, BERLIN)).toBe(17);
    expect(localHour(t, NEW_YORK)).toBe(11);
    expect(greeting(t, BERLIN)).toBe("Good evening, Smooth Operator.");
    expect(greeting(t, NEW_YORK)).toBe("Good morning, Smooth Operator.");
  });

  it("uses daylight-saving time correctly (Berlin summer = UTC+2)", () => {
    expect(greeting(at("2026-07-01T10:30:00Z"), BERLIN)).toBe("Good afternoon, Smooth Operator."); // 12:30 CEST
  });

  it("speaks to the role, never a personal name", () => {
    expect(greeting(at("2026-11-02T08:00:00Z"), BERLIN)).not.toMatch(/Mohamed/);
  });
});

describe("contextLine", () => {
  it("is a quiet day + time line in the same zone", () => {
    expect(contextLine(at("2026-11-02T16:43:00Z"), BERLIN)).toBe("Monday, 2 Nov · 17:43");
    expect(contextLine(at("2026-11-02T16:43:00Z"), NEW_YORK)).toBe("Monday, 2 Nov · 11:43");
  });
});
