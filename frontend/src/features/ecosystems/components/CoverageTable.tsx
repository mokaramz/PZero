import { familyCounts, familyShort } from "../model/coverage";
import type { CovEcosystem, FamilyDef } from "../model/types";
import styles from "../Ecosystems.module.css";
import { CovTag } from "./CovTag";

/** One row per ecosystem: its overall state, one cell per source family, the last successful retrieval and the audit
 *  opinion. A click on the row (or the city) selects it. */
export function CoverageTable({ rows, families, sel, onSel }: { rows: CovEcosystem[]; families: FamilyDef[]; sel: string | null; onSel: (id: string) => void }) {
  return (
    <div className={styles.covWrap}>
      <table className={styles.cov}>
        <thead>
          <tr>
            <th>Ecosystem</th>
            <th>Coverage</th>
            {families.map(([id, l]) => (
              <th key={id} title={l}>
                {familyShort(l)}
              </th>
            ))}
            <th>Last successful retrieval</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.id} className={sel === e.id ? styles.covSel : undefined} onClick={() => onSel(e.id)}>
              <td>
                <button type="button" className={styles.linkBtn} onClick={() => onSel(e.id)}>
                  {e.city}
                </button>{" "}
                <span className="muted small">
                  {e.country_name}
                  {e.region ? ` · ${e.region}` : ""}
                </span>
              </td>
              <td>
                <CovTag st={e.overall} />
                <div className="muted small">{e.label}</div>
              </td>
              {families.map(([id]) => {
                const f = e.families[id];
                return (
                  <td key={id} title={f?.why}>
                    <CovTag st={f?.state} />
                    <div className="muted small">
                      {familyCounts(f)}
                      {!!f?.candidates?.length && <b> · +{f.candidates.length} cand.</b>}
                    </div>
                  </td>
                );
              })}
              <td className="muted small">
                {e.last_successful_retrieval || "—"}
                {e.audit?.status && (
                  <div>
                    audit: <CovTag st={e.audit.status} />
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
