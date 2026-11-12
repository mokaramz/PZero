import { DeferredButton } from "@/components/Deferred";
import { Panel, Segmented, Stat } from "@/components/ui";
import { NOT_PORTED } from "../model/deferred";
import { STAGES, type ValidationPayload } from "../model/types";
import { collecting, DIMS, dimLabel, label, newestFirst, pct, verificationLine, whoWasRight, type Dim } from "../model/view";
import styles from "../Validation.module.css";

/** "Are we right?" — quality conversion by grouping, the human-vs-machine calibration and the outcome ledger. The
 *  grouping is the page's state, so it survives a visit to another question (only the chosen tab is mounted). */
export function RightTab({ d, dim, onDim }: { d: ValidationPayload; dim: Dim; onDim: (dim: Dim) => void }) {
  const conv = d.conversion[dim] || [];
  return (
    <div className={styles.page}>
      <Panel
        title="Quality conversion"
        aside={<Segmented value={dim} onChange={onDim} options={DIMS.map((x) => ({ value: x.value, label: x.label }))} label="Group by" />}
        data-testid="val-conversion"
      >
        {conv.length ? (
          <div className={styles.scroll}>
            <table className={styles.tbl}>
              <thead>
                <tr>
                  <th>{dimLabel(dim)}</th>
                  {STAGES.map((s) => (
                    <th key={s}>{d.stage_labels[s]}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {conv.map((r) => (
                  <tr key={r.group}>
                    <td className={styles.name}>{label(r.group)}</td>
                    {STAGES.map((s) => (
                      <td key={s} className={r[s] ? "" : "faint"}>
                        {r[s]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="faint small">No companies in this grouping yet.</div>
        )}
      </Panel>

      <div className={styles.two}>
        <Calibration d={d} />
        <OutcomeLedger d={d} />
      </div>
    </div>
  );
}

function Calibration({ d }: { d: ValidationPayload }) {
  const cal = d.calibration;
  const min = d.vocab.min_n;
  return (
    <Panel title="Smooth Operator calibration — human vs machine" data-testid="val-calibration">
      <div className={styles.stats}>
        <Stat label="your triage decisions" value={cal.decisions} />
        <Stat label="agreement with machine" value={cal.agreement === null ? collecting(cal.decisions, min) : pct(cal.agreement)} />
        <Stat label="machine REJECTs you overturned" value={cal.machine_rejects_overturned} />
        <Stat label="machine KEEPs you rejected" value={cal.machine_keeps_rejected} />
        <Stat label="review time (est. from timestamps)" value={`${Math.round(cal.review_minutes_est)} min`} />
      </div>
      <div className={`small ${styles.mt}`}>
        <b>When you disagreed, who was right?</b> {whoWasRight(cal)}
      </div>
      {d.patterns.length ? (
        <ul className="small">
          {d.patterns.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      ) : (
        <div className="small faint">Patterns appear once a decision group has {min}+ resolved outcomes. They describe — they never change your scoring.</div>
      )}
      <div className="small" data-testid="val-verification-cal">
        <b>Verification proposals you decided:</b> {verificationLine(d.verification_calibration)}
      </div>
      <div className="small faint">{cal.note}</div>
    </Panel>
  );
}

/** Newest first. Retract is a write (review 027b): visible, disabled with its reason. */
function OutcomeLedger({ d }: { d: ValidationPayload }) {
  return (
    <Panel title="Outcome ledger" data-testid="val-outcomes">
      {!d.outcomes.length ? (
        <div className="small faint">
          No outcomes recorded yet. When a company you saw raises a round, joins an accelerator, lands a customer — or shuts down — record it with the date
          it happened. That is what turns discoveries into lead time and recall.
        </div>
      ) : (
        newestFirst(d.outcomes).map((o) => (
          <div key={o.id} className={styles.audit} data-testid="val-outcome">
            <b>{o.company}</b> — {d.vocab.kinds[o.kind] || o.kind} · {o.event_date}{" "}
            {o.evidence_url && (
              <a href={o.evidence_url} target="_blank" rel="noreferrer">
                source
              </a>
            )}
            <DeferredButton size="sm" variant="ghost" reason={NOT_PORTED.writes}>
              Retract
            </DeferredButton>
          </div>
        ))
      )}
    </Panel>
  );
}
