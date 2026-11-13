/** The scan's texts (review 034a): the old finish and stopped toasts, the progress label, and the declared refusal. */
import { describe, expect, it } from "vitest";

import { findStatus } from "../test/fixtures";
import { finishToast, mergedOf, refusedText, scanIcon, scanningLabel, SCAN_FINISHED_INVALIDATES, stoppedToast } from "./scan";

describe("the scan's texts", () => {
  it("the finish toast is the old one, plus the intake's refusals when there are any", () => {
    const r = findStatus("done").result!;
    expect(finishToast(r)).toBe("2 genuinely new (1 pre-company) · 4 baseline · 1 noise · 9 already known · 1 existing pipeline · 1 refused by the intake");
    expect(finishToast({ ...r, refused: 0 })).toBe("2 genuinely new (1 pre-company) · 4 baseline · 1 noise · 9 already known · 1 existing pipeline");
    expect(finishToast({ new: 0, pre_company_new: 0, baseline: 0, noise: 0 })).toBe(
      "0 genuinely new (0 pre-company) · 0 baseline · 0 noise · 0 already known · 0 existing pipeline",
    );
  });

  it("the stopped toast keeps the old wording and plain words for the error", () => {
    expect(stoppedToast("RuntimeError: the source registry could not be read")).toBe(
      "Scan stopped: the source registry could not be read — nothing was half-saved; start it again when ready",
    );
  });

  it("the progress label, the row icons, the merged count and the refusal text", () => {
    expect(scanningLabel({ done: 2, total: 7 })).toBe("Scanning 2 / 7…");
    expect(scanningLabel(undefined)).toBe("Scanning 0 / 0…");
    expect([scanIcon("ok"), scanIcon("off"), scanIcon("failed")]).toEqual(["✓", "·", "✕"]);
    expect(mergedOf({ merged_cross_source: 1, merged_into_existing: 2 })).toBe(3);
    expect(mergedOf({})).toBe(0);
    expect([refusedText(2), refusedText(0), refusedText(null), refusedText(undefined)]).toEqual(["2 refused by the intake", "", "", ""]);
  });

  it("a finished scan refreshes the inbox, the sources, the history, the post-scan triage status, System health and the catch-up", () => {
    expect([...SCAN_FINISHED_INVALIDATES]).toEqual(["deal-flow/inbox", "sources", "deal-flow/scan_history", "deal-flow/triage_auto", "system_health", "catchup"]);
    // the triage view itself is read again when the post-scan run finishes, not when the scan does (the old order)
    expect(SCAN_FINISHED_INVALIDATES).not.toContain("deal-flow/triage");
  });
});
