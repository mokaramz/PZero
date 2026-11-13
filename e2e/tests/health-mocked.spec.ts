/**
 * System health (review 032a) — the old `health.spec.ts` checks (the plain-words verdict, the drill-down, the phone
 * layout), ported to the new page. The API is MOCKED with route interception, so no backend is needed: only the
 * frontend (`npm run dev` in frontend/, or PZ_BASE_URL). Every source, job note, model and city in fixtures/health/ is
 * invented (byte-identical copies of `frontend/src/features/health/test/*.json`).
 *
 * New here (revision 2): on the `jobs_unrun` payload the headline and every job item's guidance say the runner is not
 * ported, and NO text on the page promises a retry, a catch-up or an immediate run; "Run overdue now" is disabled in
 * both places with its visible reason, and a click, Enter or Space sends nothing. The deferred subsystems show their
 * reason; the retired Scout lanes, Grok bridge chart and repair research action are gone. Also: the drawer, Refresh
 * (the two GETs again) and no horizontal overflow at 1366, 1920, 390 and 150 %. Old checks of a model key's value are
 * not ported.
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test health-mocked
 */
import { expect, test, type Locator, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expand, expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures", "health");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (n: string): J => JSON.parse(readFileSync(resolve(FIX, n), "utf8"));

const RUNNER = "The background-job runner is not ported yet.";
const SNAPSHOT = "Background jobs are not ported yet: job state and history are the imported snapshot.";
const HARDENING = "Backups, integrity checks and model provenance arrive with the hardening port.";
const NETWORK = "The source network and its decisions arrive with the hardening port.";
const RUNNER_NOT_PORTED = /runner is not ported|until the runner is ported/;
const FORBIDDEN = ["retries automatically", "kept for retry", "run again when due", "starts them immediately", "next background trigger", "let catch-up run it", "asleep"];
const DIAGNOSTICS = ["health-glance", "health-sources", "health-coverage", "health-jobs", "health-ai", "health-news", "health-hardening", "health-build-d"];

/** Mock the two reads; anything else under /api answers 404 (the shell's not-ported reads are allowed by `watch`, any
 *  other 404 fails the test). Returns every API request, in order. */
async function mockApi(page: Page, opts: { health?: J; overview?: J } = {}) {
  const requested: Array<{ method: string; path: string }> = [];
  page.on("request", (r) => {
    if (!r.url().includes("/api/")) return;
    const u = new URL(r.url());
    requested.push({ method: r.method(), path: u.pathname + u.search });
  });
  await page.clock.setFixedTime(new Date(2026, 10, 13, 9, 30));
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/system_health(\?.*)?$/, (route) => route.fulfill({ json: opts.health ?? load("health_jobs_unrun.json") }));
  await page.route(/\/api\/system_health_overview(\?.*)?$/, (route) => route.fulfill({ json: opts.overview ?? load("overview.json") }));
  return {
    requested,
    gets: () => requested.filter((r) => r.method === "GET").map((r) => r.path),
    writes: () => requested.filter((r) => r.method !== "GET"),
    health: () => requested.filter((r) => r.path.startsWith("/api/system_health")),
  };
}

async function open(page: Page) {
  await page.goto("/health");
  await expect(page.getByRole("heading", { level: 1, name: "System health" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("health-pipeline").locator("[data-node]").first()).toBeVisible(); // the overview is there
}

/** The whole visible text of the page, `<details>` bodies included once opened. */
const text = (page: Page) => page.locator("body").innerText();

async function expectNoPromise(page: Page) {
  const t = await text(page);
  for (const p of FORBIDDEN) expect(t, p).not.toContain(p);
  expect(t).not.toMatch(/runs again automatically|kept for the next run|catch up when the app opens/);
}

/** Deferred: visible and named, aria-disabled, described by its VISIBLE reason; a click, Enter and Space change
 *  nothing (same URL, no request, no drawer). */
async function expectDeferred(page: Page, btn: Locator, reason: string, api: Awaited<ReturnType<typeof mockApi>>) {
  await expect(btn).toBeVisible();
  await expect(btn).toHaveAttribute("aria-disabled", "true");
  await expect(btn).toHaveAttribute("data-deferred", "");
  const id = await btn.getAttribute("aria-describedby");
  const note = page.locator(`[id="${id}"]`);
  await expect(note).toBeVisible();
  await expect(note).toHaveText(reason);
  await expect(btn).toHaveAccessibleDescription(reason);
  const before = api.requested.length;
  await btn.click({ force: true }); // aria-disabled: Playwright would wait for it to be enabled
  await btn.focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Space");
  await page.waitForTimeout(400);
  await expect(page).toHaveURL((u) => u.pathname === "/health" && u.search === "");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(api.requested.slice(before)).toEqual([]);
}

test.describe("System health — mocked API", () => {
  test("answers 'is Project Zero healthy?' in plain words, from the two GETs only", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    const verdict = page.getByTestId("health-verdict");
    await expect(verdict).toContainText("Action required");
    await expect(page.getByTestId("health-action")).toHaveText(load("health_jobs_unrun.json").status.sentence);
    // "Action required" only when the Needs-your-action group is not empty — and the reverse
    await expect(page.getByTestId("issues-need").getByTestId("health-issue")).toHaveCount(1);
    await expect(page.getByTestId("health-kpi")).toHaveCount(5);
    await expect(page.getByTestId("health-kpi").locator("span:first-child")).toHaveText(["Background jobs", "Data sources", "AI models", "Model spend · month", "Backups & integrity"]);
    await expand(page, "health-sources");
    await expect(page.getByTestId("health-sources")).toContainText("Health is about retrieval, not volume");
    await expand(page, "health-jobs");
    await expect(page.getByTestId("health-jobs")).toContainText("Deal Flow scan");
    await expand(page, "health-ai");
    await expect(page.getByTestId("health-ai")).toContainText("Caps stop paid calls automatically");
    await expect(page.getByTestId("health-jobs")).not.toHaveAttribute("open", ""); // one open at a time
    expect([...new Set(api.gets().filter((p) => p.startsWith("/api/system_health")))].sort()).toEqual(["/api/system_health", "/api/system_health_overview"]);
    expect(api.writes()).toEqual([]);
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });

  test("jobs_unrun: the headline and every job item's guidance say the runner is not ported; nothing promises a run", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await open(page);
    await expect(page.getByTestId("health-action")).toContainText(RUNNER_NOT_PORTED);
    const jobItems = page.getByTestId("health-issue").filter({ hasText: /background job|external dependency/ });
    await expect(jobItems).toHaveCount(6);
    for (const item of await jobItems.all()) await expect(item.locator("span").last()).toContainText(RUNNER_NOT_PORTED);
    // no job sits in "Handled automatically", and no sentence calls a job handled automatically
    await expect(page.getByTestId("issues-auto").getByTestId("health-issue")).toHaveCount(0);
    await expect(page.getByTestId("health-action")).not.toContainText(/handled automatically/i);
    await expect(page.getByTestId("health-jobs-snapshot")).toHaveText(SNAPSHOT);
    await expectNoPromise(page);
    for (const id of DIAGNOSTICS) {
      await expand(page, id);
      await expectNoPromise(page);
    }
    await expect(page.getByTestId("health-jobs-note")).toHaveCount(0); // closed again by the next one
    await expand(page, "health-jobs");
    await expect(page.getByTestId("health-jobs-note")).toHaveText(SNAPSHOT);
    await expect(page.getByTestId("health-job-runner")).toContainText("The job runner lock is not ported yet: no runner is alive.");
    // a job period's drawer: the recorded outcome, no promised retry
    await page.getByTestId("job-matrix").locator('[data-job="event_scan"] button[data-state="failed"]').last().click();
    const detail = page.getByTestId("health-detail");
    await expect(detail).toContainText("Runs in this period");
    await expect(detail).toContainText(RUNNER);
    await expect(detail).toContainText(SNAPSHOT);
    await expectNoPromise(page);
    await page.keyboard.press("Escape");
    w.expectClean();
  });

  test("jobs_only: Status unknown with the runner sentence; nothing needs you", async ({ page }) => {
    const w = watch(page);
    await mockApi(page, { health: load("health_jobs_only.json") });
    await open(page);
    await expect(page.getByTestId("health-verdict")).toContainText("Status unknown");
    await expect(page.getByTestId("health-action")).toContainText(RUNNER_NOT_PORTED);
    await expect(page.getByTestId("issues-need")).toContainText("Nothing needs you right now.");
    await expectNoPromise(page);
    w.expectClean();
  });

  test('"Run overdue now" is disabled in both places with its visible reason; a click, Enter and Space do nothing', async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    const buttons = page.getByRole("button", { name: "Run overdue now", exact: true });
    await expect(buttons).toHaveCount(2);
    await expect(page.getByTestId("health-job-history").getByRole("button", { name: "Run overdue now", exact: true })).toHaveCount(1);
    await expect(page.getByTestId("issues-auto").getByRole("button", { name: "Run overdue now", exact: true })).toHaveCount(1);
    for (const b of await buttons.all()) await expectDeferred(page, b, RUNNER, api);
    await expect(page.getByTestId("health-run-overdue-note")).toHaveText([RUNNER, RUNNER]);
    w.expectClean();
  });

  test("the 032b controls are deferred too, and the page never asks for their data", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    await expand(page, "health-hardening");
    for (const id of ["health-backups", "health-integrity", "health-governance"]) await expect(page.getByTestId(id)).toContainText(HARDENING);
    for (const id of ["backup-now", "backup-test"]) await expectDeferred(page, page.getByTestId(id), HARDENING, api);
    await expand(page, "health-sources");
    await expectDeferred(page, page.getByTestId("health-new-sources").getByRole("button", { name: "Look for new sources" }), NETWORK, api);
    await expect(page.getByTestId("new-sources-reason")).toHaveText(NETWORK);
    expect(api.requested.filter((r) => /backups|integrity|governance|source_network|bridge/.test(r.path))).toEqual([]);
    w.expectClean();
  });

  test("the deferred subsystems show their reason where the data was", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await open(page);
    await expect(page.getByTestId("health-release-reason")).toHaveText("Releases arrive with the hardening port.");
    await expect(page.getByTestId("health-backups-reason")).toHaveText("Backups arrive with the hardening port.");
    await expect(page.getByTestId("health-integrity-reason")).toHaveText("The integrity check arrives with the hardening port.");
    await expect(page.getByTestId("health-releases-reason")).toHaveText("Releases arrive with the hardening port.");
    await expect(page.getByTestId("health-kpi").nth(4)).toContainText("Not ported yet");
    await expand(page, "health-build-d");
    await expect(page.getByTestId("health-build")).toHaveText("Running build: The build and stale-interface check is not ported yet.");
    await expect(page.getByTestId("health-selfcheck")).toHaveText("Startup self-check: The startup self-check is not ported yet.");
    await expect(page.getByTestId("health-validation-data")).toContainText("WATCH: 3 company(ies), The watch sensors are not ported yet.");
    w.expectClean();
  });

  test("the retired Scout parts are gone: no Scout lane or KPI, no Grok bridge chart, no repair research", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await open(page);
    const pipe = page.getByTestId("health-pipeline");
    await expect(pipe.locator("[data-node]")).toHaveCount(5);
    for (const id of ["df-scan", "df-triage", "df-queue", "df-you", "df-conviction"]) await expect(pipe.locator(`[data-node="${id}"]`)).toBeVisible();
    await expect(pipe.locator('[data-node^="s00"], [data-node^="nat"]')).toHaveCount(0);
    await expect(page.getByTestId("bridge-chart")).toHaveCount(0);
    await expect(page.getByTestId("pool-bridge")).toHaveCount(0);
    await expect(page.getByTestId("pool-general")).toContainText("General model budget");
    await page.getByTestId("health-source-problem").first().click();
    await expect(page.getByTestId("health-detail")).toContainText("the page layout or feed format changed");
    await expect(page.getByRole("dialog").getByRole("button", { name: /repair research/i })).toHaveCount(0);
    expect(await text(page)).not.toMatch(/Scout 00|Native Scout|Grok|search bridge|repair research|Scout Bridge/i);
    w.expectClean();
  });

  test("every chart drills down: a pipeline step, a job period, a model, a source and an issue open the drawer", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await open(page);
    const dlg = page.getByRole("dialog");
    await page.getByTestId("health-pipeline").locator('[data-node="df-conviction"]').click();
    await expect(page.getByRole("dialog", { name: "Conviction → Manager" })).toContainText("Only you send a company to the Manager.");
    await page.keyboard.press("Escape");
    await expect(dlg).toHaveCount(0);
    const jobs = page.getByTestId("health-job-history");
    for (const r of ["24h", "7d", "30d"]) {
      await jobs.getByRole("button", { name: r, exact: true }).click();
      await expect(jobs.getByRole("button", { name: r, exact: true })).toHaveAttribute("aria-pressed", "true");
    }
    await jobs.locator("button[data-state]").first().click();
    await expect(page.getByTestId("health-detail")).toContainText("Runs in this period");
    await page.keyboard.press("Escape");
    await page.getByTestId("health-models").locator('[data-model="inventa/brisk-flash-1"]').click();
    await expect(page.getByRole("dialog", { name: "brisk-flash-1" })).toContainText("Errors by kind");
    await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
    await page.getByTestId("health-source-problem").nth(1).click();
    await expect(page.getByRole("dialog", { name: "Kestrel Wire" })).toContainText("External limitation — no action required");
    await page.keyboard.press("Escape");
    await page.getByTestId("issues-need").getByTestId("health-issue").click();
    await expect(page.getByTestId("health-detail")).toContainText("Needs your action");
    await page.keyboard.press("Escape");
    await page.getByTestId("health-pipeline").locator('[data-node="df-you"]').click();
    await page.getByRole("dialog").getByRole("link", { name: "Open deal flow →" }).click();
    await expect(page).toHaveURL((u) => u.pathname === "/deal-flow", { timeout: 30_000 });
    w.expectClean();
  });

  test("Refresh re-reads the two GETs and nothing else", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    await page.waitForTimeout(400); // the dev server's StrictMode may read twice on mount: count from here
    const before = api.requested.length;
    await page.getByTestId("health-freshness").getByRole("button", { name: "Refresh", exact: true }).click();
    await expect.poll(() => api.requested.length).toBeGreaterThanOrEqual(before + 2);
    await page.waitForTimeout(400);
    expect(api.requested.slice(before).map((r) => `${r.method} ${r.path}`).sort()).toEqual(["GET /api/system_health", "GET /api/system_health_overview"]);
    expect(api.writes()).toEqual([]);
    w.expectClean();
  });

  test("the empty snapshot: Status unknown without a timestamp; empty panels say so", async ({ page }) => {
    const w = watch(page);
    await mockApi(page, { health: load("health_empty.json"), overview: load("overview_empty.json") });
    await open(page);
    await expect(page.getByTestId("health-verdict")).toContainText("Status unknown");
    await expect(page.getByTestId("health-action")).toContainText("the imported snapshot contains no job report");
    await expect(page.getByTestId("health-action")).not.toContainText(/\d{4}-\d{2}-\d{2}/);
    await expect(page.getByTestId("health-job-history")).toContainText("History unavailable");
    await expect(page.getByTestId("health-attention")).toContainText("No source needs attention.");
    await expectNoPromise(page);
    w.expectClean();
  });

  test("on a phone: no horizontal scroll, the pipeline and the job rows stack", async ({ page }) => {
    await mockApi(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page);
    await expect(page.getByTestId("health-pipeline").locator("[data-node]").first()).toBeVisible();
    const [a, b] = [await page.locator('[data-node="df-scan"]').boundingBox(), await page.locator('[data-node="df-triage"]').boundingBox()];
    expect(b!.y).toBeGreaterThan(a!.y); // stacked, not side by side
    await expectNoHorizontalOverflow(page);
    await page.getByRole("button", { name: "Run overdue now", exact: true }).first().scrollIntoViewIfNeeded();
    await expect(page.getByTestId("health-run-overdue-note").first()).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  for (const [name, size] of [
    ["1366", { width: 1366, height: 768 }],
    ["1920", { width: 1920, height: 1080 }],
    ["390 (phone)", { width: 390, height: 844 }],
  ] as const) {
    test(`no horizontal overflow at ${name}`, async ({ page }) => {
      await mockApi(page);
      await page.setViewportSize(size);
      await open(page);
      await expectNoHorizontalOverflow(page);
      await expand(page, "health-hardening");
      await expectNoHorizontalOverflow(page);
      await page.getByTestId("health-source-problem").first().click();
      await expectNoHorizontalOverflow(page);
    });
  }

  test("no horizontal overflow at 150 % zoom", async ({ page }) => {
    await mockApi(page);
    await zoom150(page);
    await open(page);
    await expectNoHorizontalOverflow(page);
    await expand(page, "health-jobs");
    await expectNoHorizontalOverflow(page);
  });
});
