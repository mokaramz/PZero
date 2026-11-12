import { useState } from "react";

import { Button, Field, Panel } from "@/components/ui";
import { useBenchmarkImport, useBenchmarkPreview } from "../api";
import type { ValidationPayload } from "../model/types";
import { benchmarkLine } from "../model/view";
import { benchmarkReady, importLabel, previewLine, type BenchmarkFields, type BenchmarkSummary } from "../model/writes";
import styles from "../Validation.module.css";

/** External benchmarks: did Project Zero see companies before they became visible elsewhere? Only real dates.
 *  An export is previewed first (a POST that writes nothing), then imported with `confirm`. */
export function Benchmarks({ b }: { b: ValidationPayload["benchmarks"] }) {
  const [f, setF] = useState<BenchmarkFields>({ system: "", csv: "" });
  const [prev, setPrev] = useState<BenchmarkSummary | null>(null);
  const preview = useBenchmarkPreview();
  const imp = useBenchmarkImport();
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
          <Button size="sm" busy={preview.isPending} disabled={!benchmarkReady(f)} onClick={() => preview.mutate(f, { onSuccess: setPrev })}>
            Preview
          </Button>
          {prev && (
            <Button size="sm" variant="primary" busy={imp.isPending} onClick={() => imp.mutate({ ...f, confirm: true }, { onSuccess: () => setPrev(null) })}>
              {importLabel(prev)}
            </Button>
          )}
        </div>
        {prev && (
          <div className="small" data-testid="val-benchmark-preview">
            {previewLine(prev)}
          </div>
        )}
      </details>
    </Panel>
  );
}
