import { useState } from "react";

import { Badge } from "@/components/ui";
import { plainSourceProblem } from "@/lib/activity";
import { cx } from "@/lib/format";
import { repInWS, type Workspace } from "../model/geo";
import { mergedOf, refusedText } from "../model/scan";
import type { ReportRow, ScanSummary, WsGeos } from "../model/types";
import styles from "../DealFlow.module.css";

const WS_NAME: Record<Workspace, string> = {
  eu: "Europe",
  na: "North America",
  unk: "all geographies (unresolved items)",
  all: "all geographies",
};

/** v1 scanLedger: the honest accounting of one scan (new vs already known vs merged vs baseline vs existing pipeline). */
export function ScanLedger({ s, pipelineLabel }: { s?: ScanSummary; pipelineLabel?: string }) {
  if (!s || !s.run_id) return null;
  const pl = pipelineLabel || "Existing pipeline — not discovered in this scan";
  const cross = s.merged_cross_source || 0;
  const into = s.merged_into_existing || 0;
  const names = s.known_pipeline_names || [];
  const fresh = s.new_companies || [];
  return (
    <div className={styles.ledger} data-testid="scan-ledger">
      <b>Scan ledger {s.run_id}</b> (started {s.scan_started || ""}, finished {s.scan_finished || ""}) · sources attempted {s.sources_attempted || 0}:{" "}
      <span className={styles.okText}>{s.sources_ok || 0} successful</span> / <span className={styles.failText}>{s.sources_failed || 0} failed</span> /{" "}
      {s.sources_off || 0} disabled · raw records retrieved {s.raw_records || 0} · <b>genuinely new {s.new || 0}</b> · already known skipped {s.known_skipped || 0} ·
      duplicates merged {mergedOf(s)} ({cross} cross-source, {into} into existing) · baseline {s.baseline || 0} · {pl}: {s.known_pipeline || 0}
      {names.length ? ` (${names.join(", ")})` : ""}
      {fresh.length > 0 && (
        <div className={styles.ledgerNew}>
          New this scan:{" "}
          {fresh.slice(0, 12).map((n, i) => (
            <span key={`${n.id ?? n.name}-${i}`}>
              {i > 0 && " · "}
              <a href={n.source_url || "#"} target="_blank" rel="noreferrer">
                {n.name}
              </a>{" "}
              <span className="faint">
                ({n.source} · source date {n.source_date || "UNKNOWN"} · first seen {n.first_seen || ""})
              </span>
            </span>
          ))}
          {fresh.length > 12 ? " …" : ""}
        </div>
      )}
    </div>
  );
}

/** One source of the report. New (034a): the items the intake refused, after the old counts (the reason is the note). */
function RepRow({ x }: { x: ReportRow }) {
  const refused = refusedText(x.refused);
  return (
    <div className={cx(styles.repRow, styles[`rep_${x.status}`])} data-testid="scan-rep-row" data-source={x.source}>
      {x.source} <Badge tone={x.tier === "watcher" ? "green" : "neutral"}>{(x.tier || "").toUpperCase()}</Badge>{" "}
      {x.status === "failed" ? (
        <>
          {plainSourceProblem(x.note || "")} <span className="faint">({x.note})</span>
        </>
      ) : (
        x.note
      )}
      {x.status === "ok" && x.raw != null && (
        <span className="faint">
          {" "}
          · raw {x.raw} · records {x.count}
          {x.baseline ? ` · baseline ${x.baseline}` : ""}
        </span>
      )}
      {refused && (
        <span className={styles.failText} data-testid="scan-rep-refused">
          {" "}
          · {refused}
        </span>
      )}
    </div>
  );
}

/** The last scan's per-source report: health counts, the failed sources in plain words, the ledger, and the rows of
 *  the workspace's geographies (the others folded under "other geographies"). */
export function ScanReport({ report, summary, ws, geos, pipelineLabel, forceOpen }: {
  report: ReportRow[];
  summary?: ScanSummary;
  ws: Workspace;
  geos: WsGeos;
  pipelineLabel?: string;
  forceOpen?: boolean;
}) {
  const [open, setOpen] = useState(false);
  if (!report.length) return null;
  const ok = report.filter((x) => x.status === "ok").length;
  const fail = report.filter((x) => x.status === "failed").length;
  const off = report.filter((x) => x.status === "off").length;
  const inWS = report.filter((x) => repInWS(x, ws, geos));
  const rest = report.filter((x) => !repInWS(x, ws, geos));
  return (
    <div className={styles.report} data-testid="scan-report">
      <div className={styles.repSum}>
        <span>
          <b>{report.length} sources</b> · <span className={styles.okText}>{ok} healthy</span> · <span className={styles.failText}>{fail} failed</span> · {off}{" "}
          disabled
        </span>
        <span className="faint">
          showing {WS_NAME[ws]} ({inWS.length})
        </span>
      </div>
      {fail > 0 && (
        <div className={styles.repOutcome} data-testid="scan-outcome">
          <b>⚠ Scan partially complete</b> — {ok} sources successful, {fail} unavailable:{" "}
          {report
            .filter((x) => x.status === "failed")
            .map((x) => `${x.source} — ${plainSourceProblem(x.note || "")}`)
            .join("; ")}
          . No companies from the successful sources were lost; failing sources are retried at the next scan (System health shows why and what to do).
        </div>
      )}
      <ScanLedger s={summary} pipelineLabel={pipelineLabel} />
      <details className={styles.repDetails} open={forceOpen || open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary>Show source details</summary>
        <div className={styles.repGrid}>
          {inWS.map((x, i) => (
            <RepRow key={`${x.source}-${i}`} x={x} />
          ))}
        </div>
        {rest.length > 0 && (
          <details className={styles.repMore}>
            <summary>Show all {report.length} rows (other geographies)</summary>
            <div className={styles.repGrid}>
              {rest.map((x, i) => (
                <RepRow key={`${x.source}-${i}`} x={x} />
              ))}
            </div>
          </details>
        )}
      </details>
    </div>
  );
}
