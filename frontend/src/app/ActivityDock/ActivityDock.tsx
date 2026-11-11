import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { Link } from "react-router-dom";

import { actions, useClientActions } from "@/lib/activity";
import { isMissingEndpoint } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { cx } from "@/lib/format";
import { buildRows, ICON, isJobRow, summarize, type Activity, type DockRow } from "./rows";
import styles from "./ActivityDock.module.css";

const POLL_BUSY_MS = 2000;
const POLL_IDLE_MS = 15_000;
const AGE_TICK_MS = 10_000; // re-render so completions age out of the compact row

/** Dismissed server-job rows survive route changes (module state), not reloads. */
const dismissedJobs = new Set<string>();

/** Reserve space (`--dock-h`) so the dock never covers page content, Map cards or toasts. */
function useDockHeight(ref: RefObject<HTMLDivElement | null>, visible: boolean) {
  useLayoutEffect(() => {
    const el = ref.current;
    const set = () => document.documentElement.style.setProperty("--dock-h", visible && el ? `${el.offsetHeight + 16}px` : "0px");
    set();
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(set);
    ro.observe(el);
    return () => ro.disconnect();
  });
  useEffect(() => () => document.documentElement.style.setProperty("--dock-h", "0px"), []);
}

const rowTestId = (r: DockRow) => (isJobRow(r) ? "activity-job" : "activity-item");

/**
 * BACKGROUND ACTIVITY DOCK — a light system-status surface fixed at the bottom of the content column. Clicks are
 * acknowledged here instantly; server jobs show their real stage / progress (/api/activity). Collapsed: one row
 * (counts + the most important item). Expanded: every recent row. Running is always shown; failures / partials stay
 * until dismissed; routine completions fade from the compact row after a minute. Hidden when nothing is happening.
 * Without an /api/activity endpoint (404) it shows this browser's clicks only and stops polling.
 */
export function ActivityDock() {
  const mine = useClientActions();
  const busy = mine.some((x) => x.state === "RUNNING");
  const q = useApi<Activity>("activity", undefined, {
    retry: (failures, error) => !isMissingEndpoint(error) && failures < 1,
    refetchInterval: (query) => {
      if (isMissingEndpoint(query.state.error)) return false;
      return (query.state.data as Activity | undefined)?.running || busy ? POLL_BUSY_MS : POLL_IDLE_MS;
    },
  });
  const [open, setOpen] = useState(false);
  const [, tick] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), AGE_TICK_MS);
    return () => window.clearInterval(t);
  }, []);

  // the dock is a clock on purpose: every render (polls, clicks, the age tick) ages its rows against the current time
  // oxlint-disable-next-line react/purity
  const now = Date.now();
  const { rows, compact } = buildRows({ jobs: q.data?.jobs ?? [], mine, now, dismissedJobs, dismissMine: actions.dismiss });
  const visible = rows.length > 0 && (open || compact.length > 0);
  useDockHeight(ref, visible);

  if (!visible) return null;
  const lead = compact[0] ?? rows[0];

  return (
    <div className={styles.wrap}>
      <div ref={ref} className={styles.dock} data-testid="activity-dock" data-open={open || undefined} aria-label="Background activity">
        {open && (
          <ul id="activity-list" className={styles.list} data-testid="activity-list">
            {rows.map((r) => (
              <li key={r.key} className={cx(styles.row, styles[r.state])} data-testid={rowTestId(r)} data-state={r.state}>
                <span className={styles.icon} aria-hidden>
                  {ICON[r.state]}
                </span>
                {r.link ? (
                  <Link to={r.link} className={styles.text}>
                    {r.text}
                  </Link>
                ) : (
                  <span className={styles.text} title={r.detail}>
                    {r.text}
                  </span>
                )}
                {r.detail && r.state !== "RUNNING" && <span className={styles.detail}>{r.detail}</span>}
                {r.state !== "RUNNING" && (
                  <button
                    type="button"
                    className={styles.x}
                    aria-label={`Dismiss: ${r.text}`}
                    onClick={() => {
                      r.dismiss();
                      tick((n) => n + 1);
                    }}
                  >
                    ×
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        <div className={styles.bar} aria-live="polite">
          <span className={styles.title}>Background activity</span>
          {lead && !open && (
            <span className={cx(styles.lead, styles[lead.state])} data-testid={rowTestId(lead)} data-state={lead.state} title={lead.detail}>
              {ICON[lead.state]} {lead.text}
            </span>
          )}
          <span className={styles.summary} data-testid="activity-summary">
            {summarize(compact)}
          </span>
          <button
            type="button"
            className={styles.toggle}
            aria-expanded={open}
            aria-controls="activity-list"
            onClick={() => setOpen((v) => !v)}
            data-testid="activity-toggle"
          >
            {open ? "Hide ▾" : `Show all (${rows.length}) ▴`}
          </button>
        </div>
      </div>
    </div>
  );
}
