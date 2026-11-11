import type { RefObject } from "react";
import { Link } from "react-router-dom";

import { Icon } from "@/components/Icon";
import { Card } from "@/components/ui";
import { NOT_PORTED } from "../model/deferred";
import type { InboxPayload } from "../model/types";
import { useDeferred } from "./Deferred";
import { DeferredButton } from "./DeferredButton";
import styles from "../DealFlow.module.css";

/** The last scan, from the inbox (read-only). The live scan progress and the per-source report arrive with the scan port. */
function ScanStatus({ ib }: { ib: InboxPayload }) {
  const s = ib.last_summary || {};
  const merged = (s.merged_cross_source || 0) + (s.merged_into_existing || 0);
  return (
    <details className={styles.scanFold} data-testid="scan-fold">
      <summary className={styles.scanSummary}>
        <span className={styles.scanKicker}>Scan status</span> {ib.last_run ? `last run ${ib.last_run.slice(0, 16)} · ${s.new || 0} new` : "never run"}
        <span className={styles.scanMore}>Details</span>
      </summary>
      <div className={styles.findSt} data-testid="find-status">
        {ib.last_run ? (
          <>
            Last run {ib.last_run} — <b>{s.new || 0} genuinely new</b> ({s.pre_company_new || 0} from pre-company channels) · {s.baseline || 0} baseline ·{" "}
            {s.noise || 0} noise auto-rejected
            {s.run_id
              ? ` · ${s.known_skipped || 0} already known (skipped) · ${merged} merged · ${s.known_pipeline || 0} ${(ib.pipeline_label || "existing pipeline").toLowerCase()}`
              : ""}
          </>
        ) : (
          <>
            Never run. <b>First run only saves a baseline</b> of the pre-company pages (filed under "Baseline", not new). Feeds return items immediately.
          </>
        )}
      </div>
      {ib.last_run && (
        <div className="faint small" data-testid="scan-report" data-deferred="">
          {NOT_PORTED.scanReport}
        </div>
      )}
    </details>
  );
}

/** Find New Candidates · Analyze Top N · feed window — in place, disabled until the scan and analysis ports. */
function FindBar({ ib, anchorRef }: { ib: InboxPayload; anchorRef: RefObject<HTMLDivElement | null> }) {
  const batch = useDeferred(NOT_PORTED.analysis);
  const days = useDeferred(NOT_PORTED.scan);
  return (
    <Card className={styles.findbar}>
      <div className={styles.findRow} ref={anchorRef} id="find-bar">
        <DeferredButton size="lg" reason={NOT_PORTED.scan} data-testid="find-btn">
          Find New Candidates
        </DeferredButton>
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
        <select
          value="7"
          disabled
          aria-label="Feed window"
          className={styles.days}
          title={days.props.title}
          aria-describedby={days.props["aria-describedby"]}
          data-deferred=""
        >
          <option value="7">last 7 days</option>
          <option value="14">last 14 days</option>
          <option value="30">last 30 days</option>
        </select>
        {days.note}
      </div>
      <ScanStatus ib={ib} />
    </Card>
  );
}

/** The scan history ledger: its summary stays in place but does not open (and loads nothing) until the scan port. */
function ScanHistory() {
  const d = useDeferred(NOT_PORTED.scanHistory);
  return (
    <>
      <details className={styles.history} data-deferred="" data-testid="scan-history">
        <summary title={d.props.title} aria-describedby={d.props["aria-describedby"]} aria-disabled="true" onClick={d.props.onClick}>
          Scan history
        </summary>
      </details>
      {d.note}
    </>
  );
}

/** Machine analysis: secondary to human review — one quiet band below the decision surface. */
export function MachineZone({ ib, findRef }: { ib: InboxPayload; findRef: RefObject<HTMLDivElement | null> }) {
  return (
    <section className={styles.machineZone} aria-label="Machine analysis" data-zone="background">
      <h2 className={styles.machineTitle}>
        <Icon name="layers" size={20} className={styles.machineIcon} /> Machine analysis
      </h2>
      <FindBar ib={ib} anchorRef={findRef} />
      <ScanHistory />
      <p className="faint small">
        Source registry, coverage and health live on the <Link to="/sources">Sources</Link> page.
      </p>
    </section>
  );
}
