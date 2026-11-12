import type { StyleSpecification } from "maplibre-gl";

/** OpenFreeMap's style and fonts are the page's only external requests (review 025, decision h). */
export const POSITRON = "https://tiles.openfreemap.org/styles/positron";

/** The plain canvas the pins move to when the base map is unreachable. */
export const PLAIN: StyleSpecification = {
  version: 8,
  name: "offline",
  glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#E9E7E1" } }],
};

/** Without base tiles by then, the pins move to the plain canvas. */
export const TILE_TIMEOUT_MS = 9000;
