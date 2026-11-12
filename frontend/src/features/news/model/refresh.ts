/**
 * The refresh line's pure logic, ported line for line from the old `features/news/NewsRefresh.tsx`. In 028a no refresh
 * runs (it arrives with 028c): the status is read once and its job is idle, so the line shows the last run's outcome.
 */
import { plainSourceProblem } from "@/lib/activity";
import type { NewsRun, RefreshStatus } from "./types";

/** The run's stages, in plain words (shown while a run is active). */
export const STAGE: Record<string, string> = {
  starting: "starting",
  fetching: "checking sources",
  ingesting: "sorting articles into stories",
  watch: "checking your WATCH companies",
  cards: "writing story explanations",
  metrics: "updating source statistics",
};
export const fmtTs = (ts?: string) => (ts ? ts.replace("T", " ").slice(0, 16) : "");

/** "deutsche-startups.de: HTTPError: HTTP Error 429: …" → plain English (the technical text stays out of the page). */
export function plainFailure(line: string): string {
  const [name, ...rest] = line.split(": ");
  return `${name} — ${plainSourceProblem(rest.join(": "))}`;
}

export type Summary = { tone: "ok" | "warn" | "fail"; title: string; detail: string };

/** The three outcomes the operator must be able to tell apart: failed · no new stories · new stories. */
export function refreshSummary(r: NewsRun): Summary {
  const failed = r.sources_failed?.length ?? 0;
  const checked = r.feeds_checked ?? r.sources_ok + failed;
  const when = fmtTs(r.completed_at || r.at);
  if (r.status === "interrupted") return { tone: "fail", title: "Last refresh was interrupted", detail: `${r.note ?? "The app stopped during the refresh."} (${when})` };
  if (r.status === "failed") return { tone: "fail", title: "News refresh failed", detail: `${failed}/${checked} sources could not be fetched · ${when}` };
  const head = `${checked} sources checked${failed ? ` (${failed} failed)` : ""} · ${r.items} articles fetched`;
  const stale = r.stale_feeds?.length ? ` · not publishing lately: ${r.stale_feeds.join(", ")}` : "";
  const paused = r.cooldown?.length ? ` · paused (asked us to slow down): ${r.cooldown.join(", ")}` : "";
  // a PARTIAL always says what happens next and whether Mohamed must act
  const next = failed ? " · stories from the working sources are saved; the failed source(s) are tried again at the next refresh — nothing to do" : "";
  const tail = `${r.duplicates_skipped} already known${r.events_total !== undefined ? ` · ${r.events_total} stories stored` : ""} · ${when}${r.duration_s ? ` · ${Math.round(r.duration_s)} s` : ""}${stale}${paused}${next}`;
  if (!r.new && !r.merged)
    return { tone: failed ? "warn" : "ok", title: failed ? "Refresh partly done — no new stories" : "Refresh complete — no new stories", detail: `${head} · ${tail}` };
  return {
    tone: failed ? "warn" : "ok",
    title: failed ? "Refresh partly done" : "Refresh complete",
    detail: `${head} · ${r.new} new stor${r.new === 1 ? "y" : "ies"}${r.material_new !== undefined ? ` (${r.material_new} material)` : ""} · ${r.merged} new article(s) on existing stories · ${tail}`,
  };
}

/** "checking sources (4/10) · 3 s" — only while a run is active. */
export function progressText(job: RefreshStatus["job"]): string {
  const stage = STAGE[job.stage ?? ""] ?? job.stage ?? "";
  const feeds = job.stage === "fetching" && job.feeds_total ? ` (${job.feeds_done ?? 0}/${job.feeds_total})` : "";
  const elapsed = job.elapsed_s ? ` · ${job.elapsed_s} s` : "";
  return `${stage}${feeds}${elapsed}`;
}

/** After a failed or interrupted attempt the line also says when the last good refresh was. */
export const showsLastOk = (last: NewsRun | null | undefined) => !!last?.status && ["failed", "interrupted"].includes(last.status);
export const lastOkText = (s: RefreshStatus) => `Last successful refresh: ${s.last_ok ? fmtTs(s.last_ok.completed_at || s.last_ok.at) : "none yet"}.`;
