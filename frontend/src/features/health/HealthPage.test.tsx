import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ALL_ITEMS } from "@/app/nav";
import { JOBS_SNAPSHOT, NOT_PORTED } from "./model/deferred";
import type { Health, Overview } from "./model/types";
import { emptyHealth, emptyOverview, health, jobsOnly, overview } from "./test/fixtures";
import { fakeServer, renderPage } from "./test/server";

/** The phrases that would promise a mechanism the new app does not have while no runner exists (revision 2). */
const FORBIDDEN = ["retries automatically", "kept for retry", "run again when due", "starts them immediately", "next background trigger", "let catch-up run it", "asleep"];
const RUNNER_NOT_PORTED = /runner is not ported|until the runner is ported/;

const tick = () => new Promise((r) => setTimeout(r, 20));
const pageText = () => document.body.textContent ?? "";
const dialog = () => screen.getByRole("dialog");
const runOverdue = () => screen.queryAllByRole("button", { name: "Run overdue now" });

async function opened(routes: Parameters<typeof fakeServer>[0] = {}) {
  const server = fakeServer(routes);
  const view = renderPage();
  await screen.findByRole("heading", { level: 1, name: "System health" });
  return { server, ...view };
}

/** The page with the overview arrived (the pipeline is drawn). */
async function settled(routes: Parameters<typeof fakeServer>[0] = {}) {
  const r = await opened(routes);
  await waitFor(() => expect(document.querySelector("[data-node]")).not.toBeNull());
  return r;
}

/** Open a diagnostics disclosure (one is open at a time). */
async function expand(testId: string) {
  const d = screen.getByTestId(testId) as HTMLDetailsElement;
  if (!d.open) fireEvent.click(d.querySelector("summary")!);
  await waitFor(() => expect((screen.getByTestId(testId) as HTMLDetailsElement).open).toBe(true));
  return screen.getByTestId(testId);
}

/** A deferred control: in place and named, aria-disabled, described by a VISIBLE note with its reason; a click, Enter
 *  or Space sends nothing and goes nowhere. */
async function expectDeferred(btn: HTMLElement, reason: string, server: ReturnType<typeof fakeServer>) {
  expect(btn).toHaveAttribute("aria-disabled", "true");
  expect(btn).toHaveAttribute("data-deferred");
  expect(btn).not.toBeDisabled(); // focusable, named, inert
  expect(btn).toHaveAttribute("title", reason);
  const id = btn.getAttribute("aria-describedby");
  expect(id).toBeTruthy();
  const note = document.getElementById(id!)!;
  expect(note.textContent).toBe(reason);
  expect(note).not.toHaveClass("sr-only");
  expect(note).toBeVisible();
  expect(btn).toHaveAccessibleDescription(reason);
  const before = server.calls.length;
  fireEvent.click(btn);
  fireEvent.keyDown(btn, { key: "Enter" });
  fireEvent.keyDown(btn, { key: " " });
  fireEvent.keyUp(btn, { key: " " });
  await tick();
  expect(server.calls.length).toBe(before);
  expect(screen.queryByTestId("landed")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("System health — reads, loading and errors", () => {
  it("is a ported nav view at /health", () => {
    expect(ALL_ITEMS.find((i) => i.legacyView === "health")).toMatchObject({ path: "/health", label: "System health", page: expect.anything() });
  });

  it("reads the two GETs once each and writes nothing; never the 032b reads, even with every panel open", async () => {
    const { server } = await settled();
    for (const id of ["health-sources", "health-hardening", "health-jobs", "health-build-d"]) await expand(id);
    await tick();
    expect([...server.gets()].sort()).toEqual(["/api/system_health", "/api/system_health_overview"]);
    expect(server.writes()).toEqual([]);
  });

  it("loading: the page says Checking… until system_health arrives", async () => {
    fakeServer();
    renderPage();
    expect(screen.getByText("Checking…")).toBeInTheDocument();
    await screen.findByRole("heading", { level: 1, name: "System health" });
  });

  it("a failed system_health read is the page's error, with a retry that reads it again", async () => {
    let n = 0;
    const server = fakeServer({ health: () => (n++ === 0 ? { status: 500, body: { ok: false, error: "boom" } } : health()) });
    renderPage();
    const retry = await screen.findByRole("button", { name: /retry/i });
    expect(screen.queryByRole("heading", { level: 1, name: "System health" })).toBeNull();
    fireEvent.click(retry);
    await screen.findByRole("heading", { level: 1, name: "System health" });
    expect(server.gets().filter((p) => p === "/api/system_health")).toHaveLength(2);
  });

  it("while the overview loads, its panels say so", async () => {
    await opened({ holdOverview: true });
    expect(screen.getByText("Loading the pipeline…")).toBeInTheDocument();
    expect(screen.getByText("Loading job history…")).toBeInTheDocument();
    expect(screen.getByText("Loading spend…")).toBeInTheDocument();
    expect(within(screen.getByTestId("health-backup-status")).getByText("Loading…")).toBeInTheDocument();
    expect(screen.getAllByTestId("health-kpi")[4]).toHaveTextContent("Loading");
  });

  it("a failed overview shows its error above the panels; the panels say unavailable", async () => {
    await opened({ overview: () => ({ status: 500, body: { ok: false, error: "overview down" } }) });
    await screen.findByText("Pipeline data unavailable right now.");
    expect(screen.getAllByRole("button", { name: /retry/i }).length).toBeGreaterThan(0);
    expect(screen.getByText("History unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Spend history unavailable.")).toBeInTheDocument();
    expect(within(screen.getByTestId("health-backup-status")).getByText("Unavailable.")).toBeInTheDocument();
    expect(screen.getByText("No model call recorded yet.")).toBeInTheDocument();
  });

  it("Refresh re-reads both GETs and nothing else", async () => {
    const { server } = await settled();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(server.gets()).toHaveLength(4));
    expect([...server.gets()].sort()).toEqual(["/api/system_health", "/api/system_health", "/api/system_health_overview", "/api/system_health_overview"]);
    expect(server.writes()).toEqual([]);
  });
});

describe("System health — the answer first", () => {
  it("the header: title, purpose, the latest job report's age and the deferred releases reason", async () => {
    await settled();
    expect(screen.getByText("Infrastructure, intelligence pipelines, model spending and operational issues.")).toBeInTheDocument();
    const fresh = screen.getByTestId("health-freshness");
    expect(fresh).toHaveTextContent("latest job report 3 days ago");
    expect(within(fresh).getByTestId("health-release-reason")).toHaveTextContent(/^Releases arrive with the hardening port\.$/);
    expect(fresh).not.toHaveTextContent("release ");
  });

  it("the verdict renders the server's label and sentence as sent (jobs_unrun: Action required, 1 item)", async () => {
    await settled();
    const v = screen.getByTestId("health-verdict");
    expect(v).toHaveTextContent("Action required");
    expect(screen.getByTestId("health-action").textContent).toBe(health().status!.sentence);
    expect(screen.getByTestId("health-action")).toHaveTextContent(RUNNER_NOT_PORTED);
  });

  it("jobs_only: Status unknown with the runner sentence; the empty snapshot: no timestamp", async () => {
    await settled({ health: jobsOnly });
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("Status unknown");
    expect(screen.getByTestId("health-action").textContent).toBe(jobsOnly().status!.sentence);
    expect(screen.getByTestId("health-action")).toHaveTextContent(RUNNER_NOT_PORTED);
    expect(within(screen.getByTestId("issues-need")).getByText("✓ Nothing needs you right now.")).toBeInTheDocument();
  });

  it("the empty snapshot: no job report, no run, no model call, every job never run", async () => {
    await settled({ health: emptyHealth, overview: emptyOverview });
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("Status unknown");
    expect(screen.getByTestId("health-action")).toHaveTextContent("the imported snapshot contains no job report");
    expect(screen.getByTestId("health-action").textContent).not.toMatch(/\d{4}-\d{2}-\d{2}/);
    expect(screen.getByTestId("health-freshness")).toHaveTextContent("latest job report none yet");
    expect(screen.getByText(/^History unavailable — no scheduled run is recorded in the imported snapshot\./)).toBeInTheDocument();
    expect(screen.getByText(/No paid model call in the last 30 days/)).toBeInTheDocument();
    expect(screen.getByText("No model call recorded yet.")).toBeInTheDocument();
    expect(within(screen.getByTestId("health-attention")).getByText("No source needs attention.")).toBeInTheDocument();
    const n = (id: string) => document.querySelector(`[data-node="${id}"]`)!;
    expect(n("df-scan")).toHaveTextContent("weekly · last never");
    expect(n("df-scan")).toHaveTextContent("Overdue"); // never run, so due now
    expect(n("df-you")).toHaveTextContent("0 undecided candidates");
    const kpis = screen.getAllByTestId("health-kpi");
    expect(kpis[0]).toHaveTextContent("11 overdue");
    expect(kpis[2]).toHaveTextContent("No calls in 7 d");
    expect(screen.getAllByTestId("health-run-overdue")).toHaveLength(2);
  });

  it("an older server without `status` falls back to Status unknown", async () => {
    await settled({
      health: () => {
        const h = health();
        delete h.status;
        return h;
      },
    });
    expect(screen.getByTestId("health-verdict")).toHaveTextContent("Status unknown");
    expect(screen.getByTestId("health-action")).toHaveTextContent("This server does not report an overall status yet.");
  });
});

describe("System health — KPIs and the pipeline", () => {
  it("five KPIs in the old order without the retired Scouting one", async () => {
    await settled();
    const kpis = screen.getAllByTestId("health-kpi");
    expect(kpis.map((k) => k.firstElementChild?.textContent)).toEqual(["Background jobs", "Data sources", "AI models", "Model spend · month", "Backups & integrity"]);
    expect(kpis[0]).toHaveTextContent("3 failed");
    expect(kpis[0]).toHaveTextContent("11 jobs");
    expect(kpis[0]).toHaveTextContent("19 runs / 30 d · 3 failed · 1 partial");
    expect(kpis[1]).toHaveTextContent("2 need a look");
    expect(kpis[1]).toHaveTextContent("2 / 4 active");
    expect(kpis[1]).toHaveTextContent("1 disabled by you · news 6/7 feeds");
    expect(kpis[2]).toHaveTextContent("Responding");
    expect(kpis[2]).toHaveTextContent("95.2% ok · 7 d");
    expect(kpis[2]).toHaveTextContent("62 calls · 2 models used");
    expect(kpis[3]).toHaveTextContent("Paid AI off");
    expect(kpis[3]).toHaveTextContent("$1.87 / $25");
    expect(kpis[3]).not.toHaveTextContent("Grok");
    expect(kpis[4]).toHaveTextContent("Not ported yet");
    expect(kpis[4]).toHaveTextContent("— since backup");
    expect(kpis[4]).toHaveTextContent("Backups arrive with the hardening port.");
    expect(kpis[4]).toHaveTextContent("The integrity check arrives with the hardening port.");
  });

  it("a KPI scrolls to its panel", async () => {
    await settled();
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    vi.stubGlobal("matchMedia", () => ({ matches: true }));
    fireEvent.click(screen.getAllByTestId("health-kpi")[1]);
    expect(scroll).toHaveBeenCalledWith({ behavior: "auto", block: "start" });
  });

  it("the pipeline is the Deal Flow lane only: no Scout 00 or Native Scout lane", async () => {
    await settled();
    const pipe = screen.getByTestId("health-pipeline");
    expect(pipe).toHaveTextContent("Deal Flowsources → decision");
    expect(Array.from(pipe.querySelectorAll("[data-node]")).map((n) => n.getAttribute("data-node"))).toEqual(["df-scan", "df-triage", "df-queue", "df-you", "df-conviction"]);
    expect(pageText()).not.toMatch(/Scout 00|Native Scout|Grok|search bridge/i);
    const n = (id: string) => pipe.querySelector(`[data-node="${id}"]`)!;
    expect(n("df-scan")).toHaveTextContent("On schedule");
    expect(n("df-triage")).toHaveTextContent("3 pending");
    expect(n("df-triage")).toHaveTextContent("Pending");
    expect(n("df-triage")).not.toHaveTextContent("Retrying");
    expect(n("df-queue")).toHaveTextContent("2 routed to you · 18 researching");
    expect(n("df-queue")).toHaveTextContent("Failing"); // the imported interrupted job
    expect(n("df-you")).toHaveTextContent("37 undecided candidates");
    expect(n("df-you")).toHaveTextContent("Needs you");
    expect(n("df-conviction")).toHaveTextContent("7 in Conviction · 1 sent");
  });

  it("a pipeline step opens the drawer; its link lands on the page; Escape closes", async () => {
    await settled();
    fireEvent.click(document.querySelector('[data-node="df-queue"]')!);
    expect(dialog()).toHaveAccessibleName("Queue compression");
    expect(screen.getByTestId("health-detail")).toHaveTextContent("Routes2 routed to you · 18 background research · 40 archive");
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(document.querySelector('[data-node="df-you"]')!);
    expect(screen.getByTestId("health-detail")).toHaveTextContent("Deal Flow · a human decision");
    fireEvent.click(within(dialog()).getByRole("link", { name: "Open deal flow →" }));
    expect(await screen.findByTestId("landed")).toHaveTextContent("/deal-flow");
  });
});

describe("System health — background jobs (the deferred runner: the imported snapshot)", () => {
  it("the matrix: one row per job, the range switches, the snapshot line next to the outcomes", async () => {
    await settled();
    const jobs = screen.getByTestId("health-job-history");
    expect(jobs.querySelectorAll("[data-job]")).toHaveLength(11);
    for (const r of ["24h", "7d", "30d"]) {
      fireEvent.click(within(jobs).getByRole("button", { name: r }));
      expect(within(jobs).getByRole("button", { name: r })).toHaveAttribute("aria-pressed", "true");
    }
    expect(within(jobs).getByTestId("health-jobs-snapshot").textContent).toBe(JOBS_SNAPSHOT);
    expect(jobs).toHaveTextContent('recorded only success or failure; "nothing new" and "partial" are distinguished from then on.');
    expect(jobs).toHaveTextContent("9 job(s) overdue.");
  });

  it("a period opens its runs: the recorded outcomes, no promised retry, the snapshot line", async () => {
    await settled();
    const cell = screen.getByTestId("job-matrix").querySelector('[data-job="event_scan"] button[data-state="failed"]') as HTMLElement;
    fireEvent.click(cell);
    expect(dialog()).toHaveAccessibleName("Event source scan");
    const d = screen.getByTestId("health-detail");
    expect(d).toHaveTextContent("Runs in this period (1)");
    expect(d).toHaveTextContent("Failures in a row2");
    expect(d).toHaveTextContent(`Retry${NOT_PORTED.runner}`);
    expect(d).toHaveTextContent("HTTP Error 503 from the event listing");
    expect(within(d).getByTestId("health-runs-snapshot").textContent).toBe(JOBS_SNAPSHOT);
    expect(d).toHaveTextContent("Work that did not complete is not run again until the background-job runner is ported");
    for (const p of [...FORBIDDEN, "runs again automatically", "kept for the next run"]) expect(d.textContent).not.toContain(p);
  });

  it("a completed period needs no retry", async () => {
    await settled();
    fireEvent.click(screen.getByTestId("job-matrix").querySelector('[data-job="validation_snapshot"] button[data-state]') as HTMLElement);
    expect(screen.getByTestId("health-detail")).toHaveTextContent("Retrynot needed");
    expect(screen.getByTestId("health-detail")).not.toHaveTextContent("Downstream effect");
  });

  it('the deferred runner lock: "Run overdue now" keeps both places, each disabled with its visible reason; nothing happens (the live runner: ./HealthRunner.test)', async () => {
    const { server } = await settled();
    const [inPanel, inGroup] = runOverdue();
    expect(runOverdue()).toHaveLength(2);
    expect(screen.getByTestId("health-job-history")).toContainElement(inPanel);
    expect(screen.getByTestId("issues-auto")).toContainElement(inGroup);
    for (const b of [inPanel, inGroup]) await expectDeferred(b, NOT_PORTED.runner, server);
    expect(screen.getAllByTestId("health-run-overdue-note").map((n) => n.textContent)).toEqual([NOT_PORTED.runner, NOT_PORTED.runner]);
  });

  it("no overdue job: no Run overdue now", async () => {
    await settled({
      health: () => {
        const h = health();
        h.overdue = 0;
        return h;
      },
    });
    expect(runOverdue()).toEqual([]);
  });
});

describe("System health — spend, models, sources, backups", () => {
  it("spend: the general budget chart and pool only; the Grok bridge chart and pool are gone", async () => {
    await settled();
    const spend = screen.getByTestId("health-spend");
    expect(within(spend).getByTestId("spend-chart")).toHaveAttribute("aria-label", "Daily model spend, last 30 days, total $0.555");
    expect(screen.queryByTestId("bridge-chart")).toBeNull();
    expect(screen.queryByTestId("pool-bridge")).toBeNull();
    const pool = screen.getByTestId("pool-general");
    expect(pool).toHaveTextContent("General model budget");
    expect(pool).toHaveTextContent("Paid model calls are switched off (PZ_AI_PAID).");
    expect(within(pool).getAllByRole("img").map((m) => m.getAttribute("aria-label"))).toEqual([
      "Today: $0.012 of $1.00",
      "Week: $0.214 of $5.00",
      "Month: $1.870 of $25.00",
    ]);
  });

  it("models: a row per model; a click or Enter opens its errors", async () => {
    await settled();
    const models = screen.getByTestId("health-models");
    const row = models.querySelector('[data-model="inventa/brisk-flash-1"]') as HTMLElement;
    expect(row).toHaveTextContent("brisk-flash-1");
    expect(row).toHaveTextContent("6 invalid, 3 rate limited");
    expect(models).toHaveTextContent("Configured roles: CHEAP brisk-flash-1 · STANDARD steady-pro-2 · PREMIUM off.");
    fireEvent.keyDown(row, { key: "Enter" });
    expect(dialog()).toHaveAccessibleName("brisk-flash-1");
    const d = screen.getByTestId("health-detail");
    expect(d).toHaveTextContent("6 × invalid — the model's answer failed validation; the item was kept");
    expect(d).toHaveTextContent("3 × rate_limited — the provider asked to slow down");
    expect(d.textContent).not.toContain("kept for retry");
    fireEvent.click(within(dialog()).getByRole("button", { name: "Close" }));
    fireEvent.click(models.querySelector('[data-model="inventa/steady-pro-2"]') as HTMLElement);
    expect(screen.getByTestId("health-detail")).toHaveTextContent("No errors recorded.");
  });

  it("sources: the problem rows keep their diagnosis; search filters; no repair research action", async () => {
    await settled();
    const rows = () => screen.queryAllByTestId("health-source-problem");
    expect(rows().map((r) => r.firstElementChild?.firstElementChild?.textContent)).toEqual(["Halden Patent Bulletin", "Kestrel Wire"]);
    expect(rows()[0]).toHaveTextContent("Fixable on the Project Zero side");
    expect(rows()[0]).toHaveTextContent("fetched but no items");
    expect(rows()[0]).toHaveTextContent("Look at it");
    expect(rows()[1]).toHaveTextContent("External access restriction");
    expect(rows()[1]).toHaveTextContent("HTTP Error 403");
    expect(rows()[1]).toHaveTextContent("None — handled safely");
    const find = screen.getByRole("textbox", { name: "Search sources needing attention" });
    fireEvent.change(find, { target: { value: "layout" } });
    expect(rows()).toHaveLength(1);
    fireEvent.change(find, { target: { value: "nothing like this" } });
    expect(screen.getByText("No source matches.")).toBeInTheDocument();
    fireEvent.change(find, { target: { value: "" } });
    fireEvent.click(rows()[0]);
    expect(dialog()).toHaveAccessibleName("Halden Patent Bulletin (weekly grants)");
    const d = screen.getByTestId("health-detail");
    expect(d).toHaveTextContent("In plain wordsthe page layout or feed format changed");
    expect(d).toHaveTextContent("What to doThe parser no longer finds entries");
    expect(d).toHaveTextContent("One of 4 active Deal Flow sources; the others keep working.");
    expect(d).toHaveTextContent("Project Zero never tries to get around an access restriction.");
    expect(within(d).queryAllByRole("button")).toEqual([]);
    expect(pageText()).not.toMatch(/repair research|Scout Bridge/i);
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.keyDown(rows()[1], { key: "Enter" });
    expect(screen.getByTestId("health-detail")).toHaveTextContent("External limitation — no action required");
  });

  it("backups, integrity and releases: their deferred reasons where the data was", async () => {
    await settled();
    const bk = screen.getByTestId("health-backup-status");
    expect(within(bk).getByTestId("health-backups-reason")).toHaveTextContent(/^Backups arrive with the hardening port\.$/);
    expect(within(bk).getByTestId("health-integrity-reason")).toHaveTextContent(/^The integrity check arrives with the hardening port\.$/);
    expect(within(bk).getByTestId("health-releases-reason")).toHaveTextContent(/^Releases arrive with the hardening port\.$/);
    expect(bk.querySelectorAll("[data-reason]")).toHaveLength(5);
    expect(bk).toHaveTextContent("Not ported yet");
    expect(screen.queryByTestId("backup-not-verified")).toBeNull();
  });

  it("when the 032b data arrives, it is drawn as before", async () => {
    const o = (): Overview => ({
      ...overview(),
      backups: {
        count: 2,
        latest: { name: "pz-2026-11-12.zip", bytes: 4_200_000, at: "2026-11-12T09:30:00", checksum: true, restore_ok: null, restore_at: null },
        last_verified: { name: "pz-2026-11-01.zip", bytes: 4_000_000, at: "2026-11-01T09:00:00", checksum: true, restore_ok: true, restore_at: "2026-11-02T10:00:00" },
        dir: "backups/",
      },
      integrity: { status: "warn", files_checked: 227, checked_at: "2026-11-13T08:00:00", issues: 2 },
      releases: [{ at: "2026-11-10T08:00:00", tag: "v2.4.0", commit: "abcdef1234" }],
    });
    await settled({ overview: o });
    const bk = screen.getByTestId("health-backup-status");
    expect(bk.querySelectorAll("[data-reason]")).toHaveLength(0);
    expect(bk).toHaveTextContent("24 h ago · 4.2 MB · checksum ✓");
    expect(bk).toHaveTextContent("pz-2026-11-01.zip restored and checked");
    expect(bk).toHaveTextContent("2 issue(s)");
    expect(bk).toHaveTextContent("227 files");
    expect(bk).toHaveTextContent("v2.4.0abcdef1");
    expect(screen.getByTestId("backup-not-verified")).toHaveTextContent("Latest backup not yet restore-tested.");
    expect(screen.getByTestId("health-freshness")).toHaveTextContent("release v2.4.0");
    expect(screen.getAllByTestId("health-kpi")[4]).toHaveTextContent("2 integrity issue(s)");
    expect(screen.getAllByTestId("health-kpi")[4]).toHaveTextContent("Last verified restore");
  });
});

describe("System health — operational issues", () => {
  it("each issue once, in the group the server sent; the reworded job guidance names the missing runner", async () => {
    await settled();
    const group = (g: string) => screen.getByTestId(`issues-${g}`);
    const items = (g: string) => within(group(g)).queryAllByTestId("health-issue");
    expect(items("need")).toHaveLength(1);
    expect(items("auto")).toHaveLength(0);
    expect(items("ext")).toHaveLength(1);
    expect(items("info")).toHaveLength(9);
    expect(group("need")).toHaveTextContent("Needs your action1");
    expect(group("auto")).toHaveTextContent("None.");
    expect(items("ext")[0]).toHaveTextContent("1 source(s) unavailable for external reasons (Kestrel Wire)");
    expect(items("ext")[0]).not.toHaveTextContent("handled safely, not bypassed");
    const jobItems = items("info").filter((i) => /background job|external dependency/.test(i.textContent ?? ""));
    expect(jobItems).toHaveLength(6);
    for (const i of jobItems) expect(i.lastElementChild).toHaveTextContent(RUNNER_NOT_PORTED);
    // no job in the "Handled automatically" group, and no sentence says a job is handled automatically
    expect(screen.getByTestId("health-action")).not.toHaveTextContent(/handled automatically/i);
  });

  it("an issue opens its detail", async () => {
    await settled();
    fireEvent.click(within(screen.getByTestId("issues-need")).getByTestId("health-issue"));
    expect(dialog()).toHaveAccessibleName("1 source(s) failing for a reason Project Zero can fix (parser / address)");
    const d = screen.getByTestId("health-detail");
    expect(d).toHaveTextContent("Needs your action");
    expect(d).toHaveTextContent("Severityneeds attention");
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(within(screen.getByTestId("issues-info")).getAllByTestId("health-issue")[0]);
    expect(screen.getByTestId("health-detail")).toHaveTextContent("Severityinformation only");
  });

  it("no text anywhere promises a mechanism the app does not have — with every diagnostics section open", async () => {
    await settled();
    const check = () => {
      for (const p of FORBIDDEN) expect(pageText(), p).not.toContain(p);
      expect(pageText()).not.toMatch(/catch up when the app opens|runs again automatically|kept for the next run|\(catch-up\)/);
    };
    check();
    for (const id of ["health-glance", "health-sources", "health-coverage", "health-jobs", "health-ai", "health-news", "health-hardening", "health-build-d"]) {
      await expand(id);
      check();
    }
  });
});

describe("System health — diagnostics", () => {
  it("every section is still here; one open at a time", async () => {
    await settled();
    for (const id of ["health-glance", "health-sources", "health-coverage", "health-jobs", "health-ai", "health-news", "health-hardening", "health-build-d"]) expect(screen.getByTestId(id)).toBeInTheDocument();
    await expand("health-jobs");
    await expand("health-ai");
    expect((screen.getByTestId("health-jobs") as HTMLDetailsElement).open).toBe(false);
  });

  it("at a glance, sources, coverage, models and budget, news", async () => {
    await settled();
    expect(await expand("health-glance")).toHaveTextContent("2/5healthy sources");
    expect(screen.getByTestId("health-glance")).toHaveTextContent("9overdue background jobs");
    expect(screen.getByTestId("health-glance")).toHaveTextContent("4research questions open");
    expect(await expand("health-sources")).toHaveTextContent("Health is about retrieval, not volume");
    expect(screen.getByTestId("health-sources")).toHaveTextContent("failing 2 · healthy 2 · disabled 1");
    const cov = await expand("health-coverage");
    expect(within(cov).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Ecosystem", "Talent", "Capital", "Events"]);
    expect(cov).toHaveTextContent("Valdmarkhealthypartialgap");
    expect(cov).toHaveTextContent("Port Elsinhealthyhealthyunknown");
    const ai = await expand("health-ai");
    expect(ai).toHaveTextContent("Caps stop paid calls automatically");
    expect(ai).toHaveTextContent("Paid model calls are switched off (PZ_AI_PAID).");
    expect(ai).toHaveTextContent("CHEAP: inventa · inventa/brisk-flash-1 key set");
    expect(ai).toHaveTextContent("PREMIUM: disabled");
    const news = await expand("health-news");
    expect(news).toHaveTextContent("Last refresh 2026-11-09 21:47 · PARTIAL · 6 feed(s) ok · 4 new event(s) · 5 duplicate article(s) collapsed · 318 events stored");
    expect(within(news).getByTestId("health-news-sources")).toHaveTextContent("6/8 healthy · failing: Kestrel Wire · on probation: Larkfield Daily");
  });

  it("background jobs: the snapshot line, the deferred runner lock, the imported runners and every job's recorded outcome", async () => {
    await settled();
    const jobs = await expand("health-jobs");
    expect(within(jobs).getByTestId("health-jobs-note").textContent).toBe(JOBS_SNAPSHOT);
    const runner = within(jobs).getByTestId("health-job-runner");
    expect(runner).toHaveTextContent("Job runner: The job runner lock is not ported yet: no runner is alive.");
    expect(runner.querySelector("[data-reason]")).toHaveTextContent("The job runner lock is not ported yet: no runner is alive.");
    expect(runner).toHaveTextContent("· last background run 2026-11-09 22:05 (completed) · last manual run 2026-11-06 10:03 (partial)");
    const items = within(jobs).getAllByTestId("health-job");
    expect(items).toHaveLength(11);
    expect(items[1]).toHaveTextContent("Deal Flow scan every 7 days · last ok 2026-11-08T19:09:14 · next 2026-11-15T19:09:14");
    expect(items[2]).toHaveTextContent("overdue");
    expect(items[2]).toHaveTextContent("failed");
    expect(items[2]).toHaveTextContent("fails 2× in a row");
    expect(items[2]).toHaveTextContent("HTTP Error 503 from the event listing");
    expect(items[4]).toHaveTextContent("partially completed");
    expect(items[8]).toHaveTextContent("interrupted");
    expect(jobs).not.toHaveTextContent("catch up");
  });

  it("build, self-check and WATCH checks show their deferred reasons", async () => {
    await settled();
    const b = await expand("health-build-d");
    expect(within(b).getByTestId("health-build")).toHaveTextContent(/^Running build: The build and stale-interface check is not ported yet\.$/);
    expect(within(b).getByTestId("health-selfcheck")).toHaveTextContent(/^Startup self-check: The startup self-check is not ported yet\.$/);
    expect(within(b).getByTestId("health-validation-data")).toHaveTextContent(
      "Validation data: 12 daily snapshot(s), last 2026-11-09, 2 data warning(s). WATCH: 3 company(ies), The watch sensors are not ported yet.",
    );
  });

  it("when build, self-check, the lock and the WATCH count arrive, they are drawn as before", async () => {
    await settled({
      health: (): Health => {
        const h = health();
        h.build = { version: "2.4.0", commit: "abc1234", started_at: "2026-11-13T08:00:00", ui_stale: false, note: "", frontend: { built_at: "2026-11-13T07:59:00", commit: "abc1234" } };
        h.selfcheck = { at: "2026-11-13T08:00:10", running: false, ok: 9, total: 10, degraded: [{ name: "news", why: "x", impact: "y", recovery: "z" }] };
        h.job_runner!.lock = { held: true, alive: false, source: "background", pid: 4242, since: "2026-11-13T07:00:00" };
        h.watch.failing_checks = 2;
        return h;
      },
    });
    const b = await expand("health-build-d");
    expect(within(b).getByTestId("health-build")).toHaveTextContent("Running build abc1234 (v2.4.0) · started 2026-11-13 08:00 · interface built 2026-11-13 07:59 from abc1234");
    expect(within(b).getByTestId("health-selfcheck")).toHaveTextContent("9/10 subsystems OK at 2026-11-13 08:00 · DEGRADED: news (see the issues above)");
    expect(within(b).getByTestId("health-validation-data")).toHaveTextContent("3 company(ies), 2 failing page check(s).");
    const jobs = await expand("health-jobs");
    expect(within(jobs).getByTestId("health-job-runner")).toHaveTextContent("busy — background (pid 4242) since 2026-11-13T07:00:00 · process gone, recovered on the next run");
    // a real lock is the live runner (032c): the snapshot line goes, "Run overdue now" is enabled
    expect(within(jobs).getByTestId("health-jobs-note").textContent).not.toBe(JOBS_SNAPSHOT);
    expect(screen.queryByTestId("health-jobs-snapshot")).toBeNull();
    for (const b of runOverdue()) expect(b).not.toHaveAttribute("aria-disabled");
  });

  it("data integrity & backups: the three 032b panels show their reason; Back up now and Test latest backup are deferred", async () => {
    const { server } = await settled();
    const h = await expand("health-hardening");
    for (const id of ["health-backups", "health-integrity", "health-governance"]) expect(within(h).getByTestId(id)).toHaveTextContent(NOT_PORTED.hardening);
    expect(within(h).getAllByRole("button").map((b) => b.textContent)).toEqual(["Back up now", "Test latest backup"]);
    for (const id of ["backup-now", "backup-test"]) await expectDeferred(within(h).getByTestId(id), NOT_PORTED.hardening, server);
    expect(within(h).getByTestId("backup-now").getAttribute("aria-describedby")).toBe(within(h).getByTestId("backup-reason").id);
  });

  it("new sources: the panel shows its reason; Look for new sources is deferred", async () => {
    const { server } = await settled();
    const s = await expand("health-sources");
    const panel = within(s).getByTestId("health-new-sources");
    expect(within(panel).getByTestId("new-sources-reason").textContent).toBe(NOT_PORTED.sourceNetwork);
    await expectDeferred(within(panel).getByRole("button", { name: "Look for new sources" }), NOT_PORTED.sourceNetwork, server);
    expect(within(panel).queryByTestId("new-source")).toBeNull();
  });
});
