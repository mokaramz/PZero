/**
 * The News & Learning endpoints (review 028a, the read side) — the ONE place their paths live. The answers are the old
 * ones under new paths, each a read in one read-only transaction:
 * - `GET news` → the old `GET /api/news` body (same keys, same order). The curated cases are seeded in memory only
 *   (decision a);
 * - `GET news/weekly` → the old `GET /api/news_weekly` (`weekly_review(record=False)`);
 * - `GET news/sources?window=30|90|180|all` → the old `GET /api/news_sources` (computed live; anything else is 90);
 * - `GET news/refresh_status` → the old `GET /api/news_refresh_status`. The run executes inside its request (028c,
 *   decision e), so the status is read once and again when a run returns, never polled.
 *
 * The writes (028b), the old bodies and answers under new paths; a refusal is a 400 `{ok: false, error}` with the old
 * text, shown as the failure toast:
 * - `POST news/outcome {event_id, decision}` → the appended action line `{ok, kind, event_id, decision, at[, outcome_id]}`;
 *   once the latest decision is a confirm, `{ok, already: true, ...that confirmation}` (nothing written);
 * - `POST news/audit_miss {event_id}` → `{ok, audit}` (the Validation miss audit, prefilled by the server);
 * - `POST news/backcast {date, text, url, family, kind, event_id}` → `{ok, signal}`.
 * Every write refreshes `news`, as before; a confirm and a miss audit write a Validation row, so they also refresh
 * `validation`. The toasts and activity labels are the old ones (./model/writes).
 *
 * The runs (028c), the old bodies (`{}`), each answering once it has finished:
 * - `POST news/refresh` → the old `{started, run_id, **refresh_status}` with `job.running` false;
 * - `POST news/sources/evaluate` → `{ok, evaluated_at}`.
 * A 409 (another run holds the lock, or nothing is imported yet) is "not started" with the server's text, as the old
 * `{started: false, reason}`; a 503 (the run's deadline) is the failure toast with the server's text. While the request is
 * in flight the page shows the old running state. The old Scout Bridge job spec (`news_backcast_job`) is gone with the
 * bridge.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { actions, friendlyError } from "@/lib/activity";
import { ApiError, post } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import { EVALUATED, isNotStarted, refreshDone, RUN_LABEL, type EvaluateAnswer, type NotStarted, type RefreshAnswer } from "./model/refresh";
import type { NewsPayload, RefreshStatus, SourcesPayload, Weekly, Window } from "./model/types";
import {
  LABEL,
  SUCCESS,
  type AuditMissAnswer,
  type AuditMissBody,
  type OutcomeAnswer,
  type OutcomeBody,
  type SignalAnswer,
  type SignalBody,
} from "./model/writes";

export const NEWS = "news";
export const WEEKLY = "news/weekly";
export const SOURCES = "news/sources";
export const REFRESH_STATUS = "news/refresh_status";
export const OUTCOME = "news/outcome";
export const AUDIT_MISS = "news/audit_miss";
export const BACKCAST = "news/backcast";
export const REFRESH = "news/refresh";
export const EVALUATE = "news/sources/evaluate";

/** The Validation page's read (its ledger gains a row on a confirm or a miss audit). */
export const VALIDATION = "validation";
/** What a write makes stale: the News read, plus Validation's when a Validation row was written. */
export const NEWS_KEYS = [NEWS, SOURCES]; // the Sources windows read the same stories, outcomes and audits (Codex H-253)
export const NEWS_AND_VALIDATION_KEYS = [NEWS, SOURCES, VALIDATION];
// every outcome decision re-reads Validation too, as the old page did (only a confirm writes a Validation row)
const OUTCOME_KEYS = NEWS_AND_VALIDATION_KEYS;
/** What a finished refresh makes stale: the stories, the status, every Sources window, the weekly review (the old page
 *  re-read it too) and Validation (its News block reads the stories). */
export const REFRESH_KEYS = [NEWS, REFRESH_STATUS, SOURCES, WEEKLY, VALIDATION];
/** What a finished evaluation makes stale: the stories, the status and every Sources window. */
export const EVALUATE_KEYS = [NEWS, REFRESH_STATUS, SOURCES];

export const useNews = () => useApi<NewsPayload>(NEWS, undefined, { staleTime: 60_000 });

export const useNewsWeekly = () => useApi<Weekly>(WEEKLY);

export const useNewsSources = (window: Window) => useApi<SourcesPayload>(SOURCES, { window }, { staleTime: 60_000 });

/** One read, and again when a run returns (the run finishes inside its request, so there is nothing to poll). */
export const useRefreshStatus = () => useApi<RefreshStatus>(REFRESH_STATUS);

/** "Confirm outcome": records a Validation outcome (or answers the earlier confirmation). */
export const useConfirmOutcome = () =>
  useAction<OutcomeBody, OutcomeAnswer>(OUTCOME, {
    invalidates: OUTCOME_KEYS,
    success: SUCCESS.outcome,
    label: LABEL.outcome,
  });

/** "Reject" / "Not enough evidence": an action line only, so only the News read is stale. */
export const useDecideOutcome = () =>
  useAction<OutcomeBody, OutcomeAnswer>(OUTCOME, {
    invalidates: OUTCOME_KEYS,
    success: SUCCESS.outcome,
    label: LABEL.outcome,
  });

export const useAuditMiss = () =>
  useAction<AuditMissBody, AuditMissAnswer>(AUDIT_MISS, {
    invalidates: NEWS_AND_VALIDATION_KEYS,
    success: SUCCESS.audit,
    label: LABEL.audit,
  });

export const useAddSignal = () =>
  useAction<SignalBody, SignalAnswer>(BACKCAST, {
    invalidates: NEWS_KEYS,
    success: SUCCESS.signal,
    label: LABEL.signal,
  });

/* ------------------------------------------------------------------ the runs (028c) */

/** The run's POST; a 409 is "not started" with the server's text (nothing ran), every other refusal throws. */
async function postRun<T>(path: string): Promise<T | NotStarted> {
  try {
    return await post<T>(path, {});
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) return { started: false, reason: e.message };
    throw e;
  }
}

/** A run's own refusal (the 503 of its deadline) is operator-readable as it stands; anything else in plain words. */
const runError = (e: Error) => (e instanceof ApiError && e.status === 503 ? e.message : friendlyError(e.message, (e as { status?: number }).status));

/**
 * A News run: one POST, acknowledged in Background activity at the click; `isPending` is the running state. A finished
 * run re-reads `keys` (every params of each) before it settles; "not started" re-reads nothing and is PARTIAL; a failure
 * is the old failure toast. `toast` false keeps the outcome inline (the refresh line shows it, as the old page did).
 */
function useNewsRun<T>(path: string, opts: { label: string; keys: string[]; done: (r: T) => string; toast: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation<T | NotStarted, Error, void, { act: number }>({
    mutationFn: () => postRun<T>(path),
    onMutate: () => ({ act: actions.start(opts.label) }),
    onSuccess: async (r, _v, ctx) => {
      if (isNotStarted(r)) {
        if (ctx) actions.finish(ctx.act, "PARTIAL", r.reason);
        if (opts.toast) toast.show(r.reason, "info");
        return;
      }
      await Promise.all(opts.keys.map((k) => qc.invalidateQueries({ queryKey: [k] })));
      void qc.invalidateQueries({ queryKey: ["activity"] });
      const message = opts.done(r);
      if (ctx) actions.finish(ctx.act, "COMPLETE", message);
      if (opts.toast) toast.show(message, "ok");
    },
    onError: (e, _v, ctx) => {
      const message = runError(e);
      if (ctx) actions.finish(ctx.act, "FAILED", message);
      toast.show(`✕ ${opts.label} failed — ${message}`, "error");
    },
  });
}

/** "Refresh news": the whole run inside the request; its outcome is the refresh line, read again when it returns. */
export const useRefreshNews = () => useNewsRun<RefreshAnswer>(REFRESH, { label: RUN_LABEL.refresh, keys: REFRESH_KEYS, done: refreshDone, toast: false });

/** "Re-measure now": the source evaluation alone. */
export const useEvaluateSources = () =>
  useNewsRun<EvaluateAnswer>(EVALUATE, { label: RUN_LABEL.evaluate, keys: EVALUATE_KEYS, done: () => EVALUATED, toast: true });
