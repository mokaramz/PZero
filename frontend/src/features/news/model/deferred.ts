/**
 * Why a News & Learning control is visible but does nothing yet (reviews 028a-028c). It keeps its place and its text, and
 * says why: the Swiss deal ticker's technical health was read from System health (decision e), which is not ported yet.
 * The decisions (028b) and the refresh and "Re-measure now" (028c) are enabled. The old "Prepare backcast research (Scout
 * Bridge, paid)" button is removed: the rewrite has no Scout Bridge.
 */
export const NOT_PORTED = {
  health: "System health arrives with its port",
} as const;
