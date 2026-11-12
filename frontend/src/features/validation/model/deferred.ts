/**
 * Why a Validation control or panel is visible but does nothing yet (review 027a). Each keeps its place and its text:
 * - the writes (record outcome, record a miss / false positive, retract, benchmark preview / import, "Copy & log
 *   handover", which marks the Scout 00 packet as sent) arrive with review 027b — no request ever reaches them;
 * - the News benchmark panel and the packet's News / source-network learnings arrive with News & Learning (decisions b, c);
 * - the native search bridge pilot depends on the Scout search bridge, which is never ported (decision d).
 */
export const NOT_PORTED = {
  writes: "Recording outcomes, audits and imports arrives with the Validation writes port (027b)",
  news: "News & Learning arrives with its port",
  bridge: "The native search bridge pilot depends on the Scout search bridge, which is not part of the rewrite",
} as const;
