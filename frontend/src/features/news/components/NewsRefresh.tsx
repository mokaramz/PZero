import { Button } from "@/components/ui";
import { useRefreshNews, useRefreshStatus } from "../api";
import { ALREADY_RUNNING, isNotStarted, lastOkText, plainFailure, progressText, refreshSummary, showsLastOk } from "../model/refresh";
import styles from "../News.module.css";

/**
 * "Refresh news" + the last run's outcome (028c). The run executes inside its request (decision e): while it is in flight
 * the button and the line show the old running state, and when it returns the status, the stories and the sources are
 * read again, so the line shows the new outcome. Nothing polls (the old page polled every 1.5 s while a background run
 * was active). A run already active elsewhere is the old "already running" line; a failure is the failure toast.
 */
export function NewsRefresh() {
  const s = useRefreshStatus().data;
  const run = useRefreshNews();
  const running = !!s?.job.running || run.isPending;
  const msg = isNotStarted(run.data) ? run.data.reason || ALREADY_RUNNING : "";
  const start = () => {
    if (running) return;
    run.mutate();
  };
  const last = s?.last;
  const sum = last ? refreshSummary(last) : null;
  return (
    <div className={styles.refresh} data-testid="news-refresh">
      <Button onClick={start} busy={running} disabled={running} data-testid="news-refresh-button">
        {running ? "Refreshing…" : "Refresh news"}
      </Button>
      <div className={styles.refreshText} aria-live="polite">
        {running ? (
          <span data-testid="news-refresh-progress">
            <b>Refreshing news…</b> {s?.job.running ? progressText(s.job) : ""}
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
        {msg && (
          <span className={styles.faint} data-testid="news-refresh-message">
            {" "}
            {msg}
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
