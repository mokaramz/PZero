/** System Health dashboard logic — pure functions over the two health payloads. Nothing here invents a number: every
 *  value is read from the payload; absent telemetry stays absent (null / "no data").
 *
 *  Ported verbatim from the old `features/health/dashboard.ts` (review 032a), except `lanes`: the retired Scout 00 and
 *  Native Scout lanes are removed with their payload keys (decision c), so the pipeline is the Deal Flow lane; and
 *  the machine-triage node no longer says "Retrying" while no runner retries it (revision 2); a step whose job the
 *  runner cannot run yet (`ported: false`, 032c) says "Not ported yet" in place of "Overdue" or its next run. */
import { isPortedJob, JOB_NOT_PORTED } from "./jobs";
import type { Health, Issue, IssueGroup, Overview, Run } from "./types";

export type Tone = "ok" | "lim" | "warn" | "bad" | "unk";
export type Mark = [Tone, string];

export const GROUPS: Array<[IssueGroup, string, string]> = [
  ["need", "Needs your action", "only real decisions or interventions"],
  ["auto", "Handled automatically", "retried or recovered by Project Zero"],
  ["ext", "External limitations", "third parties, outside Project Zero's control"],
  ["info", "Informational", "no impact on your work"],
];

/** Group of an issue (served by the backend; older payloads fall back to level). */
export const groupOf = (i: Issue): IssueGroup => i.group ?? (i.level === "warn" ? "need" : "info");

export const STATUS_TONE: Record<string, Tone> = { ok: "ok", limited: "lim", action: "warn", degraded: "warn", unknown: "unk" };

// ------------------------------------------------------------------------------------------------ time helpers
export const T = (iso?: string | null): Date | null => (iso ? new Date(String(iso).replace(" ", "T")) : null);
export function ago(iso: string | null | undefined, now: Date): string {
  const t = T(iso);
  if (!t || Number.isNaN(t.getTime())) return "never";
  const m = (now.getTime() - t.getTime()) / 60_000;
  if (m < 1) return "just now";
  if (m < 60) return `${Math.round(m)} min ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} days ago`;
}
export const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export function lastDays(now: Date, n: number): string[] {
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(now);
    d.setDate(d.getDate() - (n - 1 - i));
    return isoDay(d);
  });
}
export const usd = (v: number | null | undefined, d = 2) => `$${Number(v || 0).toFixed(d)}`;
export const shortModel = (m: string) => m.split("/").pop() || m;

// ------------------------------------------------------------------------------------------------ job matrix
export type Range = "24h" | "7d" | "30d";
export const RANGES: Record<Range, { n: number; ms: number }> = { "24h": { n: 24, ms: 3_600_000 }, "7d": { n: 28, ms: 6 * 3_600_000 }, "30d": { n: 30, ms: 86_400_000 } };
/** Worst-first: a period shows its worst run. */
export const RANK: Record<string, number> = { failed: 7, interrupted: 6, budget_blocked: 5, partial: 4, waiting_external: 3, skipped: 2, completed: 1, no_findings: 0 };
export const STATE_LABEL: Record<string, string> = {
  completed: "Completed",
  no_findings: "Completed — nothing new",
  partial: "Partial",
  failed: "Failed",
  interrupted: "Interrupted",
  budget_blocked: "Blocked by budget",
  waiting_external: "Waiting on external dependency",
  skipped: "Skipped (another run active)",
};
export const stateTone = (s: string): Tone => (s === "failed" || s === "interrupted" ? "bad" : s === "partial" || s === "budget_blocked" || s === "waiting_external" ? "lim" : s === "skipped" ? "unk" : "ok");

export type MatrixRow = { id: string; label: string; cells: Run[][] };
export function jobMatrix(jobs: Array<{ id: string; label: string }>, runs: Run[], range: Range, now: Date): { start: number; rows: MatrixRow[] } {
  const R = RANGES[range];
  // buckets align to the clock: whole hours (24 h), 6-hour blocks (7 d), calendar days (30 d) — the last one holds now
  const b = new Date(now);
  b.setMinutes(0, 0, 0);
  if (range === "7d") b.setHours(b.getHours() - (b.getHours() % 6));
  if (range === "30d") b.setHours(0);
  const end = now.getTime();
  const start = b.getTime() - (R.n - 1) * R.ms;
  const days = range === "30d" ? lastDays(now, R.n) : null; // calendar days (daylight-saving safe)
  const rows = jobs.map((j) => {
    const cells: Run[][] = Array.from({ length: R.n }, () => []);
    for (const r of runs) {
      if (r.job !== j.id) continue;
      const d = T(r.at);
      const t = d?.getTime();
      if (d == null || t == null || t > end) continue;
      const idx = days ? days.indexOf(isoDay(d)) : t < start ? -1 : Math.min(R.n - 1, Math.floor((t - start) / R.ms));
      if (idx >= 0) cells[idx].push(r);
    }
    return { id: j.id, label: j.label, cells };
  });
  return { start, rows };
}
export const worst = (cell: Run[]): Run => cell.reduce((a, r) => ((RANK[r.state] ?? 1) > (RANK[a.state] ?? 1) ? r : a));

// ------------------------------------------------------------------------------------------------ spend
export function spendSeries(byDay: Record<string, Record<string, number>>, days: string[]) {
  const models = [...new Set(days.flatMap((d) => Object.keys(byDay[d] ?? {})))].sort(
    (a, b) => days.reduce((s, d) => s + (byDay[d]?.[b] ?? 0), 0) - days.reduce((s, d) => s + (byDay[d]?.[a] ?? 0), 0),
  );
  const values = days.map((d) => models.map((m) => byDay[d]?.[m] ?? 0));
  const totals = values.map((v) => v.reduce((a, b) => a + b, 0));
  return { models, values, totals, total: totals.reduce((a, b) => a + b, 0) };
}

/** Success over the last 7 days across models (provider calls only — cache hits and budget blocks excluded). */
export function modelSuccess(o: Overview | undefined): { ok: number; calls: number; rate: number | null; used: number } {
  const rows = o?.models.rows ?? [];
  const ok = rows.reduce((a, m) => a + m.ok_7d, 0);
  const calls = rows.reduce((a, m) => a + m.calls_7d, 0);
  return { ok, calls, rate: calls ? ok / calls : null, used: rows.filter((m) => m.calls_7d > 0).length };
}

// ------------------------------------------------------------------------------------------------ sources
export function sourceFamilies(h: Health) {
  const c = h.sources.counts;
  const ns = h.news?.sources;
  return {
    dealFlow: { healthy: c.HEALTHY ?? 0, failing: (c.FAILING ?? 0) + (c.DEGRADED ?? 0) + (c.STALE ?? 0), never: c.NEVER_SUCCESSFUL ?? 0, disabled: (c.DISABLED ?? 0) + (c.NEVER_RUN ?? 0), total: h.sources.sources.length },
    news: ns && !ns.error ? { healthy: ns.feeds_healthy ?? 0, failing: ns.feeds_failing?.length ?? 0 } : null,
  };
}
export const attention = (h: Health) => h.sources.sources.filter((s) => s.repair || s.state === "FAILING" || s.state === "NEVER_SUCCESSFUL");
export const activeSources = (h: Health) => h.sources.sources.length - (h.sources.counts.DISABLED ?? 0);

// ------------------------------------------------------------------------------------------------ pipeline (the real architecture)
export type PNode = { id: string; name: string; fact: string; mark: Mark; human?: boolean; external?: boolean; details: Array<[string, string]>; link?: string };
export type Lane = { id: string; name: string; sub: string; nodes: PNode[] };

const fmtT = (iso?: string | null, withDate = true) =>
  iso ? T(iso)!.toLocaleString("en-GB", withDate ? { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" } : { hour: "2-digit", minute: "2-digit" }) : "—";

/** The pipeline lanes. The old Scout 00 and Native Scout lanes are retired with their keys (decision c). */
export function lanes(h: Health, o: Overview): Lane[] {
  const job = Object.fromEntries(h.jobs.map((j) => [j.id, j]));
  const jm = (id: string): Mark => {
    const j = job[id];
    if (!j) return ["unk", "No data"];
    if (j.state === "failed" || j.state === "interrupted" || (j.fails_in_row ?? 0) >= 2) return ["bad", "Failing"];
    if (!isPortedJob(j)) return ["unk", "Not ported yet"]; // 032c: the runner never runs it; its imported history stays
    if (j.overdue) return ["lim", "Overdue"];
    if (j.outcome === "budget_blocked") return ["lim", "Budget-blocked"];
    if (j.outcome === "partial") return ["lim", "Partial"];
    if (!j.last_ok) return ["unk", "Not run yet"];
    return ["ok", "On schedule"];
  };
  const jd = (id: string): Array<[string, string]> => {
    const j = job[id];
    return j ? [["Job", j.label], ["Last run", fmtT(j.last_ok)], ["Result", j.last_note || "—"], ["Next due", isPortedJob(j) ? fmtT(j.next_due) : JOB_NOT_PORTED]] : [["Job", "not configured"]];
  };
  const p = o.pipeline;
  const rc = p.routing.counts ?? {};
  const conv = Object.values(p.conviction).reduce((a, b) => a + b, 0);
  return [
    {
      id: "df",
      name: "Deal Flow",
      sub: "sources → decision",
      nodes: [
        { id: "df-scan", name: "Source scan", fact: `weekly · last ${h.last_scan ? fmtT(h.last_scan).split(",")[0] : "never"}`, mark: jm("deal_flow_scan"), details: jd("deal_flow_scan") },
        // old mark: "Retrying" — no runner retries the triage until 032c (revision 2), so the pending items wait
        { id: "df-triage", name: "Machine triage", fact: `${h.triage_pending} pending`, mark: h.triage_pending ? ["lim", "Pending"] : ["ok", "Clear"],
          details: [["Waiting for triage", String(h.triage_pending)], ["Retry job", job.triage_retry?.last_note ?? "—"], ["Configured models", h.providers.filter((x) => x.enabled).map((x) => `${x.role}: ${shortModel(x.model)}`).join(" · ") || "none"], ["Note", "Machine triage proposes only; it never decides."]] },
        { id: "df-queue", name: "Queue compression", fact: `${rc.NEEDS_MOHAMED ?? 0} routed to you · ${rc.BACKGROUND_RESEARCH ?? 0} researching`, mark: jm("triage_compression"),
          details: [["Routes", Object.entries(rc).map(([k, v]) => `${v} ${k.toLowerCase().replace(/_/g, " ").replace("needs mohamed", "routed to you")}`).join(" · ") || "—"], ["At", fmtT(p.routing.at)]] },
        { id: "df-you", name: "You: review", fact: `${p.inbox.new ?? 0} undecided candidates`, mark: rc.NEEDS_MOHAMED ? ["warn", "Needs you"] : ["lim", "Your pace"], human: true, link: "/deal-flow",
          details: [["Undecided candidates", String(p.inbox.new ?? 0)], ["Routed to you now", String(rc.NEEDS_MOHAMED ?? 0)], ["Note", "Every Deal Flow decision is yours."]] },
        { id: "df-conviction", name: "Conviction → Manager", fact: `${conv} in Conviction · ${p.manager_sent} sent`, mark: ["ok", "Stable"], human: true, link: "/conviction",
          details: [["Conviction", Object.entries(p.conviction).map(([k, v]) => `${v} ${k}`).join(" · ") || "none"], ["Sent to the Manager", String(p.manager_sent)], ["Gate", "Only you send a company to the Manager."]] },
      ],
    },
  ];
}
