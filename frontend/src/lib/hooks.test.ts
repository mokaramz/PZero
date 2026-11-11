import { describe, expect, it } from "vitest";

import { describeOutcome } from "./hooks";

describe("describeOutcome (useAction feedback)", () => {
  it("a plain success is COMPLETE with the standard wording", () => {
    expect(describeOutcome({ ok: true }, "Saving your decision")).toEqual({ state: "COMPLETE", message: "✓ Saving your decision — done" });
    expect(describeOutcome(undefined, "Working").message).toBe("✓ Working — done");
  });
  it("a background start points at Background activity", () => {
    expect(describeOutcome({ started: true }, "Scanning sources")).toEqual({
      state: "COMPLETE",
      message: "Scanning sources — started; it runs in the background (see Background activity)",
    });
  });
  it("started:false is PARTIAL with the server reason (or the fallback)", () => {
    expect(describeOutcome({ started: false, reason: "Already scanning." }, "Scanning sources")).toEqual({ state: "PARTIAL", message: "Already scanning." });
    expect(describeOutcome({ started: false }, "Scanning sources")).toEqual({ state: "PARTIAL", message: "Scanning sources: already running" });
  });
  it("a custom success message wins, also for a partial outcome", () => {
    expect(describeOutcome({ n: 3 }, "x", (r: { n: number }) => `${r.n} saved`)).toEqual({ state: "COMPLETE", message: "3 saved" });
    expect(describeOutcome({ started: false }, "x", "Queued")).toEqual({ state: "PARTIAL", message: "Queued" });
    expect(describeOutcome({ ok: true }, "Saving", () => undefined).message).toBe("✓ Saving — done");
  });
});
