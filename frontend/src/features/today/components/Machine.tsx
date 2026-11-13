import { useNavigate } from "react-router-dom";

import { Icon } from "@/components/Icon";
import { Button } from "@/components/ui";
import { asRole } from "@/lib/roles";
import type { TodayView } from "../model/types";
import { exceptionsLine, footerLine, machineLine, reviewCount, snapshotLine } from "../model/view";
import styles from "../Today.module.css";

/** Where the two triage buttons go (they navigate; nothing is posted). */
export const REVIEW_LINK = "/deal-flow?filter=triage&route=NEEDS_MOHAMED";
export const QUEUE_LINK = "/deal-flow?filter=triage";

/** MACHINE — one quiet line; the counts, the exceptions summary, the snapshot note and how Today is chosen live under
 *  Details. */
export function Machine({ d }: { d: TodayView }) {
  const navigate = useNavigate();
  const t = d.triage;
  const c = t?.counts ?? {};
  const review = reviewCount(t);
  const note = snapshotLine(d.snapshot);
  return (
    <details className={styles.machine} data-testid="today-triage" aria-label="Machine work">
      <summary>
        <Icon name="layers" size={17} className={styles.machineIcon} />
        <span className={styles.machineTitle}>Machine work</span>
        <span className={styles.machineKicker}>Machine</span>
        {machineLine(t)}
        <span className={styles.machineMore}>
          Details <Icon name="arrow" size={12} />
        </span>
      </summary>
      <div className={styles.machineBody}>
        <p data-testid="today-exceptions">
          {exceptionsLine(d)}
          {d.machine_working && <> · {asRole(d.machine_working)}</>}
        </p>
        {t && (
          <>
            <div className={styles.triageStats}>
              <span>{t.total} machine proposals handled</span>
              <span data-testid="triage-needs">
                <b>{t.needs_mohamed}</b> need your judgment
              </span>
              <span>{c.CASE_PREPARING ?? 0} queued for case preparation</span>
              <span>{c.BACKGROUND_RESEARCH ?? 0} in the machine research queue</span>
              <span>{(c.MACHINE_WATCH ?? 0) + (c.DEFERRED_LOW_PRIORITY ?? 0)} watched / deferred</span>
              {!!c.CONFLICT_GATED && <span>{c.CONFLICT_GATED} conflict-gated (Manager)</span>}
              <span>{t.calibration} calibration samples</span>
              {!!t.resurfaced && <span>{t.resurfaced} resurfaced by new evidence</span>}
              {!!t.queued_beyond_budget && (
                <span>
                  {t.queued_beyond_budget} more wait beyond today’s budget of {t.limit}
                </span>
              )}
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              {review > 0 && (
                <Button size="sm" variant="primary" onClick={() => navigate(REVIEW_LINK)} data-testid="triage-review">
                  Review {review}
                </Button>
              )}
              <Button size="sm" onClick={() => navigate(QUEUE_LINK)} data-testid="triage-queue">
                View queue
              </Button>
            </div>
          </>
        )}
        {note && (
          <p className="faint small" data-testid="today-snapshot">
            {note}
          </p>
        )}
        <p className="faint small" data-testid="today-footer">
          {footerLine(d)}
        </p>
      </div>
    </details>
  );
}
