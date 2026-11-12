import { Panel, Sparkline, Stat } from "@/components/ui";
import type { Snapshot, ValidationPayload } from "../model/types";
import { collecting, horizonLine, leadDays, pct, strengthLine, trendNote, trendRows } from "../model/view";
import styles from "../Validation.module.css";

/** "Are we early?" — the Project Zero edge, its trends over the daily snapshots, and today's outcome evidence. */
export function EarlyTab({ d }: { d: ValidationPayload }) {
  const h = d.headline;
  const min = d.vocab.min_n;
  return (
    <Panel title="Project Zero edge" aside={<span className="faint small">{d.date}</span>} data-testid="val-edge">
      <div className={styles.stats}>
        <Stat label="companies first seen this month" value={h.found_this_month} />
        <Stat label={`pre-funding (${h.pre_funding_this_month} this month)`} value={pct(h.pre_funding_share)} tone="green" />
        <Stat label={`median lead time before a later public event (n=${h.lead_n})`} value={leadDays(h.median_lead_days)} />
        <Stat label="found only through their own funding news (lead 0)" value={h.found_at_announcement} tone="amber" />
        <Stat
          label={`exceptional recall (${h.strong_found_and_kept} of ${h.strong_universe} strong cases)`}
          value={h.exceptional_recall === null ? collecting(h.strong_universe, min) : pct(h.exceptional_recall)}
        />
        <Stat label="strong cases we saw before their public event" value={`${h.strong_found_early} early · ${h.strong_found_late} late`} />
        <Stat label={`false negatives · ${h.never_seen} never seen`} value={h.false_negatives} tone={h.false_negatives ? "red" : undefined} />
        <Stat label="single-source discoveries this month" value={h.unique_source_this_month} />
      </div>
      <Trends snaps={d.snapshots} />
      <div className={`small faint ${styles.mt}`}>
        Outcome evidence today: {strengthLine(d.strength)}. Age of discoveries: {horizonLine(d.horizon)}.
      </div>
    </Panel>
  );
}

/** Direction over the real daily snapshots — shown only with 3+ observations; a trend line, never a significance claim.
 *  The page's one signature graphic (`data-signature="data"`). */
function Trends({ snaps }: { snaps: Snapshot[] }) {
  const rows = trendRows(snaps);
  if (!rows.length) return null;
  return (
    <div className={styles.trends} data-testid="val-trends" data-signature="data">
      {rows.map(([l, v]) => (
        <div key={l} className={styles.trend}>
          <Sparkline values={v} label={l} />
          <span>{l}</span>
        </div>
      ))}
      <span className={styles.trendNote}>{trendNote(snaps.length)}</span>
    </div>
  );
}
