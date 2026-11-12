import { describe, expect, it } from "vitest";

import { sources } from "../test/fixtures";
import { NOT_PORTED } from "./deferred";
import {
  authorityLine,
  biasLine,
  collecting,
  coverageLine,
  earlyLine,
  fmtAt,
  hours,
  originalityLine,
  pct,
  ranked,
  relevanceLine,
  sourceMeta,
  speedLine,
  statusTone,
  technical,
  uniqueLine,
  WINDOWS,
} from "./sources";

const row = (name: string, w: "30" | "90" | "180" | "all" = "90") => sources(w).sources.find((s) => s.name === name)!;

describe("the sources view", () => {
  it("has the four old windows", () => {
    expect(WINDOWS.map((w) => [w.value, w.label])).toEqual([
      ["30", "30 days"],
      ["90", "90 days"],
      ["180", "180 days"],
      ["all", "All time"],
    ]);
  });
  it("rates, hours and the measured-at time", () => {
    expect(pct({ k: 9, n: 14, rate: 0.643, lb: 0.4, label: "EARLY READ" })).toBe("64% (9/14)");
    expect(pct({ k: 0, n: 0, rate: null, lb: 0, label: "INSUFFICIENT DATA" })).toBe("—");
    expect(pct(undefined)).toBe("—");
    expect(hours(undefined)).toBe("—");
    expect(hours(6.5)).toBe("6.5 h");
    expect(hours(96)).toBe("4 days");
    expect(fmtAt("2026-11-12T07:00:39")).toBe("2026-11-12 07:00");
    expect(fmtAt(null)).toBe("not yet");
    expect(statusTone("DEGRADED")).toBe("amber");
    expect(statusTone("NEW STATE")).toBe("neutral");
  });
  it("ranks the purposes with a leader and groups the rest by what is missing (90 days)", () => {
    const d = sources("90");
    expect(ranked(d.best).map((b) => `${b.label}: ${b.leader.source}`)).toEqual([
      "Best for Europe-wide coverage: Alpine Wire",
      "Best for Germany: Alpine Wire",
      "Best for the UK: Alpine Wire",
      "Best for Munich: Isar Startup Post",
      "Best for early signals: Isar Startup Post",
      "Best for fact confirmation: Alpine Wire",
      "Best for unique discovery: Alpine Wire",
      "Best for physical AI / deeptech: Alpine Wire",
      "Best technical reliability: Baltic Founders",
    ]);
    expect(collecting(d.best)).toEqual([
      ["needs ≥ 8 France events reported by other sources, and a source covering ≥ 3 of them", ["France"]],
      ["needs ≥ 8 Switzerland events reported by other sources, and a source covering ≥ 3 of them", ["Switzerland"]],
      ["needs ≥ 8 Nordics events reported by other sources, and a source covering ≥ 3 of them", ["the Nordics"]],
    ]);
  });
  it("with too little overlap (30 days) the coverage purposes share one reason", () => {
    const d = sources("30");
    expect(d.bias.overlap_ok).toBe(false);
    expect(ranked(d.best).map((b) => b.id)).toEqual(["TECH"]);
    expect(collecting(d.best)).toEqual([
      [
        "sources overlap on only 4 events — coverage comparisons need ≥ 8 events reported by two or more sources",
        ["Europe-wide coverage", "Germany", "France", "the UK", "Switzerland", "the Nordics", "Munich", "unique discovery", "physical AI / deeptech"],
      ],
      ["needs ≥ 3 observations for at least one source", ["early signals"]],
      ["needs ≥ 8 observations for at least one source", ["fact confirmation"]],
    ]);
    expect(biasLine(d.bias)).toBe("4 of 10 material events were reported by two or more sources.");
  });
  it("the row header", () => {
    const d = sources("90");
    expect(sourceMeta(row("Isar Startup Post"), d.scopes)).toBe("Munich · 96 articles · more reliable");
    expect(sourceMeta(row("Ledger Gazette"), d.scopes)).toBe("external benchmark · 3 articles · insufficient data");
  });
  it("the details of one source", () => {
    const d = sources("90");
    const isar = row("Isar Startup Post");
    expect(coverageLine(isar, d.scopes)).toBe("Europe 36% (12/33) · Germany 56% (9/16) · Munich 64% (9/14)");
    expect(coverageLine(row("Ledger Gazette"), d.scopes)).toBe("—");
    expect(speedLine(isar)).toBe("median 6.5 h · within 24 h 82% (9/11) · first 46% (5/11) (11 shared events, hour-precision)");
    expect(earlyLine(isar)).toBe(
      "4 companies mentioned ≥ 14 days before their material event (median 52 days) — e.g. Vantor Kinetics 61 days, Fennick Audio 33 days, Trellis Mobility 21 days",
    );
    expect(earlyLine(row("Channel Tech Review"))).toBe("0 companies mentioned ≥ 14 days before their material event");
    expect(uniqueLine(isar)).toBe("6 material events and 3 early companies no other source had");
    expect(relevanceLine(isar)).toBe("33% (32/96) of its articles were material European events");
    expect(originalityLine(isar)).toBe("syndicated copies 4% (4/96) · press-release markers 9% (9/96)");
    expect(authorityLine(isar)).toBe("specialist media · facts agreed 7, contradicted 1, open 1 (observed)");
  });
  it("technical health: measured from the run log, UNKNOWN for the Swiss ticker until System health is ported", () => {
    expect(technical(row("Isar Startup Post"))).toEqual({ deferred: false, text: "healthy · fetched 28/28 runs (News run log)" });
    expect(technical(row("Channel Tech Review"))).toEqual({ deferred: false, text: "degraded · fetched 24/28 runs · 2 failure(s) in a row (News run log)" });
    expect(technical(row("Ledger Gazette"))).toEqual({ deferred: false, text: "not fetched (external — not fetched)" });
    const swiss = row("Swiss deal ticker");
    expect(technical(swiss)).toEqual({ deferred: true, text: `UNKNOWN (${NOT_PORTED.health})` });
    // whatever the payload says (the old answer came from System health)
    expect(technical({ ...swiss, technical: { ...swiss.technical, state: "HEALTHY", basis: "Deal Flow source health" } }).text).toBe(
      "UNKNOWN (System health arrives with its port)",
    );
  });
});
