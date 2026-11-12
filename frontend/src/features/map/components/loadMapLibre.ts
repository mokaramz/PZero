/**
 * Loads MapLibre (and its CSS) on demand, so they only load on the Map page. Vite bundles the worker (and its shared
 * chunk) and returns its URL — MapLibre's own import.meta.url-relative lookup breaks once the library is pre-bundled.
 * The page tests replace this module: jsdom has no WebGL.
 */
export type MapLibre = typeof import("maplibre-gl");

export async function loadMapLibre(): Promise<MapLibre> {
  const [mod, worker] = await Promise.all([
    import("maplibre-gl"),
    import("maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url"),
    import("maplibre-gl/dist/maplibre-gl.css"),
  ]);
  mod.setWorkerUrl(worker.default);
  return mod;
}
