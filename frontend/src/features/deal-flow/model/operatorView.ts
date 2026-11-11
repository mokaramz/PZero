/**
 * LEVEL 1 for a Deal Flow candidate (old `CandidateDetail` `operatorView`): built only from what triage / routing
 * already recorded — no new judgement. Wording verbatim.
 */
import type { Move } from "@/components/focus";

import { ROUTE_LABEL, type TriageSummary } from "./triage";
import type { Candidate } from "./types";

/** The detail's own short edge names (the triage panel uses the longer `EDGE_LABEL`). */
const EDGE_SHORT: Record<string, string> = {
  PRE_FUNDING_EDGE: "Pre-funding",
  ROUND_FORMING: "Round forming",
  FIRST_INSTITUTIONAL: "First institutional round",
  ALREADY_FUNDED: "Already funded",
};

export type OperatorView = { why: string[]; risks: string[]; unknowns: string[]; pz: string; move: Move | null; edge?: string };

/** `toDecision` brings the decision row into view (every move here leads to it). */
export function operatorView(c: Candidate, tri: TriageSummary | undefined, toDecision: () => void): OperatorView {
  const why = tri?.reasons?.length ? tri.reasons : c.why || [];
  const risks: string[] = [];
  if (tri?.portfolio?.route_to_omar) risks.push(`Project A portfolio question (${tri.portfolio.status.toLowerCase().replace(/_/g, " ")}) — Manager decides`);
  if (tri?.edge === "ALREADY_FUNDED") risks.push("Already institutionally funded — may be late for Project A");
  if (tri?.reject_evidence) risks.push(tri.reject_evidence);
  risks.push(...(tri?.flags || []));
  const unknowns = tri?.missing || [];
  const route = tri?.queue?.state;
  const decided = c.decision !== "new";
  const pz = decided ? `Decided: ${c.decision}` : route ? ROUTE_LABEL[route] : tri ? `Machine proposes ${tri.display_proposal.replace(/_/g, " ")}` : "Not triaged yet";
  let move: Move | null;
  if (decided) move = null;
  else if (route === "CONFLICT_GATED" || tri?.portfolio?.route_to_omar) move = { label: "See the decision", onClick: toDecision, why: "Ask Manager first — then accept or override" };
  else if (!route || route === "NEEDS_MOHAMED" || route === "CALIBRATION_SAMPLE") move = { label: "Decide", onClick: toDecision, why: "Keep, research, watch or drop" };
  else move = { label: "Decide anyway", onClick: toDecision, why: "Nothing needed — the machine is on it" };
  return { why, risks, unknowns, pz, move, edge: tri?.edge && EDGE_SHORT[tri.edge] };
}
