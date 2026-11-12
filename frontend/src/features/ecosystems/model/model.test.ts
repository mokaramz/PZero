import { describe, expect, it } from "vitest";

import { coverage, registry } from "../test/server";
import { adoptMessage, familyCounts, familyShort, filterEcosystems, sourceLine, stateTone } from "./coverage";
import { chipDots, chipTitle, splitRegistry } from "./registry";

describe("coverage rules", () => {
  it("tones: HEALTHY green, PARTIAL amber, GAP red, anything else neutral", () => {
    expect(["HEALTHY", "PARTIAL", "GAP", "UNKNOWN", "ODD", undefined].map(stateTone)).toEqual(["green", "amber", "red", "neutral", "neutral", "neutral"]);
  });

  it("the filter is case-insensitive over city, country name and region", () => {
    const list = coverage().ecosystems;
    expect(filterEcosystems(list, "").map((e) => e.city)).toEqual(["Alderwick", "Brightmoor", "Cobbleton"]);
    expect(filterEcosystems(list, "NORTH").map((e) => e.city)).toEqual(["Alderwick"]);
    expect(filterEcosystems(list, "eastland").map((e) => e.city)).toEqual(["Brightmoor"]);
  });

  it("family labels, counters and source lines", () => {
    expect(familyShort("Founder formation / talent exits")).toBe("Founder formation");
    expect(familyShort("Grants")).toBe("Grants");
    expect(familyCounts(undefined)).toBe("0 cfg · 0 ok · 0 prod");
    expect(sourceLine({ id: "x", name: "N", origin: "o", retrieved: true, productive: false, failing: true, declared_by: "d" })).toBe(
      "N [o] — retrieved  · no records · failing (d)",
    );
  });

  it("the adopt toast keeps the old wording, also for an `already` answer without a note", () => {
    expect(adoptMessage({ ok: true, source_id: "cov-1", note: "stays UNKNOWN" })).toBe("Adopted as watcher cov-1 — stays UNKNOWN");
    expect(adoptMessage({ ok: true, already: true, source_id: "cov-1" })).toBe("Adopted as watcher cov-1 — ");
  });
});

describe("registry rules", () => {
  it("splits curated and detected, keeping the registry order, by a case-insensitive name match", () => {
    const r = registry();
    const names = (q: string) => {
      const s = splitRegistry(r, q);
      return [s.curated.map((x) => x.name), s.detected.map((x) => x.name)];
    };
    expect(names("")).toEqual([["Karlsruhe", "Alderwick", "Brightmoor"], ["Cobbleton"]]);
    expect(names("OB")).toEqual([[], ["Cobbleton"]]);
    expect(names("r")).toEqual([["Karlsruhe", "Alderwick", "Brightmoor"], []]);
  });

  it("dots and the chip title", () => {
    const [home, alder] = registry().cities;
    expect(chipDots(alder)).toEqual([true, false, false, true]);
    expect(chipTitle(home)).toBe("startups 2 · events 2 · people 1 · institutions 2 · last refresh 2026-11-01");
    expect(chipTitle(alder)).toBe("startups 1 · events 0 · people 0 · institutions 1");
  });
});
