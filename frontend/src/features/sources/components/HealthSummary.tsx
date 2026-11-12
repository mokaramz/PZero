import { healthCounts } from "../model/health";
import type { Source } from "../model/types";
import styles from "../Sources.module.css";

/** The four health tiles and the one-line summary, over every configured source (not the workspace's). */
export function HealthSummary({ sources }: { sources: Source[] }) {
  const h = healthCounts(sources);
  const enabled = sources.filter((s) => s.enabled).length;
  const tile = (className: string, n: number, label: string) => (
    <div className={className}>
      <div className={styles.n}>{n}</div>
      <div className={styles.l}>{label}</div>
    </div>
  );
  return (
    <div className={styles.sum} data-testid="source-health">
      {tile(styles.sumOk, h.ok, "healthy")}
      {tile(styles.sumWarn, h.warn, "warning")}
      {tile(styles.sumFail, h.failed, "failed")}
      {tile(styles.sumOff, h.off, "disabled")}
      <div className={styles.sumTxt}>
        {sources.length} sources configured · {enabled} enabled · {h.failed ? `${h.failed} failing` : "no failing sources"}
        {h.warn ? ` · ${h.warn} with a warning or not yet scanned` : ""}
        {h.failed || h.warn ? " — recorded calmly and retried on the next scan" : ""}
      </div>
    </div>
  );
}
