import { describe, expect, it } from "vitest";

import { emptyValidation, validation } from "../test/fixtures";
import { NOT_PORTED } from "./deferred";
import { STAGES } from "./types";
import {
  benchmarkLine,
  bridgeMetrics,
  collecting,
  DIMS,
  dimLabel,
  horizonLine,
  label,
  latestCycle,
  leadDays,
  measureNeeds,
  measurementHint,
  missType,
  newestFirst,
  newsTail,
  pct,
  QUESTIONS,
  scoutLine,
  sourceLead,
  stateTone,
  strengthLine,
  topAlpha,
  trendNote,
  trendRows,
  usd,
  verificationLine,
  whoWasRight,
} from "./view";

describe("Validation model — formatting", () => {
  it("pct rounds to whole percent and shows — for a missing rate", () => {
    expect(pct(0.571)).toBe("57%");
    expect(pct(0)).toBe("0%");
    expect(pct(null)).toBe("—");
    expect(pct(undefined)).toBe("—");
  });

  it("label, collecting, lead days and money", () => {
    expect(label("pre_company")).toBe("pre company");
    expect(label("DID_NOT_HOLD_UP")).toBe("DID NOT HOLD UP");
    expect(collecting(3, 5)).toBe("collecting (3/5)");
    expect(leadDays(61)).toBe("61 d");
    expect(leadDays(null)).toBe("—");
    expect(sourceLead(58.5, 2)).toBe("58.5 d (n=2)");
    expect(sourceLead(null, 0)).toBe("—");
    expect(usd(1.5)).toBe("$1.50");
    expect(usd(null)).toBe("—");
  });

  it("keeps the old question tabs, groupings and stage columns, in order", () => {
    expect(QUESTIONS.map((q) => q.label)).toEqual(["Are we early?", "Are we right?", "Which sources work?", "Where do we miss?", "What does it cost?"]);
    expect(QUESTIONS.map((q) => q.id)).toEqual(["early", "right", "sources", "miss", "cost"]);
    expect(DIMS.map((x) => x.label)).toEqual(["Discovery type", "Pre-Funding", "Capital stage", "Theme", "Country", "Scout lane"]);
    expect(dimLabel("ecosystem")).toBe("Country");
    expect(STAGES).toEqual(["discovered", "machine_keep_research", "mohamed_accepted", "conviction", "verified", "radar", "imq", "omar"]);
    // every grouping the server sends is one of the page's groupings, in the same order
    expect(Object.keys(validation().conversion)).toEqual(DIMS.map((x) => x.value));
  });

  it("state tones and miss types fall back gracefully", () => {
    expect(["KNOWN", "PARTLY KNOWN", "COLLECTING", "NOT YET MEASURABLE", "ODD"].map(stateTone)).toEqual(["green", "blue", "amber", "neutral", "neutral"]);
    expect(missType("found_early_but_rejected")).toBe("seen early, rejected");
    expect(missType("watch_not_followed")).toBe("on WATCH, then strong");
    expect(missType("brand_new")).toBe("brand_new");
  });
});

describe("Validation model — what can we measure", () => {
  it("counts the states in first-seen order", () => {
    expect(measurementHint(validation().measurement)).toBe("4 collecting · 1 known · 1 partly known");
    expect(measurementHint(emptyValidation().measurement)).toBe("5 not yet measurable · 1 partly known");
    expect(measurementHint([])).toBe("");
  });

  it("states the count so far, except for PARTLY KNOWN", () => {
    const [recall, , , , alpha] = validation().measurement;
    expect(measureNeeds(recall)).toBe("3 so far · needs: real-world outcomes (rounds, customers) and miss audits — months, not days");
    expect(measureNeeds(alpha)).toMatch(/^needs: volume, uniqueness/);
  });
});

describe("Validation model — trends (grounded sparklines)", () => {
  it("draws only the series with 3+ numeric snapshots; a gap stays a gap", () => {
    const rows = trendRows(validation().snapshots);
    expect(rows.map(([l]) => l)).toEqual(["first seen this month", "median lead days", "Conviction size"]);
    expect(rows[0][1]).toEqual([9, 10, 12, 13, 14]);
    expect(rows[1][1]).toEqual([null, 58, 60, null, 61]);
    // pre-funding share has only two numbers: no line
    expect(rows.some(([l]) => l === "pre-funding share")).toBe(false);
  });

  it("draws nothing below 3 snapshots, and says it is direction only", () => {
    expect(trendRows(emptyValidation().snapshots)).toEqual([]);
    expect(trendRows([])).toEqual([]);
    expect(trendRows([{ found_this_month: "9" }, { found_this_month: 1 }, { found_this_month: 2 }])).toEqual([]);
    expect(trendNote(5)).toBe("Direction over 5 daily snapshots — not a significance claim.");
  });
});

describe("Validation model — lines", () => {
  it("outcome evidence: strongest first, ties in the server's order; horizon in the server's order", () => {
    const d = validation();
    expect(strengthLine(d.strength)).toBe("unknown 31 · external signal 4 · promising human 3 · negative 2 · strong verified 1 · strong human 1");
    expect(horizonLine(d.horizon)).toBe("immediate 14 · 30-90 days 18 · 3-6 months 9 · unknown 1");
    expect(strengthLine({})).toBe("");
  });

  it("calibration and verification lines, and their empty states", () => {
    const d = validation();
    const e = emptyValidation();
    expect(whoWasRight(d.calibration)).toBe("pending 1 · mohamed 1");
    expect(whoWasRight(e.calibration)).toBe("no disagreements with a known outcome yet");
    expect(verificationLine(d.verification_calibration)).toBe("founder_unverified: 2 accepted · 1 rejected");
    expect(verificationLine({ a: { accepted: 1, rejected: 0 }, b: { accepted: 0, rejected: 2 } })).toBe("a: 1 accepted · 0 rejected — b: 0 accepted · 2 rejected");
    expect(verificationLine(e.verification_calibration)).toBe("none yet (founder / funding proposals appear in Conviction → Verification)");
  });

  it("the outcome ledger is newest first, without touching the payload", () => {
    const d = validation();
    expect(newestFirst(d.outcomes).map((o) => o.company)).toEqual(["Lumenfold AI", "Aurelith Systems"]);
    expect(d.outcomes[0].company).toBe("Aurelith Systems");
  });

  it("the Scout 00 line and the latest cycle", () => {
    const d = validation();
    expect(scoutLine(d.scout)).toBe("5 Scout intake item(s) across cycle(s) c-2026-10-02, c-2026-10-16: PENDING 3 · PROGRESSING 1 · DID NOT HOLD UP 1.");
    expect(scoutLine(emptyValidation().scout)).toBe("0 Scout intake item(s) across cycle(s) —: none yet.");
    expect(latestCycle(d.scout.cycles)).toBe("c-2026-10-16");
    expect(latestCycle([])).toBe("");
  });

  it("benchmark lines: singular / plural and the median rule", () => {
    const [dealroom, news] = validation().benchmarks.systems;
    expect(benchmarkLine(dealroom)).toBe("1 company · PZ earlier for 1, same day or later for 0 · median shown from 5 companies");
    expect(benchmarkLine(news)).toBe("5 companies · PZ earlier for 4, same day or later for 1 · median 47 days");
  });

  it("the News tail (only used once News is available)", () => {
    expect(newsTail({ available: true, median_lead_days: 21, preventable_misses: 2, most_common_miss_cause: "source_not_covered" })).toBe(
      " · median lead 21 days · 2 preventable · most common miss cause: source not covered",
    );
    expect(newsTail({ available: true, median_lead_days: null, preventable_misses: 0, most_common_miss_cause: null })).toBe("");
  });

  it("the native bridge panel is deferred for the rewrite's answer and the old null", () => {
    expect(bridgeMetrics(validation().native_bridge)).toBeNull();
    expect(bridgeMetrics(null)).toBeNull();
    expect(bridgeMetrics(undefined)).toBeNull();
    const m = { label: "pilot", status: { state: "ACTIVE", day_usd: 0, month_usd: 0, daily_cap: 1, monthly_cap: 1, x_hunts_this_week: 0, x_hunts_per_week: 1 }, spend_usd: 0, convergence: 0, funnel: {}, cost_per: {}, alpha: { lane: [], geography: [], query: [], web_vs_x: [], source: [] }, note: "" };
    expect(bridgeMetrics(m)).toBe(m);
  });

  it("the native bridge alpha keeps the top three", () => {
    const r = (key: string) => ({ key, found: 4, investigate: 1, contact_yes: 0 });
    expect(topAlpha([r("a"), r("b"), r("c"), r("d")])).toBe("a 1/4 · b 1/4 · c 1/4");
    expect(topAlpha([])).toBe("—");
  });
});

describe("Validation model — deferred reasons", () => {
  it("are the agreed texts", () => {
    expect(NOT_PORTED.writes).toBe("Recording outcomes, audits and imports arrives with the Validation writes port (027b)");
    expect(NOT_PORTED.news).toBe("News & Learning arrives with its port");
    expect(NOT_PORTED.bridge).toMatch(/Scout search bridge/);
    // the server's News reason is the same text
    expect(validation().news).toEqual({ available: false, reason: NOT_PORTED.news });
  });
});
