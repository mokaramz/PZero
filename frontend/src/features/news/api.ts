/**
 * The News & Learning endpoints (review 028a, the read side) — the ONE place their paths live. The answers are the old
 * ones under new paths, each a read in one read-only transaction:
 * - `GET news` → the old `GET /api/news` body (same keys, same order). The curated cases are seeded in memory only
 *   (decision a);
 * - `GET news/weekly` → the old `GET /api/news_weekly` (`weekly_review(record=False)`);
 * - `GET news/sources?window=30|90|180|all` → the old `GET /api/news_sources` (computed live; anything else is 90);
 * - `GET news/refresh_status` → the old `GET /api/news_refresh_status`. No refresh runs here (028c), so `job.running`
 *   is false: the status is read once, never polled.
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
 * The refresh and the source evaluation arrive with 028c (`news/refresh`, `news/sources/evaluate`); their controls stay
 * visible and disabled with a reason (./model/deferred). The old Scout Bridge job spec (`news_backcast_job`) is gone with
 * the bridge.
 */
import { useAction, useApi } from "@/lib/hooks";
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

/** The Validation page's read (its ledger gains a row on a confirm or a miss audit). */
export const VALIDATION = "validation";
/** What a write makes stale: the News read, plus Validation's when a Validation row was written. */
export const NEWS_KEYS = [NEWS, SOURCES]; // the Sources windows read the same stories, outcomes and audits (Codex H-253)
export const NEWS_AND_VALIDATION_KEYS = [NEWS, SOURCES, VALIDATION];
// every outcome decision re-reads Validation too, as the old page did (only a confirm writes a Validation row)
const OUTCOME_KEYS = NEWS_AND_VALIDATION_KEYS;

export const useNews = () => useApi<NewsPayload>(NEWS, undefined, { staleTime: 60_000 });

export const useNewsWeekly = () => useApi<Weekly>(WEEKLY);

export const useNewsSources = (window: Window) => useApi<SourcesPayload>(SOURCES, { window }, { staleTime: 60_000 });

/** One read: the job is always idle in 028a, so there is nothing to poll. */
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
