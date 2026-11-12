/**
 * Map (v1 view `map`, review 025): where opportunity forms, where to go, who is there, and where Project Zero is blind.
 * Two parts: the pins (`GET map/pins`, filtered in the browser by layer, time, distance, stage, type, score, theme and
 * status) and the ecosystem intelligence (`GET map/intel`, the "Why here?" panel `GET map/ecosystem`, `GET map/search`
 * and the never-stored `POST map/sourcing_day`; see ./api). Side reads: Events (types, `wsig?days=14`), Network people
 * and the Conviction pipeline.
 * Query params, read once: `?mode=opportunity|go|gaps|explore` and `?event=<id>` (opens that event once the map is ready).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Async, PageHeader, Segmented } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { usePipeline } from "@/features/conviction/api";
import { useEvents, useWsig } from "@/features/events/api";
import { usePeople } from "@/features/network/api";
import { cx } from "@/lib/format";
import { searchMap, useIntel, usePins } from "./api";
import { EcosystemPanel } from "./components/EcosystemPanel";
import { ExploreControls } from "./components/ExploreControls";
import { GeoControls } from "./components/GeoControls";
import { MapCanvas, type MapApi } from "./components/MapCanvas";
import { MapPanel } from "./components/MapPanel";
import { ExploreCards, GeoCards } from "./components/StripCards";
import { applyFilters, DEFAULT_FILTERS } from "./model/filter";
import type { Filters, MapData, Mode, Selection } from "./model/types";
import { TEXT } from "./model/text";
import { localHit, MODES, parseMode, pinAt } from "./model/view";
import styles from "./Map.module.css";

export default function MapPage() {
  const q = usePins();
  return (
    <>
      <PageHeader title="Map" subtitle="Where is opportunity forming, where should you go, who is there — and where is Project Zero blind?" />
      <Async q={q} label="Loading map data…">
        {(d) => <MapWorkspace d={d} />}
      </Async>
    </>
  );
}

function MapWorkspace({ d }: { d: MapData }) {
  const toast = useToast();
  const [params] = useSearchParams();
  const [f, setF] = useState<Filters>(DEFAULT_FILTERS);
  const [sel, setSel] = useState<Selection | null>(null);
  const api = useRef<MapApi | null>(null);
  const [ready, setReady] = useState(false);
  const [mode, setMode] = useState<Mode>(() => parseMode(params.get("mode")));

  const evTypes = useEvents();
  const wsig = useWsig("14");
  const people = usePeople();
  const pipeline = usePipeline();
  const geo = useIntel();

  const visible = useMemo(() => applyFilters(d, f), [d, f]);
  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setF((x) => ({ ...x, [k]: v }));

  const show = (s: Selection, at?: { lat: number; lng: number }) => {
    if (at) api.current?.flyTo(at.lng, at.lat, 9);
    setSel(s);
  };
  const openCity = (city: string) => {
    const e = geo.data?.ecosystems.find((x) => x.city === city);
    if (e) api.current?.flyTo(e.lng, e.lat, 8);
    setSel({ kind: "eco", id: city });
  };

  // Deep link from an event card: /map?event=<id>
  const deepEvent = params.get("event");
  useEffect(() => {
    if (!ready || !deepEvent) return;
    const e = d.events.find((x) => x.id === deepEvent);
    if (e) show({ kind: "event", id: e.id }, e);
    else toast.show(TEXT.noCoordinates, "info");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, deepEvent]);

  const search = () => {
    if (!f.q) return;
    const hit = localHit(d, f.q);
    if (hit) {
      show(hit.sel, hit.at);
      return;
    }
    // Deal Flow, Scout 00, events and institutions → the ecosystem they belong to
    searchMap(f.q)
      .then((r) => (r.results[0] ? openCity(r.results[0].city) : toast.show(TEXT.noMatch, "info")))
      .catch(() => toast.show(TEXT.noMatch, "info"));
  };

  const best = wsig.data?.ranked?.[0];
  const due = (people.data?.people ?? []).find((p) => p.due);

  return (
    <div className={styles.stage}>
      <MapCanvas
        data={d}
        visible={visible}
        eco={mode === "explore" ? null : (geo.data?.ecosystems ?? null)}
        ecoColor={mode === "gaps" ? "coverage" : "state"}
        onSelect={setSel}
        onReady={(a) => {
          api.current = a;
          setReady(true);
        }}
      />

      <div className={cx(styles.float, styles.controls)} data-testid="map-controls" data-receded={sel ? "" : undefined}>
        <Segmented value={mode} onChange={setMode} options={MODES} label="Map mode" />
        <input
          aria-label="Search the map"
          placeholder="Search city, company, person, event…"
          value={f.q}
          onChange={(e) => set("q", e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
        />
        {mode !== "explore" && <GeoControls mode={mode} geo={geo.data} loading={geo.isLoading} onCity={openCity} />}
        {mode === "explore" && <ExploreControls d={d} f={f} set={set} visible={visible} types={evTypes.data?.types ?? {}} onShow={show} />}
      </div>

      {sel?.kind === "eco" && (
        <div className={cx(styles.float, styles.panelWrap)}>
          <EcosystemPanel city={sel.id} onClose={() => setSel(null)} />
        </div>
      )}
      {sel && sel.kind !== "eco" && (
        <div className={cx(styles.float, styles.panelWrap)}>
          <MapPanel
            d={d}
            sel={sel}
            pipelineNext={(slug) => pipeline.data?.signals?.find((x) => x.slug === slug)?.next_action}
            onSelect={(s) => show(s, pinAt(d, s))}
            onClose={() => setSel(null)}
          />
        </div>
      )}

      {mode !== "explore" && <GeoCards geo={geo.data} shifted={!!sel} onCity={openCity} />}
      {mode === "explore" && <ExploreCards best={best} newSignals={d.new_signals} due={due} shifted={!!sel} />}
    </div>
  );
}
