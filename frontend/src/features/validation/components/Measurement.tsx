import { Disclosure } from "@/components/focus";
import { Badge, Panel } from "@/components/ui";
import type { ValidationPayload } from "../model/types";
import { measureNeeds, measurementHint, stateTone } from "../model/view";
import styles from "../Validation.module.css";

/** Layer 3: which core metrics are KNOWN, still COLLECTING or NOT YET MEASURABLE — one click away. */
export function Measurement({ d }: { d: ValidationPayload }) {
  return (
    <Disclosure title="What can we measure yet?" icon="question" hint={measurementHint(d.measurement)} testId="val-measurement-d">
      <Panel title="What can we measure yet?" data-testid="val-measurement">
        <div className={styles.meas}>
          {d.measurement.map((m) => (
            <div key={m.metric} className={styles.measRow} data-testid="val-measure" data-state={m.state}>
              <Badge tone={stateTone(m.state)}>{m.state}</Badge>
              <div>
                <b>{m.metric}</b> <span className="faint small">— {m.meaning}</span>
                {m.needs && <div className="small faint">{measureNeeds(m)}</div>}
              </div>
            </div>
          ))}
        </div>
        {!!d.data_issues.length && (
          <div className={`small ${styles.mt}`} data-testid="val-data-issues">
            <b>Data warnings</b> (excluded from the numbers, nothing was changed): {d.data_issues.join(" · ")}
          </div>
        )}
      </Panel>
    </Disclosure>
  );
}
