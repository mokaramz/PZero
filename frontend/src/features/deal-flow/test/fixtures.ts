/** A small Deal Flow: enough candidates to exercise the top-15 cut, every workspace and every decision. */
import type { TriagePayload, TriageSummary } from "../model/triage";
import type { Candidate, InboxPayload } from "../model/types";

const DAY = 864e5;
const iso = (daysAgo: number) => new Date(Date.now() - daysAgo * DAY).toISOString().slice(0, 10);

const STATUS: Record<Candidate["decision"], string> = { new: "new", research: "reviewing", watch: "watch", kept: "kept", rejected: "rejected", baseline: "baseline" };

export function cand(id: string, extra: Partial<Candidate> = {}): Candidate {
  const decision = extra.decision ?? "new";
  return {
    id,
    name: `Company ${id}`,
    decision,
    pz_status: STATUS[decision],
    source: "src-a",
    location: "Berlin, Germany",
    description: `What ${id} does.`,
    run_id: "r1",
    ...extra,
  };
}

/** 17 undecided European candidates with different signals (more than the queue's 15), plus the special cases. */
export function inbox(): InboxPayload {
  const eu = Array.from({ length: 17 }, (_, i) =>
    cand(`e${i + 1}`, {
      source_date: iso(i % 4 === 0 ? 3 : i % 4 === 1 ? 20 : 200),
      archetype_hits: i % 3 === 0 ? [1, 2] : [],
      discovery_tier: i % 5 === 0 ? "pre_company" : "announcement",
      priority: i % 2,
      source: i % 2 ? "src-a" : "src-b",
      themes: i % 4 === 0 ? ["climate"] : [],
    }),
  );
  return {
    candidates: [
      ...eu,
      cand("gated", { attention_v2: { gated: "noise", score: 1 }, source_date: iso(1) }),
      cand("ns", { source_date: iso(1), archetype_hits: [1, 2], also_seen: [{ source: "x" }, { source: "y" }] }),
      cand("tri1", { name: "Grant to Real Name GmbH", source_date: iso(2), archetype_hits: [1], analysis_state: "ANALYZED" }),
      cand("r1", { decision: "research" }),
      cand("w1", { decision: "watch" }),
      cand("k1", { decision: "kept" }),
      cand("x1", { decision: "rejected" }),
      cand("b1", { decision: "baseline" }),
      cand("us1", { location: "Austin, TX" }),
      cand("ca1", { location: "Toronto" }),
      cand("u1", { location: undefined, geo_scope: "global" }),
    ],
    last_run: "r1",
    last_summary: { new: 3, run_id: "r1" },
    report: [],
    themes: { climate: "Climate" },
    feedback_cap: 3,
    feedback_min_reviewed: 5,
    ws_geos: { eu: ["DACH"], na: ["US", "CA"], un: [] },
  };
}

export function proposal(id: string, extra: Partial<TriageSummary> = {}): TriageSummary {
  return {
    candidate_id: id,
    proposal: "KEEP",
    display_proposal: "KEEP",
    status: "ok",
    stage: "stage1",
    confidence: "high",
    reasons: ["Strong founder signal"],
    missing: [],
    flags: [],
    flash: { proposal: "KEEP" },
    veto: null,
    edge: "PRE_FUNDING_EDGE",
    themes: [],
    routing: { queue: "operating", reason: "European startup" },
    entity: { display_name: "Real Name GmbH", broken: "grant title", entities: [{ name: "Real Name GmbH", evidence: "awarded to Real Name GmbH", method: "regex" }] },
    portfolio: { status: "NONE", route_to_omar: false, evidence: [], twins: [], record: null },
    stale: false,
    obvious_reject: false,
    mohamed: null,
    queue: { state: "NEEDS_MOHAMED", reason: "high-value", priority: 9, priority_why: ["keep"] },
    ...extra,
  };
}

export function triage(): TriagePayload {
  return {
    architecture: { prompt_version: "v3" },
    proposals: {
      tri1: proposal("tri1"),
      ns: proposal("ns", { proposal: "REJECT", display_proposal: "REJECT", routing: { queue: "non_startup", reason: "university" }, queue: null, entity: { display_name: "Company ns", broken: "", entities: [] } }),
    },
    counts: {},
    calibration: { decisions: 0, agreement: null, machine_rejects_reviewed: 0, machine_rejects_overturned_to_keep_or_research: 0 },
    note: "Proposals only.",
  };
}
