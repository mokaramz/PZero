/** The Map's fixed messages (the old wording), shared by the page and its tests. */
export const TEXT = {
  /** `?event=<id>` for an event without a pin */
  noCoordinates: "That event has no coordinates on the map",
  /** neither the local search nor `map/search` found anything */
  noMatch: "No match on the map",
  /** `map/intel` failed */
  intelUnavailable: "Ecosystem intelligence unavailable — the Explore layers still work.",
  /** the base-map style did not load in time / failed */
  tilesTimeout: "Base-map tiles unreachable — showing pins on a plain canvas (data unaffected)",
  tilesError: "Base map failed to load — plain canvas fallback",
  /** MapLibre itself could not load */
  mapFail: "Map library could not load — internet needed for base tiles. Your data is unaffected.",
} as const;
