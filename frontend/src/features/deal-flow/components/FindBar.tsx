import { useState, type RefObject } from "react";

import { Button, Card } from "@/components/ui";
import { cx } from "@/lib/format";
import { useScan } from "../hooks/useScan";
import { NOT_PORTED } from "../model/deferred";
import type { Workspace } from "../model/geo";
import { mergedOf, scanIcon, scanningLabel, TRIAGE_LATER } from "../model/scan";
import type { InboxPayload, WsGeos } from "../model/types";
import { useDeferred } from "./Deferred";
import { DeferredButton } from "./DeferredButton";
import { ScanReport } from "./ScanReport";
import styles from "../DealFlow.module.css";

/**
 * Find New Candidates (POST find + find_status polling), the feed window and the last-scan report — ported from the old
 * `FindBar` (review 034a). Analyze Top N stays in place, disabled until the analysis port; the old post-scan machine
 * triage status is the one declared line, since triage does not run after the scan yet.
 */
export function FindBar({
  ib,
  ws,
  geos,
  onScanFinished,
  anchorRef,
}: {
  ib: InboxPayload;
  ws: Workspace;
  geos: WsGeos;
  onScanFinished: () => void;
  /** Deep link target (/deal-flow?find=1): the page scrolls here and focuses the Find button. */
  anchorRef: RefObject<HTMLDivElement | null>;
}) {
  const [days, setDays] = useState("7");
  const scan = useScan(onScanFinished);
  const fs = scan.status;
  const running = scan.running;
  const batch = useDeferred(NOT_PORTED.analysis);

  const s = ib.last_summary || {};

  return (
    <Card className={cx(styles.findbar, running && styles.scanning)}>
      <div className={styles.findRow} ref={anchorRef} id="find-bar">
        <Button size="lg" onClick={() => scan.start(days)} disabled={running || scan.pending} data-testid="find-btn">
          {running ? scanningLabel(fs) : "Find New Candidates"}
        </Button>
        {running && <span className={styles.radar} aria-hidden />}
        <label className={styles.batchLabel}>
          Analyze Top{" "}
          <input
            type="number"
            min={1}
            max={15}
            value="5"
            readOnly
            disabled
            className={styles.numInput}
            aria-label="Number of candidates to analyze"
            title={batch.props.title}
            aria-describedby={batch.props["aria-describedby"]}
            data-deferred=""
          />
        </label>
        {batch.note}
        <DeferredButton reason={NOT_PORTED.analysis}>Analyze Top Candidates</DeferredButton>
        <select value={days} onChange={(e) => setDays(e.target.value)} aria-label="Feed window" className={styles.days}>
          <option value="7">last 7 days</option>
          <option value="14">last 14 days</option>
          <option value="30">last 30 days</option>
        </select>
      </div>
      <details className={styles.scanFold} open={running || undefined} data-testid="scan-fold">
        <summary className={styles.scanSummary}>
          <span className={styles.scanKicker}>Scan status</span>{" "}
          {running
            ? `scanning ${fs?.done ?? 0} / ${fs?.total ?? 0}`
            : ib.last_run
              ? `last run ${ib.last_run.slice(0, 16)} · ${s.new || 0} new`
              : "never run"}
          <span className={styles.scanMore}>Details</span>
        </summary>
        <div className={styles.findSt} data-testid="find-status">
          {running ? (
            <>
              <b>
                Scanning {fs?.done} / {fs?.total}
              </b>{" "}
              — sources run concurrently; slow ones cannot block the rest.
            </>
          ) : ib.last_run ? (
            <>
              Last run {ib.last_run} — <b>{s.new || 0} genuinely new</b> ({s.pre_company_new || 0} from pre-company channels) · {s.baseline || 0} baseline ·{" "}
              {s.noise || 0} noise auto-rejected
              {s.run_id
                ? ` · ${s.known_skipped || 0} already known (skipped) · ${mergedOf(s)} merged · ${s.known_pipeline || 0} ${(ib.pipeline_label || "existing pipeline").toLowerCase()}`
                : ""}
            </>
          ) : (
            <>
              Never run. <b>First run only saves a baseline</b> of the pre-company pages (filed under "Baseline", not new). Feeds return items immediately.
            </>
          )}
        </div>
        {!running && ib.last_run && (
          <div className="faint small" data-testid="scan-triage">
            {TRIAGE_LATER}
          </div>
        )}
        {running ? (
          <div className={styles.repGrid} data-testid="scan-progress">
            {(fs?.rows || []).slice(-6).map((r, i) => (
              <div key={`${r.source}-${i}`} className={cx(styles.repRow, styles[`rep_${r.status === "off" ? "failed" : r.status}`])}>
                {scanIcon(r.status)} {r.source} <span className="faint">{(r.note || "").slice(0, 70)}</span>
              </div>
            ))}
          </div>
        ) : (
          ib.last_run && <ScanReport report={ib.report || []} summary={ib.last_summary} ws={ws} geos={geos} pipelineLabel={ib.pipeline_label} />
        )}
      </details>
    </Card>
  );
}
