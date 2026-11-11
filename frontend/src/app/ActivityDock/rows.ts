import type { ActionItem, ActionState } from "@/lib/activity";

/** A server job as `/api/activity` reports it. */
export type Job = { id: string; label: string; state: ActionState; detail: string; link?: string; finished_at?: string };
export type Activity = { running: number; jobs: Job[] };

/** One dock row: a server job (`job:…`) or a click of this browser (`c:…`). */
export type DockRow = { key: string; state: ActionState; text: string; detail?: string; link?: string; at: number; dismiss: () => void };

export const ICON: Record<ActionState, string> = { RUNNING: "⏳", COMPLETE: "✓", PARTIAL: "⚠", FAILED: "✕" };
export const WORD: Record<ActionState, string> = { RUNNING: "running", COMPLETE: "complete", PARTIAL: "partial", FAILED: "failed" };
/** a routine success stays in the compact dock for a minute (always in the expanded list) */
export const COMPLETE_MS = 60_000;

const ORDER: Record<ActionState, number> = { RUNNING: 0, FAILED: 1, PARTIAL: 2, COMPLETE: 3 };
const SUMMARY_ORDER: ActionState[] = ["RUNNING", "FAILED", "PARTIAL", "COMPLETE"];

/** "2026-11-11 10:00:00" → epoch ms (0 when unknown). */
const ts = (s?: string) => (s ? new Date(s.replace(" ", "T")).getTime() || 0 : 0);

export function isJobRow(row: DockRow): boolean {
  return row.key.startsWith("job");
}

/**
 * Every row, most important first (running · failed · partial · complete, then newest), and the COMPACT subset shown
 * when the dock is collapsed (completions older than a minute drop out of it).
 */
export function buildRows({
  jobs,
  mine,
  now,
  dismissedJobs,
  dismissMine,
}: {
  jobs: Job[];
  mine: ActionItem[];
  now: number;
  /** keys of server-job rows the operator dismissed (added to on dismiss) */
  dismissedJobs: Set<string>;
  dismissMine: (id: number) => void;
}): { rows: DockRow[]; compact: DockRow[] } {
  const rows: DockRow[] = [];
  for (const j of jobs) {
    const key = `job:${j.id}:${j.finished_at ?? "now"}`;
    if (dismissedJobs.has(key)) continue;
    rows.push({
      key,
      state: j.state,
      text: `${j.label} — ${j.state === "RUNNING" ? j.detail : `${WORD[j.state]} · ${j.detail}`}`,
      link: j.link,
      at: j.state === "RUNNING" ? now : ts(j.finished_at),
      dismiss: () => dismissedJobs.add(key),
    });
  }
  for (const x of mine) {
    // once a background job is listed by the server, its own row (real stage) replaces the client's "started" note
    if (jobs.length && x.state !== "RUNNING" && /runs in the background/.test(x.detail ?? "")) continue;
    rows.push({
      key: `c:${x.id}`,
      state: x.state,
      text: x.state === "RUNNING" ? `${x.label}…` : `${x.label} — ${WORD[x.state]}`,
      detail: x.detail,
      at: x.at,
      dismiss: () => dismissMine(x.id),
    });
  }
  rows.sort((a, b) => ORDER[a.state] - ORDER[b.state] || b.at - a.at);
  const compact = rows.filter((r) => r.state !== "COMPLETE" || now - r.at < COMPLETE_MS);
  return { rows, compact };
}

/** "⏳ 1 running   ✕ 2 failed" — counts of the compact rows, in importance order. */
export function summarize(compact: DockRow[]): string {
  const count = (s: ActionState) => compact.filter((r) => r.state === s).length;
  return SUMMARY_ORDER.filter((s) => count(s))
    .map((s) => `${ICON[s]} ${count(s)} ${WORD[s]}`)
    .join("   ");
}
