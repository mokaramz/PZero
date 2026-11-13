/**
 * Machine triage after a scan, on the page (review 035b): the old `AutoTriageStatus` line in the FindBar and its
 * "Retry now". The ONE place its paths, pace and texts live. The paths are new, the bodies the old ones:
 *
 * - `GET deal-flow/triage_auto` → the old `auto_triage.status()`: `{running, last, enabled, retry{waiting, next_try}}`.
 *   `last` is the latest automatic run's record; the backend writes its one plain `summary` sentence (no codes, no
 *   payloads), and "running" is the only client-side wording, as before.
 * - `POST deal-flow/triage_retry` → `{started: true}`, or `{started: false, reason}` with the old reasons ("Nothing is
 *   waiting for a retry.", "A machine triage run is already in progress.").
 *
 * The status is polled every 2 s while a run is going and for 60 s after a scan this page saw finish (machine triage
 * starts once the scan has committed). A run that finishes while the page is open is announced once, and the views it
 * changes are read again.
 */
export const TRIAGE_AUTO = "deal-flow/triage_auto";
export const TRIAGE_RETRY = "deal-flow/triage_retry";

/** The old poll pace while a run is going (or while watching after a scan). */
export const AUTO_POLL_MS = 2000;
/** How long the page watches for the post-scan run after a scan it saw finish (the old 60 s). */
export const WATCH_MS = 60_000;

/** One candidate a run could not finish, in plain words (the old `_retry_item`). */
export type AutoItem = { id: string; name?: string | null; reason: string; category?: string; retry?: string; next_try?: string | null; attempts?: number };

/** The old auto-run record, as the UI may show it. */
export type AutoRun = {
  scan_run_id: string;
  state: "running" | "done" | "partial" | "failed";
  selected: number;
  started?: string;
  triaged?: number;
  counts?: Record<string, number>;
  unchanged_skipped?: number;
  pending?: AutoItem[];
  failed?: AutoItem[];
  usd?: number;
  note?: string;
  finished?: string;
  summary?: string;
  retry?: boolean;
};

export type AutoStatus = { running: boolean; enabled: boolean; last: AutoRun | null; retry?: { waiting: number; next_try: string | null } };

export type RetryAnswer = { started: boolean; reason?: string };

/** The old activity label of Retry now. */
export const RETRY_LABEL = "Retrying machine triage";
/** The old toast when Retry now started a run (a refusal shows the server's reason). */
export const RETRY_STARTED = "Retrying the preserved candidates — see Background activity";
export const retryToast = (r: RetryAnswer) => (r.started ? RETRY_STARTED : r.reason);

/** The one line under the scan status: the backend's sentence, or the old running wording. */
export function autoTriageText(r: AutoRun | null, running: boolean): string {
  if (!r) return "";
  if (running || r.state === "running") return `${r.selected} new or changed candidate(s) — machine triage running…`;
  return r.summary || "Machine triage finished.";
}

/** The old colour of the heading: red when something needs a manual retry, amber when items are kept for a retry. */
export function autoTriageTone(r: AutoRun): "failed" | "pending" | null {
  if (r.failed?.length) return "failed";
  if (r.pending?.length) return "pending";
  return null;
}

/** "Retry now (N)" shows while candidates are waiting and no run is going. */
export const retryWaiting = (d: AutoStatus): number => (d.running ? 0 : (d.retry?.waiting ?? 0));

/** A finished run's identity: a new key is a run this page has not reflected yet. */
export const runKey = (r: AutoRun) => `${r.scan_run_id}|${r.finished ?? ""}`;

/** Is there a finished run to reflect? */
export const finishedRun = (d: AutoStatus | undefined): AutoRun | null =>
  d && !d.running && d.last && d.last.state !== "running" ? d.last : null;
