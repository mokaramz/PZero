import { DeferredButton } from "@/components/Deferred";
import { useRefreshStatus } from "../api";
import { NOT_PORTED } from "../model/deferred";
import { lastOkText, plainFailure, progressText, refreshSummary, showsLastOk } from "../model/refresh";
import styles from "../News.module.css";

/**
 * "Refresh news" + the last run's outcome. The refresh itself arrives with 028c, so the button keeps its place and says
 * why it does nothing; the status is read once (the job is idle — the old page polled every 1.5 s only while a run was
 * active, and nothing runs here).
 */
export function NewsRefresh() {
  const s = useRefreshStatus().data;
  const running = !!s?.job.running;
  const last = s?.last;
  const sum = last ? refreshSummary(last) : null;
  return (
    <div className={styles.refresh} data-testid="news-refresh">
      <DeferredButton reason={NOT_PORTED.refresh} data-testid="news-refresh-button">
        {running ? "Refreshing…" : "Refresh news"}
      </DeferredButton>
      <div className={styles.refreshText} aria-live="polite">
        {running && s ? (
          <span data-testid="news-refresh-progress">
            <b>Refreshing news…</b> {progressText(s.job)}
          </span>
        ) : sum ? (
          <span data-testid="news-refresh-result" data-tone={sum.tone} className={styles[`r_${sum.tone}`]}>
            <b>{sum.title}</b> <span className={styles.faint}>{sum.detail}</span>
          </span>
        ) : (
          <span className={styles.faint}>Not refreshed yet.</span>
        )}
        {!running && s && showsLastOk(last) && (
          <span className={styles.faint} data-testid="news-last-ok">
            {" "}
            {lastOkText(s)}
          </span>
        )}
        {!running && last?.sources_failed?.length ? (
          <details className={styles.faint}>
            <summary>Which sources failed?</summary>
            {last.sources_failed.map((f) => (
              <div key={f}>{plainFailure(f)}</div>
            ))}
          </details>
        ) : null}
      </div>
    </div>
  );
}
