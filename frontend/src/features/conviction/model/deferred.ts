/**
 * Why a Conviction entry point is visible but does nothing yet (review 011, "Not in 011"). Each one keeps its place in
 * the layout and is disabled with this one-line reason until its backend is ported — several of them would fetch pages
 * or spend money, so they stay off until their own review.
 */
export const NOT_PORTED = {
  casePrep: "Case preparation arrives with the case-preparation port",
  committee: "The Investment Committee and Reviewer arrive with the case-preparation port",
  outreach: "Recording founder contact arrives with the case-preparation port",
  manager: "The Manager handoff arrives with the Manager / IMQ port",
  imqTrigger: "Recording a dated why-now trigger arrives with the Manager / IMQ port",
  verification: "Verification proposals and the research loop arrive with the verification port",
  bridge: "External research jobs arrive with the bridge port",
  evaluator: "The Active Evaluator arrives with the evaluator port",
  founders: "Founders and registries arrive with the identity port",
  traction: "The traction review arrives with the founder-calls port",
} as const;
