import { useEffect, useRef, useState } from "react";
import type { Feature, FeatureCollection, Point } from "geojson";
import type { GeoJSONSource, Map as MLMap, MapGeoJSONFeature } from "maplibre-gl";

import { useToast } from "@/components/Toast";
import { GEO_COLOR, LAYER_COLOR, STAGE_COLOR, VIS_COLOR } from "../model/colors";
import type { Visible } from "../model/filter";
import type { GeoEco, MapData, Selection } from "../model/types";
import { ecoRadius } from "../model/view";
import { TEXT } from "../model/text";
import { loadMapLibre } from "./loadMapLibre";
import { PLAIN, POSITRON, TILE_TIMEOUT_MS } from "./mapStyle";
import styles from "../Map.module.css";

export type MapApi = {
  flyTo: (lng: number, lat: number, zoom?: number) => void;
};

type Props = {
  data: MapData;
  visible: Visible;
  onSelect: (s: Selection) => void;
  onReady: (api: MapApi) => void;
  /** ecosystem intelligence circles (activity / visibility — never investment scores); null hides them */
  eco?: GeoEco[] | null;
  ecoColor?: "state" | "coverage";
};

const fc = (features: Feature[]): FeatureCollection => ({ type: "FeatureCollection", features });
const pt = (lng: number, lat: number, properties: Record<string, unknown>): Feature => ({
  type: "Feature",
  geometry: { type: "Point", coordinates: [lng, lat] },
  properties,
});

function square(r: number, g: number, b: number, n: number) {
  const a = new Uint8Array(n * n * 4);
  for (let i = 0; i < n * n; i++) {
    a[i * 4] = r;
    a[i * 4 + 1] = g;
    a[i * 4 + 2] = b;
    a[i * 4 + 3] = 255;
  }
  return { width: n, height: n, data: a };
}

const HAS = ["has", "point_count"] as never;
const NOT = ["!", ["has", "point_count"]] as never;
const clusterCount = (size: number) => ({
  layout: { "text-field": "{point_count}", "text-font": ["Noto Sans Regular"], "text-size": size },
  paint: { "text-color": "#fff" },
});

/** Adds the sources, layers and click handlers once the style has loaded. */
function addLayers(mm: MLMap, data: MapData, ml: Awaited<ReturnType<typeof loadMapLibre>>, select: (s: Selection) => void) {
  new ml.Marker({ color: "#1B1F26", scale: 0.8 }).setLngLat([data.home.lng, data.home.lat]).addTo(mm);
  const first = (e: { features?: MapGeoJSONFeature[] }) => e.features?.[0]?.properties ?? {};
  // ecosystem circles first, so company / event / people pins stay on top
  mm.addSource("eco", { type: "geojson", data: fc([]) });
  mm.addLayer({
    id: "eco-c",
    type: "circle",
    source: "eco",
    paint: {
      "circle-color": ["get", "color"],
      "circle-opacity": ["case", ["get", "blind"], 0.12, 0.28],
      "circle-radius": ["get", "r"],
      "circle-stroke-color": ["get", "color"],
      "circle-stroke-width": ["case", ["get", "blind"], 1.5, 2],
    },
  });
  mm.addLayer({
    id: "eco-l",
    type: "symbol",
    source: "eco",
    minzoom: 4.2,
    layout: { "text-field": "{city}", "text-font": ["Noto Sans Regular"], "text-size": 11, "text-offset": [0, 1.6], "text-optional": true },
    paint: { "text-color": "#1B1F26", "text-halo-color": "#fff", "text-halo-width": 1.2 },
  });
  mm.on("click", "eco-c", (e) => select({ kind: "eco", id: String(first(e).city) }));
  mm.addSource("startups", { type: "geojson", data: fc([]), cluster: true, clusterRadius: 42 });
  mm.addSource("events", { type: "geojson", data: fc([]), cluster: true, clusterRadius: 42 });
  mm.addSource("ppl", { type: "geojson", data: fc([]), cluster: true, clusterRadius: 38 });
  mm.addSource("orgs", { type: "geojson", data: fc([]) });
  mm.addImage("ev-square", square(199, 125, 46, 16));
  mm.addImage("org-uni", square(61, 107, 107, 14));
  mm.addImage("org-hub", square(138, 109, 59, 14));
  mm.addLayer({
    id: "st-cl",
    type: "circle",
    source: "startups",
    filter: HAS,
    paint: { "circle-color": LAYER_COLOR.startup, "circle-opacity": 0.85, "circle-radius": ["step", ["get", "point_count"], 14, 5, 18, 15, 24] },
  });
  mm.addLayer({ id: "st-cl-n", type: "symbol", source: "startups", filter: HAS, ...clusterCount(11) });
  mm.addLayer({
    id: "st-pt",
    type: "circle",
    source: "startups",
    filter: NOT,
    paint: {
      "circle-color": ["get", "color"],
      "circle-radius": ["+", 6, ["/", ["get", "score"], 25]],
      "circle-stroke-width": ["case", ["get", "omar"], 2.5, 1],
      "circle-stroke-color": ["case", ["get", "omar"], "#2E7D32", "#fff"],
    },
  });
  mm.addLayer({
    id: "ev-cl",
    type: "circle",
    source: "events",
    filter: HAS,
    paint: { "circle-color": LAYER_COLOR.event, "circle-opacity": 0.85, "circle-radius": ["step", ["get", "point_count"], 13, 5, 17, 15, 22] },
  });
  mm.addLayer({ id: "ev-cl-n", type: "symbol", source: "events", filter: HAS, ...clusterCount(11) });
  mm.addLayer({
    id: "ev-pt",
    type: "symbol",
    source: "events",
    filter: NOT,
    layout: { "icon-image": "ev-square", "icon-size": ["+", 0.55, ["/", ["get", "score"], 200]], "icon-allow-overlap": true },
  });
  mm.addLayer({
    id: "ppl-cl",
    type: "circle",
    source: "ppl",
    filter: HAS,
    paint: { "circle-color": LAYER_COLOR.person, "circle-opacity": 0.85, "circle-radius": ["step", ["get", "point_count"], 12, 5, 16, 15, 20] },
  });
  mm.addLayer({ id: "ppl-cl-n", type: "symbol", source: "ppl", filter: HAS, ...clusterCount(10.5) });
  mm.addLayer({
    id: "ppl-pt",
    type: "circle",
    source: "ppl",
    filter: NOT,
    paint: {
      "circle-color": LAYER_COLOR.person,
      "circle-radius": 5.5,
      "circle-stroke-width": ["case", ["get", "watch"], 2.5, 1],
      "circle-stroke-color": ["case", ["get", "watch"], "#7A5A48", "#fff"],
    },
  });
  mm.addLayer({
    id: "org-pt",
    type: "symbol",
    source: "orgs",
    layout: { "icon-image": ["case", ["==", ["get", "kind"], "hub"], "org-hub", "org-uni"], "icon-size": 0.8, "icon-allow-overlap": true },
  });

  mm.on("click", "st-pt", (e) => select({ kind: "startup", id: String(first(e).slug) }));
  mm.on("click", "ev-pt", (e) => select({ kind: "event", id: String(first(e).id) }));
  mm.on("click", "ppl-pt", (e) => select({ kind: "person", id: String(first(e).id) }));
  mm.on("click", "org-pt", (e) => select({ kind: "org", id: String(first(e).name) }));
  for (const [layer, src] of [
    ["st-cl", "startups"],
    ["ev-cl", "events"],
    ["ppl-cl", "ppl"],
  ] as const) {
    mm.on("click", layer, async (e) => {
      const f = mm.queryRenderedFeatures(e.point, { layers: [layer] })[0];
      if (!f) return;
      const z = await (mm.getSource(src) as GeoJSONSource).getClusterExpansionZoom(f.properties.cluster_id as number);
      mm.easeTo({ center: (f.geometry as Point).coordinates as [number, number], zoom: z + 0.5 });
    });
  }
  for (const l of ["eco-c", "st-pt", "ev-pt", "ppl-pt", "org-pt", "st-cl", "ev-cl", "ppl-cl"]) {
    mm.on("mouseenter", l, () => (mm.getCanvas().style.cursor = "pointer"));
    mm.on("mouseleave", l, () => (mm.getCanvas().style.cursor = ""));
  }
}

/**
 * MapLibre canvas, with clustering. `maplibre-gl` (and its CSS) load dynamically (see ./loadMapLibre). Falls back to a
 * plain canvas when the OpenFreeMap style is unreachable (data unaffected), as in v1.
 */
export function MapCanvas({ data, visible, onSelect, onReady, eco = null, ecoColor = "state" }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const toast = useToast();
  const cb = useRef({ onSelect, onReady, toast });
  useEffect(() => {
    cb.current = { onSelect, onReady, toast };
  });

  useEffect(() => {
    let cancelled = false;
    let m: MLMap | null = null;
    let timer: number | undefined;
    (async () => {
      let ml: Awaited<ReturnType<typeof loadMapLibre>>;
      try {
        ml = await loadMapLibre();
      } catch {
        if (!cancelled) setFailed(true);
        return;
      }
      if (cancelled || !el.current) return;
      let loaded = false;
      let fellBack = false;
      const mm = new ml.Map({
        container: el.current,
        style: POSITRON,
        center: [data.home.lng, data.home.lat],
        zoom: 5.2,
        attributionControl: { compact: true },
      });
      m = mm;
      map.current = mm;
      const fallback = (why: string) => {
        if (loaded || fellBack) return;
        fellBack = true;
        mm.setStyle(PLAIN);
        cb.current.toast.show(why, "info");
      };
      timer = window.setTimeout(() => fallback(TEXT.tilesTimeout), TILE_TIMEOUT_MS);
      // A listener on "error" also keeps MapLibre from logging tile hiccups to the console.
      mm.on("error", () => fallback(TEXT.tilesError));
      mm.addControl(new ml.NavigationControl({ showCompass: false }), "top-right");
      mm.on("load", () => {
        loaded = true;
        window.clearTimeout(timer);
        addLayers(mm, data, ml, (s) => cb.current.onSelect(s));
        setReady(true);
        cb.current.onReady({ flyTo: (lng, lat, zoom = 9) => mm.flyTo({ center: [lng, lat], zoom }) });
      });
    })();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      m?.remove();
      map.current = null;
    };
    // The map is created once per mount; data.home is stable for the page's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Push the filtered data into the GeoJSON sources whenever filters change.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !m.getSource("startups")) return;
    const set = (id: string, features: Feature[]) => (m.getSource(id) as GeoJSONSource).setData(fc(features));
    set(
      "startups",
      visible.startups.map((s) => pt(s.lng, s.lat, { slug: s.slug, score: s.score, color: STAGE_COLOR[s.stage] ?? "#9AA3AF", omar: !!s.sent_to_omar })),
    );
    set(
      "events",
      visible.events.map((e) => pt(e.lng, e.lat, { id: e.id, score: e.score })),
    );
    set(
      "ppl",
      visible.people.map((p) => pt(p.lng, p.lat, { id: p.id, watch: !!p.watch })),
    );
    set(
      "orgs",
      visible.orgs.map((o) => pt(o.lng, o.lat, { name: o.name, kind: o.kind })),
    );
  }, [ready, visible]);

  // Ecosystem intelligence circles: size grows with EARLY signals and events (capped), never with raw volume.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !m.getSource("eco")) return;
    (m.getSource("eco") as GeoJSONSource).setData(
      fc(
        (eco ?? []).map((e) =>
          pt(e.lng, e.lat, {
            city: e.city,
            color: ecoColor === "coverage" ? (VIS_COLOR[e.coverage.visibility] ?? "#9AA3AF") : GEO_COLOR[e.state],
            blind: e.state === "UNDER-COVERED" || e.coverage.visibility === "POOR",
            r: ecoRadius(e),
          }),
        ),
      ),
    );
  }, [ready, eco, ecoColor]);

  return (
    <div className={styles.canvasWrap}>
      <div ref={el} className={styles.canvas} data-testid="map-canvas" data-ready={ready || undefined} />
      {failed && <div className={styles.mapFail}>{TEXT.mapFail}</div>}
    </div>
  );
}
