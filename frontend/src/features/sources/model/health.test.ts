import { describe, expect, it } from "vitest";

import { coverageLevel, fbPrio, healthCounts, latestScan, limitation, scanTone, sourcesInWs, srcHealth, srcWs, wsGeoSet } from "./health";
import type { Source, SourcesPayload } from "./types";

const src = (extra: Partial<Source> = {}): Source => ({ id: "x", name: "Copper Valley Awards", enabled: true, last_ok: "2026-11-01 08:00", ...extra });

describe("source health", () => {
  it("disabled wins; 3+ failures in a row is failed; any failure warns; never scanned warns; else healthy", () => {
    expect(srcHealth(src({ enabled: false, failures_in_row: 5 }))).toEqual(["off", "Disabled"]);
    expect(srcHealth(src({ failures_in_row: 3 }))).toEqual(["failed", "Failing — 3 consecutive failures"]);
    expect(srcHealth(src({ failures_in_row: 4 }))).toEqual(["failed", "Failing — 4 consecutive failures"]);
    expect(srcHealth(src({ failures_in_row: 1 }))).toEqual(["warn", "Warning — 1 recent failure"]);
    expect(srcHealth(src({ failures_in_row: 2 }))).toEqual(["warn", "Warning — 2 recent failures"]);
    expect(srcHealth(src({ last_ok: null }))).toEqual(["warn", "Not yet scanned"]);
    expect(srcHealth(src({ last_ok: undefined, failures_in_row: 0 }))).toEqual(["warn", "Not yet scanned"]);
    expect(srcHealth(src())).toEqual(["ok", "Healthy"]);
  });

  it("counts every state", () => {
    expect(healthCounts([src(), src({ enabled: false }), src({ failures_in_row: 3 }), src({ last_ok: null }), src({ failures_in_row: 1 })])).toEqual({
      ok: 1,
      warn: 2,
      failed: 1,
      off: 1,
    });
  });
});

describe("workspace", () => {
  const m = { geos: ["DACH", "US", "CA"], sources: [src({ id: "a", geo: ["DACH"] }), src({ id: "b", geo: ["US"] }), src({ id: "c" })] } as SourcesPayload;
  const geos = { eu: ["DACH"], na: ["US", "CA"] };
  it("Unresolved shows all sources; the others are themselves", () => {
    expect(srcWs("unk")).toBe("all");
    expect(srcWs("eu")).toBe("eu");
    expect(srcWs("na")).toBe("na");
  });
  it("filters by the workspace's geo tags; all keeps every source, even untagged ones", () => {
    expect(wsGeoSet("all", m, geos)).toEqual(["DACH", "US", "CA"]);
    expect(sourcesInWs(m, "eu", wsGeoSet("eu", m, geos)).map((s) => s.id)).toEqual(["a"]);
    expect(sourcesInWs(m, "na", wsGeoSet("na", m, geos)).map((s) => s.id)).toEqual(["b"]);
    expect(sourcesInWs(m, "all", wsGeoSet("all", m, geos)).map((s) => s.id)).toEqual(["a", "b", "c"]);
  });
});

describe("feedback priority cell", () => {
  it("shows the signed adjustment when active, else 0 and reviewed / minimum", () => {
    expect(fbPrio({ active: true, adjustment: 2 })).toEqual({ value: "+2" });
    expect(fbPrio({ active: true, adjustment: -1 })).toEqual({ value: "-1" });
    expect(fbPrio({ active: true, adjustment: 0 })).toEqual({ value: "0" });
    expect(fbPrio({ active: false, reviewed: 3 }, 6)).toEqual({ value: "0", progress: "3/6" });
    expect(fbPrio({})).toEqual({ value: "0", progress: "0/5" });
  });
});

describe("limitations", () => {
  it("notes that say partial / lazy / js-only win over health", () => {
    for (const notes of ["Only a PARTIAL list", "lazy-loaded entries", "a JS-only page"]) {
      expect(limitation(src({ notes, failures_in_row: 3 }))).toBe(notes);
    }
  });
  it("a failing source, a warning source, then nothing", () => {
    expect(limitation(src({ failures_in_row: 3, notes: "plain" }))).toBe(
      "Consecutive failures — the site may have changed or be unreachable; the scan retries automatically and nothing is invented.",
    );
    expect(limitation(src({ failures_in_row: 1 }))).toBe("A recent failure or no scan yet; monitored on the next run.");
    expect(limitation(src({ last_ok: null }))).toBe("A recent failure or no scan yet; monitored on the next run.");
    expect(limitation(src())).toBeNull();
    expect(limitation(src({ enabled: false, failures_in_row: 4 }))).toBeNull();
  });
});

describe("latest scan result", () => {
  const report = [
    { source: "Birch Fund list", status: "ok" },
    { source: "Copper Valley Awards — 2026 round", status: "fail" },
    { source: "Copper Valley Awards", status: "ok" },
  ];
  it("matches by the exact name or by the name before ' (' — the first matching row wins", () => {
    expect(latestScan(src({ name: "Copper Valley Awards (EU)" }), report)?.source).toBe("Copper Valley Awards — 2026 round");
    expect(latestScan(src({ name: "Birch Fund list" }), report)?.status).toBe("ok");
    expect(latestScan(src({ name: "Granite Labs" }), report)).toBeUndefined();
  });
  it("tones: ok green, fail / error red, anything else amber", () => {
    expect(scanTone("ok")).toBe("green");
    expect(scanTone("fail")).toBe("red");
    expect(scanTone("error")).toBe("red");
    expect(scanTone("skipped")).toBe("amber");
    expect(scanTone(undefined)).toBe("amber");
  });
});

describe("coverage thresholds", () => {
  it("none ≤ 0 < weak < 2 ≤ ok < 4 ≤ strong", () => {
    expect([-1, 0, 0.1, 1.9, 2, 3.9, 4, 9].map(coverageLevel)).toEqual(["none", "none", "weak", "weak", "ok", "ok", "strong", "strong"]);
  });
});
