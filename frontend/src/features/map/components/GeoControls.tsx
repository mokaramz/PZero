import { GEO_COLOR, VIS_COLOR } from "../model/colors";
import { SNAPSHOT_NOTE } from "../model/deferred";
import { TEXT } from "../model/text";
import type { GeoIntel, Mode } from "../model/types";
import { activeEcosystems, coverageGaps, gapText, unplacedText } from "../model/view";
import styles from "../Map.module.css";

function Opportunity({ geo, onCity }: { geo: GeoIntel; onCity: (c: string) => void }) {
  const active = activeEcosystems(geo);
  return (
    <>
      <div className={styles.legend}>
        {Object.entries(geo.legend).map(([k, v]) => (
          <span key={k} title={v}>
            <span className={styles.dot} style={{ background: GEO_COLOR[k] }} /> {k.toLowerCase()} ({geo.counts[k] ?? 0})
          </span>
        ))}
      </div>
      <div className={styles.results} data-testid="geo-list">
        {active.slice(0, 14).map((e) => (
          <button key={e.city} type="button" className={styles.res} onClick={() => onCity(e.city)}>
            <span className={styles.dot} style={{ background: GEO_COLOR[e.state] }} />
            <b>{e.city}</b>
            <span className="muted small grow">{e.reasons[0] ?? e.state.toLowerCase()}</span>
          </button>
        ))}
        {!active.length && <div className="muted small">No area has current Project Zero signals yet.</div>}
      </div>
    </>
  );
}

function WhereToGo({ geo, onCity }: { geo: GeoIntel; onCity: (c: string) => void }) {
  const { ranked, note } = geo.where_to_go;
  return (
    <div data-testid="where-to-go">
      <div className={styles.hd}>Where should I go?</div>
      {ranked.length ? (
        ranked.map((w, i) => (
          <button key={w.city} type="button" className={styles.goRow} onClick={() => onCity(w.city)}>
            <b>
              {i + 1}. {w.city}
            </b>{" "}
            <span className="muted small">
              {w.travel.bucket.toLowerCase()} · {w.travel.text}
            </span>
            <span className="small">Why: {w.why.join(" · ")}</span>
          </button>
        ))
      ) : (
        <div className="muted small">{note}</div>
      )}
      {ranked.length > 0 && <p className="muted small">{note} Open a city, then “Build a sourcing day”.</p>}
    </div>
  );
}

function CoverageGaps({ geo, onCity }: { geo: GeoIntel; onCity: (c: string) => void }) {
  return (
    <div data-testid="coverage-gaps">
      <div className={styles.hd}>Where is Project Zero blind?</div>
      <div className={styles.legend}>
        {Object.entries(VIS_COLOR).map(([k, c]) => (
          <span key={k}>
            <span className={styles.dot} style={{ background: c }} /> visibility {k.toLowerCase()}
          </span>
        ))}
      </div>
      <div className={styles.results}>
        {coverageGaps(geo).map((e) => (
          <button key={e.city} type="button" className={styles.res} onClick={() => onCity(e.city)}>
            <span className={styles.dot} style={{ background: VIS_COLOR[e.coverage.visibility] }} />
            <b>{e.city}</b>
            <span className="muted small grow">{gapText(e)}</span>
          </button>
        ))}
      </div>
      {Object.keys(geo.unplaced).length > 0 && (
        <p className="muted small">Not placed (no city in their own location — never guessed): {unplacedText(geo.unplaced)}</p>
      )}
    </div>
  );
}

/** Opportunity / Where to go / Coverage gaps — ecosystem intelligence (activity and visibility, never investment scores). */
export function GeoControls({ mode, geo, loading, onCity }: { mode: Mode; geo?: GeoIntel; loading: boolean; onCity: (c: string) => void }) {
  if (!geo) return <div className="muted small">{loading ? "Reading the ecosystems…" : TEXT.intelUnavailable}</div>;
  return (
    <div className={styles.geoCtl} data-testid="geo-controls">
      <p className="muted small">{geo.note}</p>
      <p className="muted small" data-testid="geo-snapshot-note">
        {SNAPSHOT_NOTE}
      </p>
      {mode === "opportunity" && <Opportunity geo={geo} onCity={onCity} />}
      {mode === "go" && <WhereToGo geo={geo} onCity={onCity} />}
      {mode === "gaps" && <CoverageGaps geo={geo} onCity={onCity} />}
    </div>
  );
}
