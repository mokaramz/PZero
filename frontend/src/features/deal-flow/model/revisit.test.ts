import { describe, expect, it } from "vitest";

import { cand, inbox, triage } from "../test/fixtures";
import type { NaFilter, Workspace } from "./geo";
import { buildList, FILTERS, type ListFilter } from "./list";
import { isoDay, REVISIT_KIND, revisitCount, revisitLabel, revisitList } from "./revisit";
import type { Candidate, InboxPayload, Revisit } from "./types";
import { candidateView, linkFilter, type ViewControls } from "./view";

const flag = (p: Partial<Revisit> = {}): Revisit => ({
  kind: "funding_round",
  since: "2026-11-03",
  date_source: "since",
  rejected_on: "2026-10-01",
  evidence_url: "https://example.org/round",
  evidence: [{ url: "https://example.org/round" }],
  note: "Seed round announced",
  submission_id: "sub-1",
  flagged_at: "2026-11-10T08:15:00+00:00",
  ...p,
});

/** The fixture inbox plus a rejected North American candidate; `flags` sets `revisit` on the two rejected ones. */
function payload(flags: boolean): InboxPayload {
  const ib = inbox();
  ib.candidates.push(cand("x2", { decision: "rejected", location: "Austin, TX" }));
  if (flags) {
    ib.candidates.find((c) => c.id === "x1")!.revisit = flag();
    ib.candidates.find((c) => c.id === "x2")!.revisit = flag({ kind: "registry_event", flagged_at: "2026-11-11T09:00:00+00:00" });
    ib.revisit_count = 2;
  }
  return ib;
}

const ids = (xs: Candidate[]) => xs.map((c) => c.id);

describe("the Revisit list (review 018)", () => {
  it("lists exactly the flagged candidates, rejected included, across every workspace, newest flag first", () => {
    const ib = payload(true);
    expect(ids(revisitList(ib.candidates))).toEqual(["x2", "x1"]);
    expect(revisitList(payload(false).candidates)).toEqual([]);
    const v = candidateView(ib, triage().proposals, { ws: "eu", naf: "both", theme: "climate", im: false, filter: "revisit", tScope: "operating", tKind: "ALL", tRoute: "ANY" });
    expect(ids(v!.list)).toEqual(["x2", "x1"]); // the workspace and the theme do not narrow it: the count is the inbox's
    expect(v!.hidden).toBe(0);
    expect(v!.counts).toEqual(buildList(ib.candidates, { ws: "all", naf: "both", theme: "", im: false, filter: "new", lastRun: ib.last_run }).counts);
  });

  it("equal flag times keep the payload order", () => {
    const at = "2026-11-10T08:15:00+00:00";
    const cs = ["a", "b", "c"].map((id) => cand(id, { decision: "rejected", revisit: flag({ flagged_at: at }) }));
    expect(ids(revisitList(cs))).toEqual(["a", "b", "c"]);
  });

  it("the count is the server's revisit_count, else the flags in the payload", () => {
    expect(revisitCount(payload(true))).toBe(2);
    expect(revisitCount({ ...payload(true), revisit_count: undefined })).toBe(2);
    expect(revisitCount(payload(false))).toBe(0);
  });

  it("labels, dates and the ?filter=revisit link", () => {
    expect(Object.values(REVISIT_KIND)).toEqual(["New funding round", "Registry event", "New founder or key hire", "Independent corroboration"]);
    expect(revisitLabel("founder_or_key_hire")).toBe("New founder or key hire");
    expect(revisitLabel("something_new")).toBe("something_new");
    expect(isoDay("2026-11-10T08:15:00+00:00")).toBe("2026-11-10");
    expect(isoDay(null)).toBe("");
    expect(linkFilter("revisit")).toBe("revisit");
    expect(linkFilter("review")).toBeNull();
  });
});

describe("the protected list is unchanged by the flags", () => {
  const WS: Workspace[] = ["eu", "na", "unk", "all"];
  const NAF: NaFilter[] = ["both", "us", "ca"];
  const LIST_FILTERS = FILTERS.map((f) => f.value).filter((f): f is ListFilter => f !== "review" && f !== "triage");
  const skip = (c: Candidate) => c.id === "ns";

  it("buildList answers byte-identically with and without revisit flags, for every view", () => {
    const off = payload(false);
    const on = payload(true);
    let compared = 0;
    for (const ws of WS)
      for (const naf of NAF)
        for (const filter of LIST_FILTERS)
          for (const im of [false, true])
            for (const theme of ["", "climate"]) {
              const opts = { ws, naf, theme, im, filter, lastRun: off.last_run, skip };
              const a = buildList(off.candidates, opts);
              const b = buildList(on.candidates, opts);
              expect(ids(b.list)).toEqual(ids(a.list));
              expect(b.hidden).toBe(a.hidden);
              expect(b.counts).toEqual(a.counts);
              compared++;
            }
    expect(compared).toBe(WS.length * NAF.length * LIST_FILTERS.length * 4);
  });

  it("every page view other than Revisit is the same with and without flags", () => {
    const tri = triage().proposals;
    for (const filter of ["top", "triage", "pre", "thisrun", "new", "research", "watch", "kept", "rejected", "baseline"] as const)
      for (const ws of WS) {
        const v: ViewControls = { ws, naf: "both", theme: "", im: false, filter, tScope: "operating", tKind: "ALL", tRoute: "ANY" };
        const a = candidateView(payload(false), tri, v)!;
        const b = candidateView(payload(true), tri, v)!;
        expect([ids(b.list), b.hidden, b.counts]).toEqual([ids(a.list), a.hidden, a.counts]);
      }
  });
});
