import { describe, expect, it } from "vitest";

import { activeSources, ago, attention, groupOf, jobMatrix, lanes, lastDays, modelSuccess, sourceFamilies, spendSeries, stateTone, worst } from "./dashboard";
import type { Health, Overview, Run } from "./types";

const NOW = new Date("2026-11-10T15:30:00");

function health(p: Partial<Health> = {}): Health {
  return {
    at: "2026-11-10T15:30:00",
    verdict: "FYI — EXTERNAL LIMITATIONS",
    issues: [],
    sources: {
      sources: [
        { id: "a", name: "Kestrel Wire", url: "", state: "FAILING", last_ok: "2026-10-22", failures_in_row: 3, last_useful_discovery: "", candidates: 92, noise_rate: 0, early_share: 0, last_error: "HTTP Error 403", repair: { cause: "refuses automated access", suggestion: "no bypass", external: true } },
        { id: "b", name: "Healthy", url: "", state: "HEALTHY", last_ok: "2026-11-10", failures_in_row: 0, last_useful_discovery: "", candidates: 1, noise_rate: 0, early_share: 0, last_error: "" },
        { id: "c", name: "Off", url: "", state: "DISABLED", last_ok: null, failures_in_row: 0, last_useful_discovery: "", candidates: 0, noise_rate: 0, early_share: 0, last_error: "" },
      ],
      counts: { FAILING: 1, HEALTHY: 1, DISABLED: 1 },
      rule: "",
      stale_days: 30,
    },
    coverage: { available: false },
    triage_pending: 0,
    research: {},
    watch: { companies: 0, open_triggers: 0, failing_checks: { deferred: "The watch sensors are not ported yet." } },
    jobs: [
      { id: "triage_compression", label: "Triage queue compression", interval_h: 6, last_ok: "2026-11-10T14:47:00", next_due: "2026-11-10T20:47:00", overdue: false, state: "ok", last_note: "routed 3", outcome: "completed" },
      { id: "news_refresh", label: "News refresh", interval_h: 24, last_ok: "2026-11-10T15:23:00", next_due: "2026-11-11T15:23:00", overdue: false, state: "ok", last_note: "PARTIAL", outcome: "partial" },
    ],
    overdue: 0,
    spend: { day: 0.002, week: 0.016, month: 0.2, limits: { daily_usd: 1, weekly_usd: 5, monthly_usd: 25 }, kill_switch: null },
    providers: [{ role: "CHEAP", provider: "inventa", model: "inventa/brisk-flash-1", enabled: true, key: true }],
    last_scan: "2026-11-08T19:09:14",
    validation: { snapshots: 0, last_snapshot: null, data_issues: 0 },
    news: { last_run: null, events: 0, backcasts_pending: 0, usd_total: 0, sources: { feeds_healthy: 8, feeds_failing: ["Kestrel Wire"] } },
    ...p,
  };
}

function overview(p: Partial<Overview> = {}): Overview {
  return {
    at: "2026-11-10T15:30:00",
    jobs: { days: 30, runs: [], outcomes_recorded_since: null },
    models: { rows: [], spend_by_day: {} },
    pipeline: { inbox: { new: 1019 }, routing: { counts: { NEEDS_MOHAMED: 0, BACKGROUND_RESEARCH: 129 }, at: null }, conviction: { new: 7, contacted: 2, dropped: 1 }, manager_sent: 0 },
    backups: { deferred: "Backups arrive with the hardening port." },
    integrity: { deferred: "Integrity checks arrive with the hardening port." },
    releases: { deferred: "Releases arrive with the hardening port." },
    ...p,
  };
}
const run = (at: string, job: string, state: string): Run => ({ at, job, label: job, state, seconds: 1, note: "", source: "background" });

describe("issues and status", () => {
  it("uses the backend group; an older payload falls back by level", () => {
    expect(groupOf({ level: "info", what: "x", do: "", group: "ext" })).toBe("ext");
    expect(groupOf({ level: "warn", what: "x", do: "" })).toBe("need");
    expect(groupOf({ level: "info", what: "x", do: "" })).toBe("info");
  });
  it("run states map to status shapes; a failed run is never green", () => {
    expect(["completed", "no_findings", "partial", "budget_blocked", "failed", "interrupted", "skipped"].map(stateTone)).toEqual(["ok", "ok", "lim", "lim", "bad", "bad", "unk"]);
  });
  it("relative times", () => {
    expect(ago("2026-11-10T15:20:00", NOW)).toBe("10 min ago");
    expect(ago("2026-11-09T13:30:00", NOW)).toBe("26 h ago");
    expect(ago("2026-11-10T15:29:40", NOW)).toBe("just now");
    expect(ago("2026-11-01T15:30:00", NOW)).toBe("9 days ago");
    expect(ago(null, NOW)).toBe("never");
    expect(ago("not a date", NOW)).toBe("never");
  });
});

describe("job matrix", () => {
  const jobs = [{ id: "news_refresh", label: "News refresh" }];
  const runs = [run("2026-11-09T21:45:58", "news_refresh", "partial"), run("2026-11-09T08:00:00", "news_refresh", "completed"), run("2026-10-01T08:00:00", "news_refresh", "failed")];
  it("30 d: one cell per day, the worst run wins, runs outside the window are dropped", () => {
    const m = jobMatrix(jobs, runs, "30d", NOW);
    const filled = m.rows[0].cells.filter((c) => c.length);
    expect(filled).toHaveLength(1);
    expect(filled[0]).toHaveLength(2);
    expect(worst(filled[0]).state).toBe("partial");
  });
  it("24 h: 24 hourly cells; an older run is not shown", () => {
    const m = jobMatrix(jobs, runs, "24h", NOW);
    expect(m.rows[0].cells).toHaveLength(24);
    expect(m.rows[0].cells.flat().map((r) => r.state)).toEqual(["partial"]);
  });
  it("7 d: 28 six-hour cells", () => {
    const m = jobMatrix(jobs, runs, "7d", NOW);
    expect(m.rows[0].cells).toHaveLength(28);
    expect(m.rows[0].cells.flat().map((r) => r.state).sort()).toEqual(["completed", "partial"]);
  });
  it("a run after now is not shown", () => {
    expect(jobMatrix(jobs, [run("2026-11-10T16:00:00", "news_refresh", "failed")], "24h", NOW).rows[0].cells.flat()).toEqual([]);
  });
  it("30 d cells are calendar days, also across the daylight-saving change", () => {
    const m = jobMatrix(jobs, [run("2026-10-25T23:30:00", "news_refresh", "completed")], "30d", NOW);
    const i = m.rows[0].cells.findIndex((c) => c.length);
    expect(lastDays(NOW, 30)[i]).toBe("2026-10-25");
  });
  it("a job with no run in the window has only empty cells (no invented history)", () => {
    expect(jobMatrix([{ id: "x", label: "x" }], runs, "7d", NOW).rows[0].cells.every((c) => c.length === 0)).toBe(true);
  });
});

describe("models and spend", () => {
  it("daily spend series: real values, models ordered by spend, totals add up", () => {
    const days = lastDays(NOW, 3);
    const s = spendSeries({ [days[0]]: { a: 0.01 }, [days[2]]: { a: 0.02, b: 0.05 } }, days);
    expect(s.models).toEqual(["b", "a"]);
    expect(s.totals.map((t) => Number(t.toFixed(3)))).toEqual([0.01, 0, 0.07]);
    expect(Number(s.total.toFixed(3))).toBe(0.08);
  });
  it("7-day success counts provider calls only; no calls = no rate (not 100 %)", () => {
    expect(modelSuccess(overview()).rate).toBeNull();
    expect(modelSuccess(undefined)).toEqual({ ok: 0, calls: 0, rate: null, used: 0 });
    const o = overview({
      models: {
        rows: [
          { model: "a", provider: "p", roles: [], calls: 10, ok: 9, errors: 1, cache_hits: 5, blocked: 1, usd: 0, last_ok: "", last_error: "", error_kinds: {}, calls_7d: 4, ok_7d: 3, p50_ms_7d: null },
          { model: "b", provider: "p", roles: [], calls: 2, ok: 2, errors: 0, cache_hits: 0, blocked: 0, usd: 0, last_ok: "", last_error: "", error_kinds: {}, calls_7d: 0, ok_7d: 0, p50_ms_7d: null },
        ],
        spend_by_day: {},
      },
    });
    expect(modelSuccess(o)).toEqual({ ok: 3, calls: 4, rate: 0.75, used: 1 });
  });
});

describe("sources", () => {
  it("families, attention list and active count; low volume is not a failure", () => {
    const h = health();
    expect(sourceFamilies(h).dealFlow).toEqual({ healthy: 1, failing: 1, never: 0, disabled: 1, total: 3 });
    expect(sourceFamilies(h).news).toEqual({ healthy: 8, failing: 1 });
    expect(attention(h).map((s) => s.name)).toEqual(["Kestrel Wire"]);
    expect(activeSources(h)).toBe(2);
  });
  it("a news sources error hides the news family", () => {
    expect(sourceFamilies(health({ news: { last_run: null, events: 0, backcasts_pending: 0, usd_total: 0, sources: { error: "temporarily unavailable" } } })).news).toBeNull();
  });
});

describe("pipeline", () => {
  it("the Deal Flow lane only: the Scout 00 and Native Scout lanes are retired (decision c)", () => {
    const L = lanes(health(), overview());
    expect(L.map((l) => l.name)).toEqual(["Deal Flow"]);
    const ids = L.flatMap((l) => l.nodes.map((n) => n.id));
    expect(ids).toEqual(["df-scan", "df-triage", "df-queue", "df-you", "df-conviction"]);
    expect(ids.some((id) => id.startsWith("s00") || id.startsWith("nat"))).toBe(false);
  });
  it("every human decision is a marked human node and the lane ends with you", () => {
    const L = lanes(health(), overview());
    expect(L.flatMap((l) => l.nodes.filter((n) => n.human).map((n) => n.id))).toEqual(["df-you", "df-conviction"]);
    for (const l of L) expect(l.nodes[l.nodes.length - 1].human).toBe(true);
  });
  it("reads real states: a completed job, the routes, Manager sends", () => {
    const n = Object.fromEntries(lanes(health(), overview()).flatMap((l) => l.nodes).map((x) => [x.id, x]));
    expect(n["df-queue"].mark).toEqual(["ok", "On schedule"]);
    expect(n["df-queue"].fact).toBe("0 routed to you · 129 researching");
    expect(n["df-you"].fact).toBe("1019 undecided candidates");
    expect(n["df-you"].mark).toEqual(["lim", "Your pace"]);
    expect(n["df-conviction"].fact).toBe("10 in Conviction · 0 sent");
    expect(n["df-triage"].mark).toEqual(["ok", "Clear"]);
  });
  it("job marks: failing, overdue, budget-blocked, partial, not run yet, and pending triage never says retrying", () => {
    const j = (id: string, x: Partial<Health["jobs"][number]>) => ({ id, label: id, interval_h: 1, last_ok: "2026-11-01T00:00:00", next_due: "now", overdue: false, state: "ok", last_note: "", ...x });
    const mark = (x: Partial<Health["jobs"][number]>) =>
      lanes(health({ jobs: [j("deal_flow_scan", x)] }), overview())[0].nodes[0].mark;
    expect(mark({ state: "failed" })).toEqual(["bad", "Failing"]);
    expect(mark({ state: "interrupted" })).toEqual(["bad", "Failing"]);
    expect(mark({ fails_in_row: 2 })).toEqual(["bad", "Failing"]);
    expect(mark({ overdue: true })).toEqual(["lim", "Overdue"]);
    expect(mark({ outcome: "budget_blocked" })).toEqual(["lim", "Budget-blocked"]);
    expect(mark({ outcome: "partial" })).toEqual(["lim", "Partial"]);
    expect(mark({ last_ok: null })).toEqual(["unk", "Not run yet"]);
    const triage = lanes(health({ triage_pending: 4 }), overview())[0].nodes[1];
    expect(triage.mark).toEqual(["lim", "Pending"]);
    expect(triage.fact).toBe("4 pending");
  });
  it("missing telemetry is shown as no data, never as healthy", () => {
    const n = Object.fromEntries(lanes(health({ jobs: [], last_scan: "" }), overview()).flatMap((l) => l.nodes).map((x) => [x.id, x]));
    expect(n["df-scan"].mark).toEqual(["unk", "No data"]);
    expect(n["df-scan"].fact).toBe("weekly · last never");
    expect(n["df-scan"].details).toEqual([["Job", "not configured"]]);
    expect(n["df-queue"].mark).toEqual(["unk", "No data"]);
  });
});
