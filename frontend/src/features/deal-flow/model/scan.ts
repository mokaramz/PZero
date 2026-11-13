/**
 * The Deal Flow scan on the page (review 034a): Find New Candidates, its polling, the finish toast, the per-source
 * report and the scan history, ported from the old `features/inbox/` (`FindBar`, `ScanReport`, `ScanHistory`). The ONE
 * place the scan's paths and texts live. The paths are new, the bodies the old ones:
 *
 * - `POST deal-flow/find {days}` → the old `start_scan` answer: `{started}`, or `{running, done, total, note}` when a
 *   scan is already going (the page then shows its progress).
 * - `GET deal-flow/find_status` → `{running, done, total, rows, result, error, started}`, polled every 1.2 s while a
 *   scan runs (also one started elsewhere, e.g. by the runner, before the page was opened).
 * - `GET deal-flow/scan_history?n=` → `{scans, total, pipeline_label}`, read only when the history is opened.
 * - The inbox carries `report`, `last_run` and `last_summary`, from the latest run.
 *
 * Two declared additions: the intake's refusals (`refused` in the summary and on a report row, the reason in the
 * row's note) are shown in the row and in the finish toast; and machine triage does NOT run after the scan yet (it
 * arrives with the triage port), so the page says so where the old post-scan triage status sat, and neither reads
 * nor refreshes the triage status.
 */
import { plainText } from "@/lib/activity";
import type { FindStatus, ScanSummary } from "./types";

export const FIND = "deal-flow/find";
export const FIND_STATUS = "deal-flow/find_status";
export const SCAN_HISTORY = "deal-flow/scan_history";

/** The old poll pace while a scan runs. */
export const POLL_MS = 1200;
/** The scan history's page size (the old one). */
export const HISTORY_N = 10;

/** What a finished scan makes stale: the inbox (candidates, report, summary), the sources' runtime state, the history,
 *  System health and the runner's catch-up (the old list was inbox, sources, scan_history and triage_auto). */
export const SCAN_FINISHED_INVALIDATES = ["deal-flow/inbox", "sources", SCAN_HISTORY, "system_health", "catchup"] as const;

/** The old activity label of `find` ("Scanning sources"). */
export const FIND_LABEL = "Scanning sources";
export const ALREADY_RUNNING = "Scan already running — showing progress";
/** Declared (034a d): where the old post-scan machine-triage status sat. */
export const TRIAGE_LATER = "Machine triage arrives with the triage port.";

export const scanIcon = (s: string) => (s === "ok" ? "✓" : s === "off" ? "·" : "✕");

/** The intake's refusals, in plain words ("2 refused by the intake"); empty when there are none. */
export const refusedText = (n?: number | null) => (n && n > 0 ? `${n} refused by the intake` : "");

/** The old finish toast, plus the refusals when there are any. */
export function finishToast(r: NonNullable<FindStatus["result"]>): string {
  const refused = refusedText(r.refused);
  return `${r.new} genuinely new (${r.pre_company_new} pre-company) · ${r.baseline} baseline · ${r.noise} noise · ${r.known_skipped || 0} already known · ${r.known_pipeline || 0} existing pipeline${refused ? ` · ${refused}` : ""}`;
}

/** The old toast when the scan stopped. */
export const stoppedToast = (error: string) => `Scan stopped: ${plainText(error)} — nothing was half-saved; start it again when ready`;

/** "Scanning 2 / 3…" on the button while a scan runs. */
export const scanningLabel = (fs?: Pick<FindStatus, "done" | "total">) => `Scanning ${fs?.done ?? 0} / ${fs?.total ?? 0}…`;

/** The merged count of the old ledger and history. */
export const mergedOf = (s: ScanSummary) => (s.merged_cross_source || 0) + (s.merged_into_existing || 0);
