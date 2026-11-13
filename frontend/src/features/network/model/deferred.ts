/**
 * Why a Network / Watchlist entry point is visible but does nothing yet (review 013, "Not in 013"). Each one keeps its
 * place in the layout and says why, until its backend is ported in its own review. The watched companies panel is
 * live since review 037a; its "Check now" reason lives with it (`features/watchlist/model/watch.ts`).
 */
export const NOT_PORTED = {
  identity: "Identity review arrives with the identity port",
} as const;
