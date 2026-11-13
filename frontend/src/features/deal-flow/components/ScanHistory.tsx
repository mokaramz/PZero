import { useState } from "react";

import { Async } from "@/components/ui";
import { useApi } from "@/lib/hooks";
import { HISTORY_N, mergedOf, SCAN_HISTORY } from "../model/scan";
import type { ScanHistory as ScanHistoryT } from "../model/types";
import styles from "../DealFlow.module.css";

function HistoryTable({ n }: { n: number }) {
  const q = useApi<ScanHistoryT>(SCAN_HISTORY, { n });
  return (
    <Async q={q} label="Loading scan history…">
      {(h) =>
        h.scans.length ? (
          <div className={styles.tableWrap}>
            <table className={styles.histTbl} data-testid="scan-history-table">
              <thead>
                <tr>
                  <th>Scan</th>
                  <th>Sources ok / failed / off</th>
                  <th>Raw</th>
                  <th>New</th>
                  <th>Already known</th>
                  <th>Merged</th>
                  <th>Baseline</th>
                  <th>{h.pipeline_label}</th>
                </tr>
              </thead>
              <tbody>
                {[...h.scans].reverse().map((s) => (
                  <tr key={s.run_id}>
                    <td>{s.run_id}</td>
                    <td>
                      {s.sources_ok || 0} / {s.sources_failed || 0} / {s.sources_off || 0}
                    </td>
                    <td>{s.raw_records || 0}</td>
                    <td>
                      <b>{s.new || 0}</b>
                    </td>
                    <td>{s.known_skipped || 0}</td>
                    <td>{mergedOf(s)}</td>
                    <td>{s.baseline || 0}</td>
                    <td>{s.known_pipeline || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="faint small">
              {h.total} scan{h.total === 1 ? "" : "s"} recorded in total · showing the latest {h.scans.length}.
            </div>
          </div>
        ) : (
          <div className="faint small">No scans recorded yet.</div>
        )
      }
    </Async>
  );
}

/** Scan history ledger (GET deal-flow/scan_history) — loaded only when opened. */
export function ScanHistory() {
  const [open, setOpen] = useState(false);
  return (
    <details className={styles.history} data-testid="scan-history" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>Scan history</summary>
      {open && <HistoryTable n={HISTORY_N} />}
    </details>
  );
}
