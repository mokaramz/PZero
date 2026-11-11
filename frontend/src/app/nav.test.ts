import { describe, expect, it } from "vitest";

import { ALL_ITEMS, NAV, pathForLegacyView } from "./nav";

describe("navigation", () => {
  it("covers the 14 remaining v1 views (plus the Phase 2 views) exactly once", () => {
    // Scout Intake ("scout") and Scout Bridge ("bridge") were merged into Deal Flow and have no page of their own
    const v1 = ["home", "inbox", "src", "pipe", "people", "founders", "events", "map", "eco", "radar", "work", "watch", "calls", "evaluator"];
    const phase2 = ["today", "validation", "health", "news", "associate"];
    expect(ALL_ITEMS.map((i) => i.legacyView).sort()).toEqual([...v1, ...phase2].sort());
    expect(new Set(ALL_ITEMS.map((i) => i.path)).size).toBe(ALL_ITEMS.length);
  });
  it("keeps the old sections and order, without Scout Intake and Scout Bridge", () => {
    expect(NAV.map((s) => s.title)).toEqual([null, "Sourcing", "Judgment", "Network"]);
    expect(NAV[1].items.map((i) => i.label)).toEqual(["Deal Flow", "Sources", "Events", "Map", "Ecosystems"]);
    expect(ALL_ITEMS.some((i) => i.path === "/scout-intake" || i.path === "/scout-bridge")).toBe(false);
  });
  it("maps v1 hash deep links to v2 routes", () => {
    expect(pathForLegacyView("pipe")).toBe("/conviction");
    expect(pathForLegacyView("founders")).toBe("/founder-radar");
    expect(pathForLegacyView("inbox")).toBe("/deal-flow");
    expect(pathForLegacyView("scout")).toBe("/deal-flow");
    expect(pathForLegacyView("bridge")).toBe("/deal-flow");
    expect(pathForLegacyView("nope")).toBeUndefined();
  });
});
