/**
 * Why a Network / Watchlist entry point is visible but does nothing yet (review 013, "Not in 013"). Each one keeps its
 * place in the layout and says why, until its backend is ported in its own review.
 */
export const NOT_PORTED = {
  identity: "Identity review arrives with the identity port",
  watchCompanies: "Watched companies and their sensors arrive with the WATCH sensors port",
} as const;
