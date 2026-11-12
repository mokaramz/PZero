import { cx } from "@/lib/format";
import { LAYER_COLOR } from "../model/colors";
import type { Visible } from "../model/filter";
import type { Filters, MapData, Selection } from "../model/types";
import { resultRows, visibleTotal } from "../model/view";
import styles from "../Map.module.css";

type SetFilter = <K extends keyof Filters>(k: K, v: Filters[K]) => void;

function Layer({ label, checked, onChange, color, square, n }: { label: string; checked: boolean; onChange: (v: boolean) => void; color: string; square?: boolean; n: number }) {
  return (
    <label className={styles.layer}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /> {label}
      <span className={cx(styles.dot, square && styles.sq)} style={{ background: color }} />
      <span className={styles.num}>({n})</span>
    </label>
  );
}

/** Explore mode: the layers, the filters and the visible results. */
export function ExploreControls({
  d,
  f,
  set,
  visible,
  types,
  onShow,
}: {
  d: MapData;
  f: Filters;
  set: SetFilter;
  visible: Visible;
  types: Record<string, string>;
  onShow: (s: Selection, at: { lat: number; lng: number }) => void;
}) {
  const results = resultRows(visible);
  return (
    <>
      <div className={styles.hd}>Layers</div>
      <Layer label="Startups" checked={f.lyStart} onChange={(v) => set("lyStart", v)} color={LAYER_COLOR.startup} n={visible.counts.start} />
      <Layer label="Events" checked={f.lyEv} onChange={(v) => set("lyEv", v)} color={LAYER_COLOR.event} square n={visible.counts.ev} />
      <Layer label="People" checked={f.lyPpl} onChange={(v) => set("lyPpl", v)} color={LAYER_COLOR.person} n={visible.counts.ppl} />
      <Layer label="Universities & labs" checked={f.lyOrg} onChange={(v) => set("lyOrg", v)} color={LAYER_COLOR.uni} square n={visible.counts.org} />
      <Layer label="Hubs & accelerators" checked={f.lyHub} onChange={(v) => set("lyHub", v)} color={LAYER_COLOR.hub} square n={visible.counts.hub} />
      <div className={styles.fRow}>
        <select aria-label="Time" value={f.time} onChange={(e) => set("time", e.target.value)}>
          <option value="all">All upcoming</option>
          <option value="7">This week</option>
          <option value="weekend">This weekend</option>
          <option value="30">30 days</option>
          <option value="past">Incl. past</option>
        </select>
        <select aria-label="Distance from home base" value={f.dist} onChange={(e) => set("dist", Number(e.target.value))}>
          <option value={0}>Everywhere</option>
          <option value={100}>≤100 km</option>
          <option value={250}>≤250 km</option>
          <option value={500}>≤500 km</option>
        </select>
        <select aria-label="Stage" value={f.stage} onChange={(e) => set("stage", e.target.value)}>
          <option value="">All stages</option>
          <option value="pre_company">Pre-company</option>
          <option value="grant_angel">Grant/angel</option>
          <option value="pre_seed">Pre-seed</option>
          <option value="seed">Seed</option>
          <option value="series_a_plus">Series A+</option>
        </select>
        <select aria-label="Event type" value={f.evType} onChange={(e) => set("evType", e.target.value)}>
          <option value="">All event types</option>
          {Object.entries(types).map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
        <input
          type="number"
          min={0}
          max={100}
          aria-label="Min startup score"
          title="Min startup score"
          value={f.minS}
          onChange={(e) => set("minS", Number(e.target.value) || 0)}
        />
        <input
          type="number"
          min={0}
          max={100}
          aria-label="Min event score"
          title="Min event score"
          value={f.minE}
          onChange={(e) => set("minE", Number(e.target.value) || 0)}
        />
      </div>
      <div className={styles.fRow}>
        <select aria-label="Project A theme" value={f.theme} onChange={(e) => set("theme", e.target.value)}>
          <option value="">All Project A themes</option>
          <option value="defence">Defence Technologies</option>
          <option value="industrial_autonomy">Industrial Autonomy</option>
          <option value="regulated">Regulated Industries</option>
          <option value="frontier">Frontier Technologies</option>
          <option value="physical_world">Physical World Intelligence</option>
        </select>
        <select aria-label="Status" value={f.status} onChange={(e) => set("status", e.target.value)}>
          <option value="">All statuses</option>
          <option value="verified">Verified</option>
          <option value="provisional">Provisional</option>
          <option value="omar">Sent to Manager</option>
          <option value="gated">Conflict-gated</option>
        </select>
      </div>
      {d.no_geo.length > 0 && <div className={styles.noGeo}>No coordinates (edit location): {d.no_geo.join(", ")}</div>}
      <div className={styles.hd}>
        Visible results <span className={styles.num}>({visibleTotal(visible)})</span>
      </div>
      <div className={styles.results} data-testid="map-results">
        {results.length ? (
          results.map((r) => (
            <button key={r.key} type="button" className={styles.res} onClick={() => onShow(r.sel, r.at)}>
              <span className={cx(styles.dot, r.sq && styles.sq)} style={{ background: r.color }} />
              <b>{r.name}</b>
              <span className="muted small grow">{r.sub}</span>
              <span className={styles.num}>{r.num}</span>
            </button>
          ))
        ) : (
          <div className="muted small">Nothing visible with these filters.</div>
        )}
      </div>
    </>
  );
}
