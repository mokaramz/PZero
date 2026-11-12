import { cx } from "@/lib/format";
import { coverageLevel } from "../model/health";
import type { SourcesPayload } from "../model/types";
import styles from "../Sources.module.css";

/** Geography × sector coverage: VERIFIED (bold) vs POTENTIAL (faint), rows limited to the workspace's geos. */
export function CoverageMatrix({ m, geos }: { m: SourcesPayload; geos: string[] }) {
  const rows = m.geos.filter((g) => geos.includes(g));
  return (
    <>
      <div className={styles.tableWrap}>
        <table className={styles.cov} data-testid="coverage-matrix">
          <thead>
            <tr>
              <th />
              {m.sectors.map((s) => (
                <th key={s}>{m.sector_label[s]}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((g) => (
              <tr key={g}>
                <th scope="row">{m.geo_label[g] || g}</th>
                {m.sectors.map((s) => {
                  const v = m.verified[g]?.[s] ?? 0;
                  const p = m.potential[g]?.[s] ?? 0;
                  const level = coverageLevel(v);
                  return (
                    <td
                      key={s}
                      className={cx(styles.cell, styles[`c_${level}`])}
                      title={`verified ${v.toFixed(1)} of potential ${p.toFixed(1)}`}
                      data-level={level}
                    >
                      {v > 0 ? v.toFixed(1) : "—"}
                      {p > v && <span className={styles.pot}> /{p.toFixed(1)}</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="faint small">
        <b>Bold = VERIFIED</b> coverage (sources that actually returned usable candidates and are healthy) · <span className="faint">/faint = POTENTIAL</span>{" "}
        (configured but unproven). Weights: API/dataset 3 · RSS 1.5 · watcher 1 · manual 0.5, × reliability; 3+ consecutive failures ⇒ 0.
      </div>
    </>
  );
}
