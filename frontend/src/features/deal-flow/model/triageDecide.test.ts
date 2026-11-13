import { describe, expect, it } from "vitest";

import { triageInbox, triageWorld } from "../test/fixtures";
import { batchToast, decidedToast, obviousRejectIds, patchTriaged, skippedLine, triageDecideBody } from "./triageDecide";

describe("machine triage writes — the pure parts (review 035a)", () => {
  it("the decide body carries the stored status the panel showed as expected_status", () => {
    expect(triageDecideBody({ id: "t-1", pz_status: "new" }, "REJECT", "accept")).toEqual({ id: "t-1", verdict: "REJECT", mode: "accept", expected_status: "new" });
    expect(triageDecideBody({ id: "t-1" }, "WATCH", "override")).toEqual({ id: "t-1", verdict: "WATCH", mode: "override" });
  });

  it("the old toasts", () => {
    expect(decidedToast("REJECT", "accept")).toBe("Accepted REJECT");
    expect(decidedToast("WATCH", "override")).toBe("Overrode to WATCH");
    expect(batchToast({ ok: true, applied: 3, skipped: {} })).toBe("Rejected 3");
    expect(batchToast({ ok: true, applied: 1, skipped: { "already decided": 2, "no proposal": 1 } })).toBe("Rejected 1 · skipped 3");
    expect(skippedLine({ "already decided": 2, "no proposal": 0 })).toBe("2 already decided");
    expect(skippedLine({})).toBe("");
  });

  it("the batch ids: undecided obvious REJECTs in the scope, in inbox order", () => {
    const ib = triageInbox();
    const tri = triageWorld().proposals;
    expect(obviousRejectIds(ib.candidates, tri, "operating")).toEqual(["t-0204", "t-0205"]);
    expect(obviousRejectIds(ib.candidates, tri, "global_only")).toEqual(["t-0207"]);
    expect(obviousRejectIds(ib.candidates, tri, "all")).toEqual(["t-0204", "t-0205", "t-0207"]);
    expect(obviousRejectIds(ib.candidates, tri, "non_startup")).toEqual([]);
  });

  it("the cache patch sets the view decision and the stored status of exactly those rows", () => {
    const ib = triageInbox();
    const out = patchTriaged(ib, ["t-0202"], "research");
    expect(out.candidates.find((c) => c.id === "t-0202")).toMatchObject({ decision: "research", pz_status: "reviewing" });
    expect(out.candidates.filter((c, i) => c !== ib.candidates[i]).map((c) => c.id)).toEqual(["t-0202"]);
    expect(ib.candidates.find((c) => c.id === "t-0202")).toMatchObject({ decision: "new" });
  });
});
