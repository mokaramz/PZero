import { useState } from "react";

import { DeferredButton } from "@/components/Deferred";
import { Field, Panel } from "@/components/ui";
import { NOT_PORTED } from "../model/deferred";
import type { ValidationPayload } from "../model/types";
import { benchmarkLine } from "../model/view";
import styles from "../Validation.module.css";

/** External benchmarks: did Project Zero see companies before they became visible elsewhere? Only real dates.
 *  The import form keeps its place and its fields; Preview (and so "Import N dates") is a write that arrives with
 *  review 027b. */
export function Benchmarks({ b }: { b: ValidationPayload["benchmarks"] }) {
  const [f, setF] = useState({ system: "", csv: "" });
  return (
    <Panel title="External benchmarks — earlier than everyone else?" data-testid="val-benchmarks">
      <p className="small faint">{b.note}</p>
      {b.systems.length ? (
        b.systems.map((s) => (
          <div key={s.system} className={`small ${styles.bench}`} data-testid="val-benchmark">
            <b>{s.system}</b>: {benchmarkLine(s)}
            <ul className={styles.benchList}>
              {s.examples.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
        ))
      ) : (
        <div className="small faint">No benchmark dates yet.</div>
      )}
      <details>
        <summary className="small">Import a benchmark export (e.g. a Dealroom CSV you downloaded)</summary>
        <Field label="Which system">
          <input value={f.system} onChange={(e) => setF({ ...f, system: e.target.value })} placeholder="Dealroom" />
        </Field>
        <Field label="CSV text (needs a name column and a date column)">
          <textarea rows={5} value={f.csv} onChange={(e) => setF({ ...f, csv: e.target.value })} />
        </Field>
        <div className="row">
          <DeferredButton size="sm" reason={NOT_PORTED.writes}>
            Preview
          </DeferredButton>
        </div>
      </details>
    </Panel>
  );
}
