/**
 * The News & Learning test data (invented names only), kept as JSON so the mocked Playwright spec reads the same shapes
 * (`e2e/tests/fixtures/news/`). The shapes and key order are the old answers (`services/news.py::view`,
 * `weekly_review`, `refresh_status`, `services/news_sources.py::view`):
 * - `news.json`: eight stories in every state — an early catch with an outcome proposal and a settled disagreement, a
 *   late one whose proposal was rejected, a miss with a backcast and no audit, an unreviewed possible miss with an audit
 *   and an open disagreement, a curated historical case, a minor UNKNOWN story without a summary, a fund story (not
 *   relevant) and one noise story (counted, never listed); two themes; a partial last run;
 * - `news_empty.json`: an empty data folder;
 * - `news_weekly.json` / `news_weekly_empty.json`: the weekly review of that week / of an empty folder;
 * - `news_sources.json`: the sources view for each window ("30" | "90" | "180" | "all"): six sources (a Munich and a
 *   Europe-wide feed, a declining UK feed, the Swiss deal ticker reused from Deal Flow, a probation feed and an external
 *   benchmark); the 30-day window has too little overlap, so most purposes are COLLECTING DATA;
 * - `news_refresh_status.json`: the refresh status after a partial run, after a failed one, and before any run (the job
 *   is idle in each);
 * - `news_writes.json`: the old answers of the three writes (028b) — a confirm, a repeated decision after a confirm
 *   (`already`), a reject, a not-enough, the prefilled miss audit and an added signal.
 */
import emptyJson from "./news_empty.json";
import fullJson from "./news.json";
import refreshJson from "./news_refresh_status.json";
import sourcesJson from "./news_sources.json";
import weeklyEmptyJson from "./news_weekly_empty.json";
import weeklyJson from "./news_weekly.json";
import writesJson from "./news_writes.json";
import type { NewsPayload, RefreshStatus, SourcesPayload, Weekly, Window } from "../model/types";

export const news = (): NewsPayload => structuredClone(fullJson) as unknown as NewsPayload;
export const emptyNews = (): NewsPayload => structuredClone(emptyJson) as unknown as NewsPayload;
export const weekly = (): Weekly => structuredClone(weeklyJson) as Weekly;
export const emptyWeekly = (): Weekly => structuredClone(weeklyEmptyJson) as Weekly;
export const sources = (window: Window = "90"): SourcesPayload => structuredClone(sourcesJson[window]) as unknown as SourcesPayload;
export type RefreshCase = keyof typeof refreshJson;
export const refreshStatus = (c: RefreshCase = "partial"): RefreshStatus => structuredClone(refreshJson[c]) as unknown as RefreshStatus;

export type WriteCase = keyof typeof writesJson;
export const writeAnswer = (c: WriteCase): Record<string, unknown> => structuredClone(writesJson[c]);

/** The old write endpoints, the new write and refresh paths and the dropped Scout Bridge calls (every request that writes,
 *  or would have). */
export const WRITE_PATHS =
  /\/api\/(news_(outcome|audit_miss|backcast|backcast_job|refresh|sources_evaluate)\b|news\/(outcome|audit_miss|backcast|refresh|sources\/evaluate)\b|bridge_create\b)/;
