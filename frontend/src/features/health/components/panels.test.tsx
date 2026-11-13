/** The 032b panels with data (as the hardening port will feed them): every action control stays deferred with its
 *  visible reason — "Safe repair" on each repairable integrity issue, and the source decisions in the old order. */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NOT_PORTED } from "../model/deferred";
import { Hardening, type HardeningData } from "./Hardening";
import { NewSources, type Cand, type Net } from "./NewSources";

function expectDeferred(btn: HTMLElement, reason: string) {
  expect(btn).toHaveAttribute("aria-disabled", "true");
  expect(btn).toHaveAttribute("data-deferred");
  const note = document.getElementById(btn.getAttribute("aria-describedby") ?? "");
  expect(note?.textContent).toBe(reason);
  expect(note).not.toHaveClass("sr-only");
  expect(btn).toHaveAccessibleDescription(reason);
}

const hardening: HardeningData = {
  backups: {
    dir: "backups/",
    backups: [
      { archive: "a", name: "pz-2026-11-12.zip", bytes: 4_194_304, has_checksum: true, restore_test: null },
      { archive: "b", name: "pz-2026-11-01.zip", bytes: 2_097_152, has_checksum: false, restore_test: { ok: true, tested_at: "2026-11-02T10:00:00", problems: [] } },
    ],
  },
  integrity: {
    status: "warn",
    files_checked: 227,
    issues: [
      { level: "warn", kind: "stuck_job", what: "a job record is stuck in running", safe_repair: "clear_stuck" },
      { level: "info", kind: "impossible_date", what: "one founder call is dated 1970", safe_repair: "" },
    ],
  },
  governance: {
    calls: 12,
    by_purpose: [{ purpose: "machine_triage", calls: 12, usd: 0.0123, models: { "inventa/brisk-flash-1": 12 }, prompt_versions: 2, last: "2026-11-09T21:47:00" }],
    roles: {},
    field_completeness: {},
    experiments: [],
    note: "Invented note.",
  },
};

const cand = (id: string, state: string, x: Partial<Cand> = {}): Cand => ({
  id,
  url: `https://${id}.example`,
  name: `Source ${id}`,
  family: "news_feed",
  state,
  why_interesting: "",
  discovered_via: [{ kind: "news_backcast", ref: "r", company: "Tessaro Grid" }],
  validation: null,
  performance: null,
  eligibility: null,
  early_examples: [],
  ...x,
});
const net: Net = {
  candidates: [cand("p", "PROBATION", { eligibility: { eligible: true, requirements: [{ ok: true, text: "8 weeks" }] } }), cand("d", "DISCOVERED"), cand("r", "REJECTED"), cand("t", "TRUSTED"), cand("v", "VALIDATING")],
  counts: { PROBATION: 1, DISCOVERED: 1 },
  monitored_evidence: [],
  alpha_sources: [],
  coverage_gaps: [],
  note: "",
};

describe("Hardening with data", () => {
  it("draws the backups, integrity issues and provenance; every control is deferred, Safe repair only on a repairable issue", () => {
    const onClick = vi.fn();
    document.addEventListener("click", onClick);
    render(<Hardening data={hardening} />);
    expect(screen.getByTestId("health-backups")).toHaveTextContent("pz-2026-11-12.zip · 4.0 MB checksum not restore-tested yet");
    expect(screen.getByTestId("health-backups")).toHaveTextContent("restore tested 2026-11-02");
    expect(screen.getByTestId("health-integrity")).toHaveTextContent("WARN 227 files checked");
    expect(screen.getByTestId("health-governance")).toHaveTextContent("machine triage12$0.012");
    const repairs = screen.getAllByRole("button", { name: "Safe repair" });
    expect(repairs).toHaveLength(1);
    for (const b of [screen.getByTestId("backup-now"), screen.getByTestId("backup-test"), ...repairs]) expectDeferred(b, NOT_PORTED.hardening);
    fireEvent.click(repairs[0]);
    fireEvent.keyDown(repairs[0], { key: "Enter" });
    expect(onClick).not.toHaveBeenCalled(); // stopped at the control: no handler runs
    document.removeEventListener("click", onClick);
  });
});

describe("New sources with data", () => {
  it("the decisions keep their state-dependent labels and order, each deferred with the row's reason", () => {
    render(<NewSources net={net} />);
    const rows = screen.getAllByTestId("new-source");
    const labels = (i: number) => within(rows[i]).queryAllByRole("button").map((b) => b.textContent);
    expect(labels(0)).toEqual(["Promote to trusted", "Keep in probation", "Reject"]);
    expect(labels(1)).toEqual(["Validate now", "Reject"]);
    expect(labels(2)).toEqual(["Validate again"]);
    expect(labels(3)).toEqual(["Reject"]);
    expect(labels(4)).toEqual([]);
    for (const b of rows.flatMap((r) => within(r).queryAllByRole("button"))) expectDeferred(b, NOT_PORTED.sourceNetwork);
    expectDeferred(screen.getByTestId("source-network-run"), NOT_PORTED.sourceNetwork);
    expect(screen.getByTestId("new-sources-counts")).toHaveTextContent("probation 1 · discovered 1");
    expect(rows[0]).toHaveTextContent("Found through: News backcast (Tessaro Grid) · type: news feed");
    expect(rows[0]).toHaveTextContent("eligible for TRUSTED");
  });
});
