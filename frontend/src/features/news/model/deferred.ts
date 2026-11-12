/**
 * Why a News & Learning control is visible but does nothing yet (reviews 028a, 028b). Each keeps its place and its text,
 * and says why:
 * - "Refresh news" and the source evaluation's "Re-measure now" run the feed refresh, which arrives with 028c;
 * - the Swiss deal ticker's technical health was read from System health (decision e), which is not ported yet.
 * The outcome decisions, the miss audit and the early signal are enabled since 028b (./writes). The old "Prepare backcast
 * research (Scout Bridge, paid)" button is removed: the rewrite has no Scout Bridge.
 */
export const NOT_PORTED = {
  refresh: "Refreshing News arrives with the News refresh port (028c)",
  health: "System health arrives with its port",
} as const;
