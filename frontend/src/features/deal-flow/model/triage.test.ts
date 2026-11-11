import { describe, expect, it } from "vitest";

import { routeCounts, triageCounts, triageList, type TriageSummary } from "./triage";
import type { Candidate } from "./types";

const cand = (id: string, decision: Candidate["decision"] = "new"): Candidate => ({ id, name: id, source: "s", decision });
const t = (id: string, display: TriageSummary["display_proposal"], queue: TriageSummary["routing"]["queue"], edge: TriageSummary["edge"] = "UNKNOWN", confidence = "medium") =>
  ({
    candidate_id: id,
    proposal: display === "KNOWN_PORTFOLIO" || display === "ASK_OMAR_CONFLICT" ? "KEEP" : display,
    display_proposal: display,
    routing: { queue, reason: "" },
    edge,
    confidence,
  }) as TriageSummary;

describe("machine triage queue", () => {
  const all = [cand("rej"), cand("keep"), cand("omar"), cand("res"), cand("us"), cand("done", "rejected"), cand("keep-edge")];
  const tri: Record<string, TriageSummary> = {
    rej: t("rej", "REJECT", "operating"),
    keep: t("keep", "KEEP", "operating", "ALREADY_FUNDED"),
    "keep-edge": t("keep-edge", "KEEP", "operating", "PRE_FUNDING_EDGE"),
    omar: t("omar", "ASK_OMAR_CONFLICT", "operating"),
    res: t("res", "RESEARCH", "operating"),
    us: t("us", "KEEP", "global_only"),
    done: t("done", "REJECT", "operating"),
  };

  it("orders conflicts first, then KEEP (Pre-Funding Edge first), RESEARCH, REJECT; only undecided, scoped", () => {
    expect(triageList(all, tri, "operating", "ALL").map((c) => c.id)).toEqual(["omar", "keep-edge", "keep", "res", "rej"]);
    expect(triageList(all, tri, "global_only", "ALL").map((c) => c.id)).toEqual(["us"]);
    // unknown stage ranks above "already institutionally funded"
    expect(triageList(all, tri, "all", "KEEP").map((c) => c.id)).toEqual(["keep-edge", "us", "keep"]);
  });

  it("counts per proposal within the scope", () => {
    expect(triageCounts(all, tri, "operating")).toEqual({ ASK_OMAR_CONFLICT: 1, KEEP: 2, RESEARCH: 1, REJECT: 1, ALL: 5 });
  });
});

describe("triage queue compression — routing views", () => {
  const all = [cand("a"), cand("b"), cand("c"), cand("d", "kept")];
  const q = (state: NonNullable<TriageSummary["queue"]>["state"], priority: number) => ({ state, reason: "r", priority, priority_why: [] });
  const tri: Record<string, TriageSummary> = {
    a: { ...t("a", "RESEARCH", "operating"), queue: q("NEEDS_MOHAMED", 10) },
    b: { ...t("b", "KEEP", "global_only"), queue: q("NEEDS_MOHAMED", 40) },
    c: { ...t("c", "KEEP", "operating"), queue: q("DEFERRED_LOW_PRIORITY", 90) },
    d: { ...t("d", "KEEP", "operating"), queue: q("NEEDS_MOHAMED", 99) },
  };
  it("a routing view lists only that state, undecided, in the compressor's priority order", () => {
    expect(triageList(all, tri, "operating", "ALL", "NEEDS_MOHAMED").map((c) => c.id)).toEqual(["b", "a"]);
  });
  it("counts per routing state ignore decided companies; deferred ones stay listed and reachable", () => {
    expect(routeCounts(all, tri)).toEqual({ NEEDS_MOHAMED: 2, DEFERRED_LOW_PRIORITY: 1 });
    expect(triageList(all, tri, "operating", "ALL").map((c) => c.id)).toContain("c");
  });
});
