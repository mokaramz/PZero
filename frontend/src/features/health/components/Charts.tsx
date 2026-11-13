/** The System health charts, ported verbatim from the old `Charts.tsx` (review 032a) — without the Grok search bridge
 *  chart, retired with the `search_bridge` key (decision c). */
import { cx } from "@/lib/format";
import { RANGES, STATE_LABEL, jobMatrix, shortModel, spendSeries, usd, worst, type Range } from "../model/dashboard";
import type { Job, Run } from "../model/types";
import styles from "../Health.module.css";

/** Categorical series colours — tokens only, so both themes stay in the PZ palette. */
const SERIES = ["var(--blue)", "var(--green)", "var(--amber)", "var(--slate)", "var(--dot-sage)", "var(--line-sand)"];
const STATE_CLASS: Record<string, string> = {
  completed: styles.cCompleted,
  no_findings: styles.cNoFindings,
  partial: styles.cPartial,
  failed: styles.cFailed,
  interrupted: styles.cFailed,
  budget_blocked: styles.cBlocked,
  waiting_external: styles.cWaiting,
  skipped: styles.cSkipped,
};

export function Spark({ values, color, label }: { values: number[]; color: string; label: string }) {
  const w = 120;
  const h = 24;
  const mx = Math.max(...values, 1e-9);
  const bw = w / Math.max(values.length, 1);
  return (
    <svg className={styles.spark} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label={label}>
      {values.map((v, i) => (
        <rect key={i} x={i * bw + 0.5} y={h - (v / mx) * h} width={Math.max(1, bw - 1)} height={(v / mx) * h} fill={color} rx={1} />
      ))}
    </svg>
  );
}

/** Every scheduled run, per job, per period — a period shows its worst run. Click a period for its runs. */
export function JobMatrix({ jobs, runs, range, now, onCell }: { jobs: Job[]; runs: Run[]; range: Range; now: Date; onCell: (jobId: string, runs: Run[]) => void }) {
  const R = RANGES[range];
  const { start, rows } = jobMatrix(jobs, runs, range, now);
  const lab = (t: number) => {
    const d = new Date(t);
    return range === "24h" ? d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  };
  const next = (j: Job) => (j.overdue ? "overdue" : j.next_due ? `next ${new Date(j.next_due).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : "");
  return (
    <div className={styles.mx} style={{ ["--c" as string]: R.n }} data-testid="job-matrix">
      {rows.map((row) => {
        const j = jobs.find((x) => x.id === row.id)!;
        return (
          <div key={row.id} className={styles.jr} data-job={row.id}>
            <span className={styles.jn} title={j.label}>
              {j.label.split(" (")[0].split(" — ")[0]}
            </span>
            <div className={styles.cellsw}>
              <div className={styles.cells}>
                {row.cells.map((c, i) =>
                  c.length ? (
                    <button
                      key={i}
                      type="button"
                      className={cx(styles.cell, STATE_CLASS[worst(c).state] ?? styles.cCompleted)}
                      data-state={worst(c).state}
                      aria-label={`${j.label}: ${c.length} run${c.length === 1 ? "" : "s"}, ${STATE_LABEL[worst(c).state] ?? worst(c).state}`}
                      title={`${c.length} run${c.length === 1 ? "" : "s"} · ${STATE_LABEL[worst(c).state] ?? worst(c).state}`}
                      onClick={() => onCell(row.id, c)}
                    />
                  ) : (
                    <span key={i} className={cx(styles.cell, styles.cNone)} aria-hidden />
                  ),
                )}
              </div>
            </div>
            <span className={cx(styles.nx, j.overdue && styles.nxOver)}>{next(j)}</span>
          </div>
        );
      })}
      <div className={styles.jr} aria-hidden>
        <span />
        <div className={styles.axis}>
          <span>{lab(start)}</span>
          <span>{lab(start + (R.n / 2) * R.ms)}</span>
          <span>now</span>
        </div>
        <span />
      </div>
    </div>
  );
}

function xLabels(days: string[]) {
  return [0, Math.floor(days.length / 3), Math.floor((2 * days.length) / 3), days.length - 1].map((i) => [i, new Date(`${days[i]}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })] as const);
}

/** General model budget: US$ per day, stacked by model. Real ledger values only. */
export function SpendChart({ byDay, days }: { byDay: Record<string, Record<string, number>>; days: string[] }) {
  const s = spendSeries(byDay, days);
  const W = 640;
  const H = 190;
  const L = 48;
  const B = 24;
  const mx = Math.max(...s.totals, 0.01);
  const cw = (W - L - 6) / days.length;
  const y = (v: number) => H - B - (v / mx) * (H - B - 10);
  if (!s.models.length)
    return <div className={styles.empty}>No paid model call in the last {days.length} days — nothing to chart. History comes from the inference ledger.</div>;
  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Daily model spend, last ${days.length} days, total ${usd(s.total, 3)}`} data-testid="spend-chart">
        {[0, mx / 2, mx].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - 4} y1={y(v)} y2={y(v)} stroke="var(--hair)" />
            <text x={L - 6} y={y(v) + 4} fontSize={10.5} fill="var(--faint)" textAnchor="end">
              {usd(v, v < 0.1 ? 3 : 2)}
            </text>
          </g>
        ))}
        {s.values.map((v, i) => {
          let y0 = H - B;
          return (
            <g key={days[i]}>
              {v.map((x, k) => {
                const hh = (x / mx) * (H - B - 10);
                if (hh <= 0) return null;
                y0 -= hh;
                return (
                  <rect key={k} x={L + i * cw + 2} y={y0} width={cw - 4} height={hh} fill={SERIES[k % SERIES.length]} rx={1.5}>
                    <title>{`${days[i]} · ${shortModel(s.models[k])}: ${usd(x, 4)}`}</title>
                  </rect>
                );
              })}
              {!s.totals[i] && <rect x={L + i * cw + 2} y={H - B - 1} width={cw - 4} height={1} fill="var(--hair-2)" />}
            </g>
          );
        })}
        {xLabels(days).map(([i, t]) => (
          <text key={i} x={L + i * cw + cw / 2} y={H - 6} fontSize={10.5} fill="var(--faint)" textAnchor="middle">
            {t}
          </text>
        ))}
      </svg>
      <div className={styles.legend}>
        {s.models.map((m, k) => (
          <span key={m}>
            <i style={{ background: SERIES[k % SERIES.length] }} />
            {shortModel(m)}
          </span>
        ))}
        <span className={styles.legendTotal}>{usd(s.total, 3)} in {days.length} days</span>
      </div>
    </>
  );
}

