import { Button } from "@/components/ui";
import { cx } from "@/lib/format";
import { useTriageAuto } from "../hooks/useTriageAuto";
import { autoTriageText, autoTriageTone, retryWaiting } from "../model/triageAuto";
import styles from "../DealFlow.module.css";

/**
 * Post-scan machine triage (accepted v3, proposal-only), separate from the deterministic Attention score — ported from
 * the old `AutoTriageStatus` (review 035b): the run's one sentence, and "Retry now (N)" while candidates wait for a
 * retry and no run is going. Nothing shows while a scan runs (`hidden`), when automatic triage is off, before the first
 * run, or on a server without the endpoint.
 */
export function AutoTriageStatus({ watch, hidden }: { watch: boolean; hidden?: boolean }) {
  const { status: d, retryNow, retrying } = useTriageAuto(watch);
  if (hidden || !d || !d.enabled || !d.last) return null;
  const waiting = retryWaiting(d);
  const tone = autoTriageTone(d.last);
  return (
    <div className={cx("small", styles.autoTriage)} data-testid="auto-triage-status" data-state={d.running ? "running" : d.last.state}>
      <b className={cx(tone === "failed" && styles.redText, tone === "pending" && styles.amberText)}>{tone ? "⚠ " : ""}Machine triage after scan</b>{" "}
      <span className="faint">(proposals only — the Attention score is separate):</span> <span data-testid="auto-triage-text">{autoTriageText(d.last, d.running)}</span>
      {waiting > 0 && (
        <>
          {" "}
          <Button size="sm" variant="ghost" busy={retrying} onClick={retryNow} data-testid="triage-retry-now">
            Retry now ({waiting})
          </Button>
        </>
      )}
    </div>
  );
}
