/** The protected client rules (logic.ts, ported verbatim — review 011): the old tests, plus a boundary test pinning each
 *  of the three known differences from the server so a "fix" cannot slip in unnoticed (011 decision c, Codex). */
import { describe, expect, it } from "vitest";

import { labelFor } from "@/lib/activity";
import { convergenceSources, currentState, isGated, liveScore, pipeGroups, pzView, type LiveInput } from "./logic";
import type { Signal } from "./types";

const sig = (slug: string, prov: number, extra: Partial<Signal> = {}) =>
  ({ slug, company: slug, status: "new", conflict: "none", sc: { provisional: prov, verified: 0, verdict: "WATCH" }, ...extra }) as unknown as Signal;
const slugs = (xs: Signal[]) => xs.map((e) => e.slug);

const BASE: LiveInput = {
  founder: 15,
  venture_scale: 15,
  why_now: 10,
  taste: 10,
  insight: 10,
  earliness: "pre_seed",
  conflict: "none",
  penalties: [],
  v_founders: false,
  v_traction: false,
  v_funding: false,
};

describe("case preparation actions say what they do (Background activity)", () => {
  it("every case action has a plain label", () => {
    for (const p of ["case_prepare", "case_reviewer", "case_committee", "case_committee_request", "case_external_job"]) {
      expect(labelFor(p), p).not.toBe("Working");
    }
  });
  it("recording a why-now trigger is not described as starting IMQ", () => {
    expect(labelFor("imq_trigger")).toBe("Recording the why-now trigger");
  });
});

describe("Conviction list follows the one operator state", () => {
  const op = (slug: string, prov: number, status?: string) => sig(slug, prov, { op: status ? ({ status } as Signal["op"]) : undefined });
  it("a WATCHING company is listed under Watch even in the 65–79 band; an active one stays in Investigate", () => {
    const g = pipeGroups([op("held", 65, "WATCHING"), op("active", 69, "READY FOR MOHAMED"), op("band", 70)], "");
    expect(slugs(g.watch)).toEqual(["held"]);
    expect(slugs(g.inv)).toEqual(["band", "active"]);
  });
  it("dropped entries are hidden; the filter matches anything in the record", () => {
    const all = [sig("a", 70, { one_liner: "grid batteries" }), sig("b", 70, { status: "dropped" }), sig("c", 50)];
    const g = pipeGroups(all, "");
    expect([...slugs(g.inv), ...slugs(g.watch), ...slugs(g.gated)]).toEqual(["a", "c"]);
    expect(slugs(pipeGroups(all, "  BATTERIES ").inv)).toEqual(["a"]);
  });
});

describe("quirk 1 — Investigate is provisional ≥ 63 (the server bands are 65 and 80)", () => {
  it("62 is Watch, 63 and 64 are Investigate — below the server's 65", () => {
    const g = pipeGroups([sig("p62", 62), sig("p63", 63), sig("p64", 64), sig("p65", 65)], "");
    expect(slugs(g.inv)).toEqual(["p65", "p64", "p63"]);
    expect(slugs(g.watch)).toEqual(["p62"]);
  });
});

describe("quirk 2 — isGated covers only potential_conflict (the server also gates unclear)", () => {
  it("unclear is listed by score, potential_conflict is gated whatever the score", () => {
    expect(isGated(sig("u", 90, { conflict: "unclear" }))).toBe(false);
    expect(isGated(sig("p", 90, { conflict: "potential_conflict" }))).toBe(true);
    const g = pipeGroups([sig("u", 90, { conflict: "unclear" }), sig("p", 90, { conflict: "potential_conflict" })], "");
    expect(slugs(g.inv)).toEqual(["u"]);
    expect(slugs(g.gated)).toEqual(["p"]);
    expect(currentState(sig("u", 90, { conflict: "unclear" })).tone).toBe("neutral");
    expect(currentState(sig("p", 90, { conflict: "potential_conflict", twin: "Acme" }))).toMatchObject({ label: "Conflict gated", tone: "risk" });
    expect(pzView(sig("p", 90, { conflict: "potential_conflict" }))).toBe("Hold until Manager answers the conflict");
  });
});

describe("quirk 3 — liveScore keeps the resemblance bonus for archetype #15 (the server zeroes it)", () => {
  it("complementary is +5 and similar +4 on both numbers; the preview takes no archetype at all", () => {
    const none = liveScore(BASE);
    const comp = liveScore({ ...BASE, conflict: "complementary" });
    const sim = liveScore({ ...BASE, conflict: "similar" });
    expect(comp.prov - none.prov).toBe(5);
    expect(comp.ver - none.ver).toBe(5);
    expect(sim.prov - none.prov).toBe(4);
    // an archetype #15 entry previews the same numbers (the input has no archetype field to zero it with)
    expect(liveScore({ ...BASE, conflict: "complementary", archetype: 15 } as LiveInput)).toEqual(comp);
  });
});

describe("liveScore — the preview formula", () => {
  it("adds the blocks, earliness and penalties; verified zeroes unverified founders and funding and halves traction", () => {
    // 15 + 15 + 10 + 10 + 6 (pre_seed) + 10
    expect(liveScore(BASE)).toEqual({ prov: 66, ver: 40, missLabel: "unverified: founders, traction, funding" });
    // insight 10 → floor(10 / 2) = 5 unverified; earliness counts only once funding is verified
    expect(liveScore({ ...BASE, v_founders: true, v_traction: true, v_funding: true })).toEqual({ prov: 66, ver: 66, missLabel: "fully verified" });
    expect(liveScore({ ...BASE, insight: 15 }).ver).toBe(15 + 10 + 10 + 7);
  });
  it("potential_conflict costs 25 on top of the penalties; both numbers stay within 0–100", () => {
    expect(liveScore({ ...BASE, conflict: "potential_conflict" }).prov).toBe(41);
    expect(liveScore({ ...BASE, penalties: ["consumer", "wrapper", "unknown-key"] }).prov).toBe(36);
    expect(liveScore({ ...BASE, conflict: "potential_conflict", penalties: ["consumer", "non_eu", "known", "wrapper"] })).toMatchObject({ prov: 0, ver: 0 });
    const max = { ...BASE, founder: 40, venture_scale: 40, why_now: 40, taste: 40, insight: 40, earliness: "pre_company", v_founders: true, v_traction: true, v_funding: true };
    expect(liveScore(max)).toMatchObject({ prov: 100, ver: 100 });
  });
  it("an unknown earliness counts 0", () => {
    expect(liveScore({ ...BASE, earliness: "whatever" }).prov).toBe(60);
  });
});

/** Convergence inputs are REAL and independent: one publication counted once, Scout 00 cycles distinct, never invented. */
describe("convergenceSources", () => {
  const s = (over: Partial<Signal>) => ({ slug: "x", company: "X", sc: {}, ...over }) as unknown as Signal;
  it("counts a publication and its own domain once", () => {
    expect(convergenceSources(s({ discovery_source: "ArcticStartup announcements", sources: ["https://arcticstartup.com/a"] }))).toEqual([
      "ArcticStartup announcements",
    ]);
  });
  it("keeps genuinely independent inputs, Scout 00 cycles included", () => {
    const e = s({
      discovery_source: "EU-Startups",
      sources: ["https://www.tech.eu/x", "https://sifted.eu/y"],
      scout_provenance: [{ scout_cycle_id: "006" }, { scout_cycle_id: "007" }],
    });
    expect(convergenceSources(e)).toEqual(["EU-Startups", "tech.eu", "sifted.eu", "Scout 00 · cycle 006", "Scout 00 · cycle 007"]);
  });
  it("returns nothing it was not given", () => {
    expect(convergenceSources(s({}))).toEqual([]);
  });
});
