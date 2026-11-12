/** A stand-in for `maplibre-gl` in jsdom (no WebGL): it records what the page asks of the map — sources and their
 *  data, layers, handlers, camera moves, the style — and lets a test fire map events. The page tests mock
 *  `../components/loadMapLibre` to resolve to `fakeMapLibre`. */
import type { MapLibre } from "../components/loadMapLibre";

type Handler = (e: Record<string, unknown>) => unknown;
type Fc = { type: "FeatureCollection"; features: Array<{ geometry: { coordinates: [number, number] }; properties: Record<string, unknown> }> };

export class FakeSource {
  data: Fc | null = null;
  readonly spec: Record<string, unknown>;
  constructor(spec: Record<string, unknown>) {
    this.spec = spec;
    this.data = (spec.data as Fc) ?? null;
  }
  setData(d: Fc) {
    this.data = d;
    return this;
  }
  getClusterExpansionZoom() {
    return Promise.resolve(7);
  }
  /** the `properties` of every feature */
  props() {
    return (this.data?.features ?? []).map((f) => f.properties);
  }
}

export class FakeMap {
  static instances: FakeMap[] = [];
  /** fire "load" right after construction (the base style arrived) */
  static autoLoad = true;
  /** what `queryRenderedFeatures` answers (a cluster under the pointer) */
  static rendered: unknown[] = [];

  static reset() {
    FakeMap.instances = [];
    FakeMap.autoLoad = true;
    FakeMap.rendered = [];
  }

  static get last(): FakeMap {
    const m = FakeMap.instances.at(-1);
    if (!m) throw new Error("no map was created");
    return m;
  }

  readonly options: Record<string, unknown>;
  style: unknown;
  loaded = false;
  removed = false;
  readonly handlers = new Map<string, Handler[]>();
  readonly sources = new Map<string, FakeSource>();
  readonly layers: string[] = [];
  readonly flights: Array<{ center: [number, number]; zoom: number }> = [];
  readonly eases: Array<{ center: [number, number]; zoom: number }> = [];
  readonly canvas = { style: { cursor: "" } };

  constructor(options: Record<string, unknown>) {
    this.options = options;
    this.style = options.style;
    FakeMap.instances.push(this);
    if (FakeMap.autoLoad) setTimeout(() => this.fire("load"), 0);
  }

  on(type: string, a: string | Handler, b?: Handler) {
    const key = typeof a === "string" ? `${type}:${a}` : type;
    const fn = (typeof a === "string" ? b : a) as Handler;
    this.handlers.set(key, [...(this.handlers.get(key) ?? []), fn]);
    return this;
  }

  /** Fire a map event (`layer` for a layer event such as a click on "eco-c"). */
  async fire(type: string, layer?: string, e: Record<string, unknown> = {}) {
    if (type === "load") {
      if (this.loaded) return;
      this.loaded = true;
    }
    for (const h of this.handlers.get(layer ? `${type}:${layer}` : type) ?? []) await h(e);
  }

  /** A click on a pin: the feature's properties, as MapLibre hands them over. */
  click(layer: string, properties: Record<string, unknown>) {
    return this.fire("click", layer, { features: [{ properties }], point: { x: 1, y: 1 } });
  }

  setStyle(style: unknown) {
    this.style = style;
    if (!this.loaded) setTimeout(() => this.fire("load"), 0); // the plain style needs no network
    return this;
  }

  addControl() {
    return this;
  }
  addSource(id: string, spec: Record<string, unknown>) {
    this.sources.set(id, new FakeSource(spec));
    return this;
  }
  getSource(id: string) {
    return this.sources.get(id);
  }
  addLayer(layer: { id: string }) {
    this.layers.push(layer.id);
    return this;
  }
  addImage() {
    return this;
  }
  flyTo(o: { center: [number, number]; zoom: number }) {
    this.flights.push(o);
    return this;
  }
  easeTo(o: { center: [number, number]; zoom: number }) {
    this.eases.push(o);
    return this;
  }
  getCanvas() {
    return this.canvas;
  }
  queryRenderedFeatures() {
    return FakeMap.rendered;
  }
  remove() {
    this.removed = true;
  }

  /** the properties of every feature in a source */
  props(source: string) {
    return this.sources.get(source)?.props() ?? [];
  }
}

class FakeMarker {
  setLngLat() {
    return this;
  }
  addTo() {
    return this;
  }
}

class FakeNavigationControl {}

export const fakeMapLibre = {
  Map: FakeMap,
  Marker: FakeMarker,
  NavigationControl: FakeNavigationControl,
  setWorkerUrl: () => undefined,
} as unknown as MapLibre;
