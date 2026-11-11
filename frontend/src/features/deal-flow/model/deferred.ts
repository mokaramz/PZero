/**
 * Why an entry point is visible but does nothing yet (review 009, deviation a). Each one keeps its place in the layout
 * and is disabled with this one-line reason until its backend is ported.
 */
export const NOT_PORTED = {
  keep: "Keep moves to Conviction — available when Conviction is ported",
  analysis: "Machine analysis arrives with the analysis port",
  reviewQueue: "The Agent Review Queue arrives with the analysis port",
  redTeam: "The red team arrives with the analysis port",
  triage: "Accepting or overriding machine triage arrives with the triage port",
  scan: "Finding new candidates arrives with the scan port",
  scanReport: "The per-source scan report arrives with the scan port",
  scanHistory: "Scan history arrives with the scan port",
  watch: "Watch sensors arrive with the Watchlist port",
  founders: "Founders arrive with the identity port",
} as const;

export type NotPortedReason = (typeof NOT_PORTED)[keyof typeof NOT_PORTED];
