import { describe, expect, it } from "vitest";

import { att, attWhy, lensRank, recScore, srcDate } from "./attention";
import { DEFAULT_WS_GEOS, geoOk, region, repInWS } from "./geo";
import { buildList } from "./list";
import { isNonStartup, type TriageSummary } from "./triage";
import type { Candidate } from "./types";

const cand = (x: Partial<Candidate>) => x as Candidate;
const DAY = 864e5;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * DAY).toISOString().slice(0, 10);

describe("region (workspace routing — v1 rules)", () => {
  it("routes by explicit country/location first", () => {
    expect(region({ location: "Munich, Germany" })).toBe("eu");
    expect(region({ location: "Austin, TX" })).toBe("us");
    expect(region({ location: "Waterloo" })).toBe("ca");
    expect(region({ country: "CH" })).toBe("eu");
  });
  it("falls back to the source geo scope without location evidence", () => {
    expect(region({ geo: ["US"] })).toBe("us");
    expect(region({ geo_scope: "region-eu" })).toBe("eu");
    expect(region({ geo_scope: "global" })).toBe("unknown"); // never silently defaults to Europe
  });
});

describe("geoOk", () => {
  it("keeps workspaces disjoint and honours the NA sub-filter", () => {
    const us = { location: "Boston, MA" };
    expect(geoOk(us, "eu", "both")).toBe(false);
    expect(geoOk(us, "na", "both")).toBe(true);
    expect(geoOk(us, "na", "ca")).toBe(false);
    expect(geoOk({ geo_scope: "global" }, "unk", "both")).toBe(true);
    expect(geoOk({ geo_scope: "global" }, "eu", "both")).toBe(false);
  });
});

describe("repInWS (scan report rows)", () => {
  it("shows system and ALL-geo rows everywhere, others by workspace geo tags", () => {
    expect(repInWS({ tier: "system", geo: [] } as never, "na", DEFAULT_WS_GEOS)).toBe(true);
    expect(repInWS({ geo: ["ALL"] } as never, "na", DEFAULT_WS_GEOS)).toBe(true);
    expect(repInWS({ geo: ["DACH"] } as never, "eu", DEFAULT_WS_GEOS)).toBe(true);
    expect(repInWS({ geo: ["DACH"] } as never, "na", DEFAULT_WS_GEOS)).toBe(false);
  });
});

describe("attention score", () => {
  it("uses only real source dates for freshness (unknown date = 0, never guessed)", () => {
    expect(srcDate(cand({ date: "2026-01-01", date_kind: "seen" } as Partial<Candidate>))).toBeNull();
    expect(recScore(cand({}))).toBe(0);
    expect(recScore(cand({ source_date: iso(3) }))).toBe(3);
    expect(recScore(cand({ source_date: iso(20) }))).toBe(2);
    expect(recScore(cand({ source_date: iso(200) }))).toBe(0);
  });
  it("adds earliness, fit, quality, cross-source and feedback, and explains every point", () => {
    const c = cand({ discovery_tier: "pre_company", source_date: iso(1), archetype_hits: [1, 2, 3], twins: ["x"], also_seen: [{ source: "a" }], feedback: { adjustment: 2 } } as Partial<Candidate>);
    // freshness 3*2 + earliness 3 + fit min(3,2)*2+1 + quality 1 + cross 2 + feedback 2
    expect(att(c)).toBe(6 + 3 + 5 + 1 + 2 + 2);
    expect(attWhy(c)).toContain(`attention ${att(c)} = freshness 6`);
  });
  it("Investment Manager lens ranks by attention v2 final, ties by attention", () => {
    const a = cand({ attention_v2: { final: 10 } } as Partial<Candidate>);
    const b = cand({ attention_v2: { final: 20 } } as Partial<Candidate>);
    expect([a, b].sort((x, y) => lensRank(x, y, true))[0]).toBe(b);
  });
});


describe("buildList — the per-workspace Attention queue", () => {
  const eu = (id: string, extra: Partial<Candidate> = {}) => cand({ id, name: id, decision: "new", location: "Berlin, Germany", ...extra });
  const opts = { ws: "eu" as const, naf: "both" as const, theme: "", im: false, filter: "top" as const, lastRun: "r1" };

  it("keeps 15, counts the rest as hidden, and breaks ties by priority then payload order", () => {
    const pool = Array.from({ length: 18 }, (_, i) => eu(`c${i}`, { priority: i < 4 ? 9 : 1 }));
    const { list, hidden } = buildList(pool, opts);
    expect(list.map((c) => c.id).slice(0, 5)).toEqual(["c0", "c1", "c2", "c3", "c4"]);
    expect(list).toHaveLength(15);
    expect(hidden).toBe(3);
    expect(list.at(-1)?.id).toBe("c14"); // equal score and priority across the cutoff: payload order decides
  });

  it("drops gated, decided, other-workspace and non-startup candidates from the queue", () => {
    const tri = { ns: { routing: { queue: "non_startup", reason: "" } } as TriageSummary };
    const pool = [eu("ok"), eu("gated", { attention_v2: { gated: "noise" } }), eu("done", { decision: "kept" }), cand({ id: "us", name: "us", decision: "new", location: "Austin, TX" }), eu("ns")];
    expect(buildList(pool, { ...opts, skip: isNonStartup(tri) }).list.map((c) => c.id)).toEqual(["ok"]);
    expect(buildList(pool, opts).counts).toEqual({ new: 3, kept: 1 });
  });

  it("the IM lens orders by attention v2 final plus feedback", () => {
    const pool = [eu("low", { attention_v2: { final: 5 } }), eu("high", { attention_v2: { final: 9 } })];
    expect(buildList(pool, { ...opts, im: true }).list.map((c) => c.id)).toEqual(["high", "low"]);
  });

  it("thisrun excludes baseline; per-decision filters list that decision", () => {
    const pool = [eu("a", { run_id: "r1" }), eu("b", { run_id: "r1", decision: "baseline" }), eu("c", { decision: "watch" })];
    expect(buildList(pool, { ...opts, filter: "thisrun" }).list.map((c) => c.id)).toEqual(["a"]);
    expect(buildList(pool, { ...opts, filter: "watch" }).list.map((c) => c.id)).toEqual(["c"]);
  });
});
