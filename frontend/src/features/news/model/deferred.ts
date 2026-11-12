/**
 * Why a News & Learning control is visible but does nothing yet (review 028a). Each keeps its place and its text, and
 * says why:
 * - Confirm outcome / Reject / Not enough evidence, "Audit this miss" and "Add an early signal" write through Validation
 *   and arrive with the News writes (028b);
 * - "Refresh news" and the source evaluation's "Re-measure now" run the feed refresh, which arrives with 028c;
 * - the Swiss deal ticker's technical health was read from System health (decision e), which is not ported yet.
 * The old "Prepare backcast research (Scout Bridge, paid)" button is removed: the rewrite has no Scout Bridge.
 */
export const NOT_PORTED = {
  writes: "Recording News decisions arrives with the News writes port (028b)",
  refresh: "Refreshing News arrives with the News refresh port (028c)",
  health: "System health arrives with its port",
} as const;
