/**
 * Why a Founder Radar control is visible but does nothing yet (review 026a, decision h). Each keeps its place and its
 * text, and says why:
 * - the founder scan (`radar_scan`) and the company research crawl (`radar_research`, `radar_research_queue`) fetch from
 *   the network; they arrive with review 026b on the new outbound boundary — "Scan founder signals", "Research company",
 *   "Refresh research", "Research next 5 leads" and "Research company queue…";
 * - "Ask Scout 00 for identity evidence" created a Scout Bridge job; the Scout Bridge is never ported.
 */
import { NOT_PORTED as CONVICTION } from "@/features/conviction/model/deferred";

export const NOT_PORTED = {
  scan: "Founder scans and company research arrive with the founder scan port (026b)",
  bridge: CONVICTION.bridge,
} as const;
