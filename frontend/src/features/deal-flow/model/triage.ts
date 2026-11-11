/**
 * Machine triage inside Deal Flow (protected; old `triage.ts`). Proposals only — Mohamed decides.
 * `GET /api/deal-flow/triage` serves the old `/api/triage` payload from the imported records.
 */
import type { Tone } from "@/components/ui";

import type { Candidate } from "./types";

export type Verdict = "KEEP" | "RESEARCH" | "WATCH" | "REJECT";
export type DisplayProposal = Verdict | "KNOWN_PORTFOLIO" | "ASK_OMAR_CONFLICT";
export type Queue = "operating" | "global_only" | "non_startup";
export type Edge = "PRE_FUNDING_EDGE" | "ROUND_FORMING" | "FIRST_INSTITUTIONAL" | "ALREADY_FUNDED" | "UNKNOWN";
export type RouteState =
  | "NEEDS_MOHAMED"
  | "CASE_PREPARING"
  | "BACKGROUND_RESEARCH"
  | "MACHINE_WATCH"
  | "DEFERRED_LOW_PRIORITY"
  | "CONFLICT_GATED"
  | "CALIBRATION_SAMPLE";
export type RouteFilter = RouteState | "ANY";

type PortfolioCheck = {
  status: "KNOWN_PORTFOLIO" | "PROJECT_A_RELATIONSHIP" | "RESEMBLES_PORTFOLIO" | "EXISTING_RECORD" | "NONE";
  route_to_omar: boolean;
  evidence: string[];
  twins: Array<{ name: string; what: string; keyword_hits: number }>;
  record: { where: string; name: string; conflict?: string | null } | null;
};

/** Triage Queue Compressor routing — attention order only, never a decision. */
type QueueRoute = {
  state: RouteState;
  reason: string;
  priority: number;
  priority_why: string[];
  underlying?: RouteState | null;
  resurfaced?: { at: string; from: string; why: string } | null;
};

export type TriageSummary = {
  candidate_id: string;
  proposal: Verdict;
  display_proposal: DisplayProposal;
  status: string;
  stage: "stage0" | "stage1" | "veto";
  path?: string;
  confidence?: string;
  reject_basis?: string | null;
  reject_evidence?: string | null;
  reasons: string[];
  missing: string[];
  flags: string[];
  flash: { model?: string | null; proposal?: string; confidence?: string; reject_basis?: string | null };
  veto: { model?: string; mode?: string; ok?: boolean; proposal?: string; reject_basis?: string | null; reasons: string[] } | null;
  capital_stage?: string;
  edge: Edge;
  themes: string[];
  sector?: string;
  entity_type?: string;
  routing: { queue: Queue; reason: string };
  entity: { display_name: string; broken: string; entities: Array<{ name: string; evidence: string; method: string }> };
  portfolio: PortfolioCheck;
  stale: boolean;
  obvious_reject: boolean;
  prompt_version?: string;
  mohamed: { verdict: Verdict; mode: string; at: string; agreed: boolean } | null;
  queue?: QueueRoute | null;
};

export type TriagePayload = {
  architecture: { prompt_version: string; accepted?: string; holdout?: Record<string, unknown> };
  proposals: Record<string, TriageSummary>;
  counts: Partial<Record<Queue, Partial<Record<DisplayProposal | "OBVIOUS_REJECT", number>>>>;
  calibration: { decisions: number; agreement: number | null; machine_rejects_reviewed: number; machine_rejects_overturned_to_keep_or_research: number };
  pending?: Record<string, string>;
  note: string;
};

export const ROUTE_LABEL: Record<RouteState, string> = {
  NEEDS_MOHAMED: "Needs you",
  CALIBRATION_SAMPLE: "Calibration sample",
  CASE_PREPARING: "Queued for case preparation",
  BACKGROUND_RESEARCH: "Machine research queue",
  MACHINE_WATCH: "Machine watch",
  DEFERRED_LOW_PRIORITY: "Deferred",
  CONFLICT_GATED: "Conflict — Manager",
};
export const ROUTE_ORDER: RouteState[] = [
  "NEEDS_MOHAMED",
  "CALIBRATION_SAMPLE",
  "CASE_PREPARING",
  "BACKGROUND_RESEARCH",
  "MACHINE_WATCH",
  "DEFERRED_LOW_PRIORITY",
  "CONFLICT_GATED",
];

export const PROPOSAL_LABEL: Record<DisplayProposal, string> = {
  KEEP: "KEEP",
  RESEARCH: "RESEARCH",
  WATCH: "WATCH",
  REJECT: "REJECT",
  KNOWN_PORTFOLIO: "PROJECT A PORTFOLIO",
  ASK_OMAR_CONFLICT: "ASK OMAR",
};

export const EDGE_LABEL: Record<Edge, string> = {
  PRE_FUNDING_EDGE: "Pre-Funding Edge",
  ROUND_FORMING: "round forming",
  FIRST_INSTITUTIONAL: "first institutional round",
  ALREADY_FUNDED: "already institutionally funded",
  UNKNOWN: "stage unknown",
};

export function proposalTone(p: DisplayProposal): Tone {
  if (p === "KEEP") return "green";
  if (p === "RESEARCH") return "blue";
  if (p === "WATCH") return "amber";
  if (p === "REJECT") return "neutral";
  return "purple";
}

/** Kept out of the Attention queue: the router says this is not a startup. */
export const isNonStartup = (tri: Record<string, TriageSummary>) => (c: Candidate) => tri[c.id]?.routing.queue === "non_startup";

const PROPOSAL_ORDER: Record<DisplayProposal, number> = { ASK_OMAR_CONFLICT: 0, KNOWN_PORTFOLIO: 0, KEEP: 1, RESEARCH: 2, WATCH: 3, REJECT: 4 };
const EDGE_ORDER: Record<Edge, number> = { PRE_FUNDING_EDGE: 0, ROUND_FORMING: 1, FIRST_INSTITUTIONAL: 2, UNKNOWN: 3, ALREADY_FUNDED: 4 };
const CONFIDENCE_ORDER: Record<string, number> = { high: 0, medium: 1, low: 2 };

export type TriageScope = Queue | "all";
export type TriageKind = DisplayProposal | "ALL";

/** The machine-triage queue: undecided candidates with a proposal, highest-value review first. */
export function triageList(all: Candidate[], tri: Record<string, TriageSummary>, scope: TriageScope, kind: TriageKind, route: RouteFilter = "ANY"): Candidate[] {
  return all
    .filter((c) => {
      const t = tri[c.id];
      if (!t || c.decision !== "new") return false;
      if (route !== "ANY") return t.queue?.state === route; // a routing view spans every queue scope
      if (scope !== "all" && t.routing.queue !== scope) return false;
      return kind === "ALL" || t.display_proposal === kind;
    })
    .sort((a, b) => {
      const x = tri[a.id];
      const y = tri[b.id];
      if (route !== "ANY") return (y.queue?.priority ?? 0) - (x.queue?.priority ?? 0); // the compressor's attention order
      return (
        PROPOSAL_ORDER[x.display_proposal] - PROPOSAL_ORDER[y.display_proposal] ||
        EDGE_ORDER[x.edge] - EDGE_ORDER[y.edge] ||
        (CONFIDENCE_ORDER[x.confidence || ""] ?? 3) - (CONFIDENCE_ORDER[y.confidence || ""] ?? 3) ||
        (b.attention_v2?.final ?? 0) - (a.attention_v2?.final ?? 0)
      );
    });
}

export function triageCounts(all: Candidate[], tri: Record<string, TriageSummary>, scope: TriageScope): Partial<Record<TriageKind, number>> {
  const out: Partial<Record<TriageKind, number>> = {};
  for (const c of all) {
    const t = tri[c.id];
    if (!t || c.decision !== "new" || (scope !== "all" && t.routing.queue !== scope)) continue;
    out[t.display_proposal] = (out[t.display_proposal] || 0) + 1;
    out.ALL = (out.ALL || 0) + 1;
  }
  return out;
}

/** How many undecided proposals the compressor put in each routing state. */
export function routeCounts(all: Candidate[], tri: Record<string, TriageSummary>): Partial<Record<RouteState, number>> {
  const out: Partial<Record<RouteState, number>> = {};
  for (const c of all) {
    const state = c.decision === "new" ? tri[c.id]?.queue?.state : undefined;
    if (state) out[state] = (out[state] || 0) + 1;
  }
  return out;
}
