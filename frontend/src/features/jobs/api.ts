/**
 * The background-jobs runner (review 032c) — the ONE place its paths live. The old paths and bodies:
 *
 * - `GET catchup` → the old `scheduler.status()`: `{running, queue, current, done, enabled, plan, lock, runners, ...}`.
 *   `queue` holds the labels of the jobs this run takes, `current` the label of the one running now, `done` one row per
 *   finished job; `runners` is the per-source overlay of the imported records and the new ones; `lock` is the real
 *   runner lock `{held, source, pid, since, alive, suspect}`. The banner polls it: every 2.5 s while a run is going,
 *   every 60 s otherwise, and not at all when the server has no such endpoint (404).
 * - `POST catchup_run {only?: string[]}` → `{started: true}`, or `{started: false, reason}` ("already running", or the
 *   live import has not run yet). The page always sends `only`: the overdue jobs the runner can run (never a job the
 *   server marks `ported: false`). It refreshes `catchup`, `system_health` and `system_health_overview`, and its toast
 *   is the old "Running overdue jobs in the background"; a run that did not start says why.
 */
import { isMissingEndpoint } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";

export const CATCHUP = "catchup";
export const CATCHUP_RUN = "catchup_run";
/** What a run makes stale (the old list). */
export const RUN_INVALIDATES = [CATCHUP, "system_health", "system_health_overview"];

export const POLL_RUNNING_MS = 2500;
export const POLL_IDLE_MS = 60_000;

export type Done = { job?: string; label: string; ok: boolean; note: string; outcome?: string; seconds?: number | null; at?: string; source?: string; error?: string };
export type CatchUpLock = { held: boolean; source?: string; pid?: number | null; since?: string; alive?: boolean; suspect?: boolean; age_h?: number | null };
export type CatchUp = {
  running: boolean;
  queue: string[];
  current: string | null;
  done: Done[];
  enabled: boolean;
  started?: string | null;
  finished?: string | null;
  plan?: unknown[];
  lock?: CatchUpLock | { deferred: string };
  runners?: Record<string, unknown>;
};

export type RunBody = { only?: string[] };
export type RunAnswer = { started: boolean; reason?: string; queue?: string[] };

/** The old toast, and the reason when the server did not start a run. */
export const RUN_STARTED = "Running overdue jobs in the background";
export const notStarted = (reason?: string) => `Not started — ${reason || "the server gave no reason"}.`;

/** The catch-up status, polled while the app is open. */
export function useCatchUp() {
  return useApi<CatchUp>(CATCHUP, undefined, {
    staleTime: 0,
    retry: (failures, error) => !isMissingEndpoint(error) && failures < 1,
    refetchInterval: (s) => (isMissingEndpoint(s.state.error) ? false : s.state.data?.running ? POLL_RUNNING_MS : POLL_IDLE_MS),
  });
}

/** "Run overdue now": `POST catchup_run {only}`. */
export function useRunOverdue() {
  return useAction<RunBody, RunAnswer>(CATCHUP_RUN, {
    invalidates: RUN_INVALIDATES,
    success: (r) => (r.started === false ? notStarted(r.reason) : RUN_STARTED),
  });
}
