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
 * Nothing on the page writes: the outcome decisions, miss audits and early signals arrive with 028b
 * (`news/outcome`, `news/audit_miss`, `news/backcast`), the refresh and the source evaluation with 028c (`news/refresh`,
 * `news/sources/evaluate`). Their controls stay visible and disabled with a reason (./model/deferred). The old Scout
 * Bridge job spec (`news_backcast_job`) is gone with the bridge.
 */
import { useApi } from "@/lib/hooks";
import type { NewsPayload, RefreshStatus, SourcesPayload, Weekly, Window } from "./model/types";

export const NEWS = "news";
export const WEEKLY = "news/weekly";
export const SOURCES = "news/sources";
export const REFRESH_STATUS = "news/refresh_status";

export const useNews = () => useApi<NewsPayload>(NEWS, undefined, { staleTime: 60_000 });

export const useNewsWeekly = () => useApi<Weekly>(WEEKLY);

export const useNewsSources = (window: Window) => useApi<SourcesPayload>(SOURCES, { window }, { staleTime: 60_000 });

/** One read: the job is always idle in 028a, so there is nothing to poll. */
export const useRefreshStatus = () => useApi<RefreshStatus>(REFRESH_STATUS);
