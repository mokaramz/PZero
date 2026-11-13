/**
 * The background-jobs runner (review 032c) on the page — the catch-up banner in the app shell and "Run overdue now" on
 * System health — with the API MOCKED by route interception, so no backend is needed: only the frontend (`npm run dev`
 * in frontend/, or PZ_BASE_URL). Every job note, source and model in fixtures/jobs/ is invented (byte-identical copies
 * of `frontend/src/features/jobs/test/*.json`; the overview is fixtures/health/overview.json).
 *
 * Covered: the banner while a run goes (the count, the job running now, what is left, the reworded sentence) and when it
 * is done (it goes, and every view is read again); "Run overdue now" posting exactly the ported overdue ids from both of
 * its places, then the banner showing that run; `{started: false}` showing its reason; the six unported jobs labelled
 * "not ported yet", never posted, with no promise of a run near them; the deferred fallback; no Scout text; no
 * horizontal overflow at 1366, 1920, 390 and 150 %.
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test jobs-mocked
 */
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expand, expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (n: string): J => JSON.parse(readFileSync(resolve(FIX, n), "utf8"));

const UNPORTED = ["watch_checks", "deal_flow_scan", "triage_retry", "source_network", "triage_compression", "case_refresh"];
const PORTED_OVERDUE = ["event_scan", "validation_snapshot", "news_refresh", "news_weekly_review"];
const STARTED = "Running overdue jobs in the background";
const SENTENCE =
  "Project Zero runs its periodic work (scans, news, snapshots) in this catch-up when the app opens, and in the optional Windows task “Project Zero v2 - background jobs”, registered disabled until the cutover. Budget caps apply; nothing is sent to anyone.";
const SNAPSHOT = "Background jobs are not ported yet: job state and history are the imported snapshot.";
const RUNNER = "The background-job runner is not ported yet.";
const FORBIDDEN = ["retries automatically", "kept for retry", "run again when due", "starts them immediately", "next background trigger", "let catch-up run it", "asleep", "runs again automatically", "kept for the next run"];
const DIAGNOSTICS = ["health-glance", "health-sources", "health-coverage", "health-jobs", "health-ai", "health-news", "health-hardening", "health-build-d"];

type Phase = "idle" | "running" | "done";

/**
 * Mock System health (the live runner unless `health` says otherwise), its overview, `GET catchup` and `POST
 * catchup_run`. The catch-up starts in `phase`; a `catchup_run` that starts moves it to "running"; while running, each
 * read counts down `runningReads` and then answers "done". Anything else under /api is a 404.
 */
async function mockApi(page: Page, opts: { health?: J; phase?: Phase; runningReads?: number; run?: (body: J) => J } = {}) {
  const requested: Array<{ method: string; path: string; body: J }> = [];
  page.on("request", (r) => {
    if (!r.url().includes("/api/")) return;
    const u = new URL(r.url());
    let body: J = null;
    try {
      body = r.postDataJSON();
    } catch {
      body = null;
    }
    requested.push({ method: r.method(), path: u.pathname + u.search, body });
  });
  const state = { phase: opts.phase ?? ("idle" as Phase), left: opts.runningReads ?? 2 };
  await page.clock.setFixedTime(new Date(2026, 10, 13, 9, 30));
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/system_health(\?.*)?$/, (route) => route.fulfill({ json: opts.health ?? load("jobs/health_runner.json") }));
  await page.route(/\/api\/system_health_overview(\?.*)?$/, (route) => route.fulfill({ json: load("health/overview.json") }));
  await page.route(/\/api\/catchup(\?.*)?$/, (route) => {
    if (state.phase === "running" && state.left-- <= 0) state.phase = "done";
    return route.fulfill({ json: load(`jobs/catchup_${state.phase}.json`) });
  });
  await page.route(/\/api\/catchup_run$/, (route) => {
    const answer = opts.run ? opts.run(route.request().postDataJSON()) : { started: true, queue: PORTED_OVERDUE };
    if (answer.started) Object.assign(state, { phase: "running", left: opts.runningReads ?? 2 });
    return route.fulfill({ json: answer });
  });
  return {
    state,
    requested,
    posts: () => requested.filter((r) => r.method === "POST"),
    reads: (p: string) => requested.filter((r) => r.method === "GET" && r.path === p).length,
  };
}

async function open(page: Page) {
  await page.goto("/health");
  await expect(page.getByRole("heading", { level: 1, name: "System health" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("health-pipeline").locator("[data-node]").first()).toBeVisible();
}

const text = (page: Page) => page.locator("body").innerText();
const runButtons = (page: Page) => page.getByRole("button", { name: "Run overdue now", exact: true });

test.describe("Background jobs — mocked API", () => {
  test("the banner while a catch-up runs, then done: it goes and every view is read again", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page, { phase: "running", runningReads: 2 });
    await open(page);
    const banner = page.getByTestId("catchup-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute("role", "status");
    await expect(banner).toHaveText(`Catching up on 4 overdue checks… Now: Validation snapshot. 3 left. ${SENTENCE}`);
    await expect(banner).not.toContainText("Project Zero runs on your computer");
    await expect(banner).not.toContainText(/WATCH checks|scout|bridge/i);
    const healthReads = api.reads("/api/system_health");
    await expect(banner).toBeHidden({ timeout: 15_000 }); // 2.5 s polls, then "done"
    expect(api.state.phase).toBe("done");
    await expect.poll(() => api.reads("/api/system_health")).toBeGreaterThan(healthReads); // the old "refresh everything"
    expect(api.posts()).toEqual([]);
    w.expectClean();
  });

  test("idle: no banner", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await open(page);
    await page.waitForTimeout(600);
    await expect(page.getByTestId("catchup-banner")).toHaveCount(0);
    w.expectClean();
  });

  test('"Run overdue now" posts exactly the ported overdue ids; the toast; the banner shows that run, then done', async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page, { runningReads: 3 });
    await open(page);
    await expect(runButtons(page)).toHaveCount(2);
    for (const b of await runButtons(page).all()) {
      await expect(b).toBeEnabled();
      await expect(b).not.toHaveAttribute("aria-disabled", "true");
    }
    await expect(page.getByTestId("health-run-overdue-note")).toHaveCount(0);
    await page.getByTestId("health-job-history").getByRole("button", { name: "Run overdue now", exact: true }).click();
    await expect(page.getByText(STARTED).first()).toBeVisible();
    expect(api.posts()).toEqual([{ method: "POST", path: "/api/catchup_run", body: { only: PORTED_OVERDUE } }]);
    const banner = page.getByTestId("catchup-banner");
    await expect(banner).toBeVisible(); // `catchup` was invalidated
    await expect(banner).toContainText("Catching up on 4 overdue checks…");
    await expect(banner).toBeHidden({ timeout: 20_000 });
    // the second place sends the same body
    await page.getByTestId("issues-auto").getByRole("button", { name: "Run overdue now", exact: true }).click();
    await expect.poll(() => api.posts().length).toBe(2);
    expect(api.posts()[1].body).toEqual({ only: PORTED_OVERDUE });
    for (const p of api.posts()) for (const id of UNPORTED) expect(p.body.only).not.toContain(id);
    w.expectClean();
  });

  test("{started: false}: the reason next to both buttons; no banner", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page, { run: () => ({ started: false, reason: "already running" }) });
    await open(page);
    await runButtons(page).first().click();
    await expect(page.getByTestId("health-run-overdue-result")).toHaveText(["Not started — already running.", "Not started — already running."]);
    await expect(page.getByText(STARTED)).toHaveCount(0);
    expect(api.posts()).toHaveLength(1);
    await page.waitForTimeout(600);
    await expect(page.getByTestId("catchup-banner")).toHaveCount(0);
    w.expectClean();
  });

  test("the unported jobs: labelled 'not ported yet', their history kept, never posted, no promise of a run near them", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    await expect(page.getByTestId("health-jobs-snapshot")).toHaveCount(0);
    await expect(page.getByTestId("health-jobs-unported")).toContainText("“not ported yet” does not run");
    const mx = page.getByTestId("job-matrix");
    for (const id of UNPORTED) await expect(mx.locator(`[data-job="${id}"] > span`).last()).toHaveText("not ported yet");
    await expect(mx.locator('[data-job="watch_checks"] button[data-state]').first()).toBeVisible(); // imported runs kept
    await expect(page.locator('[data-node="df-scan"]')).toContainText("Not ported yet");
    await expand(page, "health-jobs");
    const rows = page.getByTestId("health-job");
    await expect(rows).toHaveCount(11);
    const unported = page.locator('[data-testid="health-job"][data-ported="false"]');
    await expect(unported).toHaveCount(6);
    for (const r of await unported.all()) {
      await expect(r.getByTestId("health-job-not-ported")).toHaveText("not ported yet");
      await expect(r).toContainText(/last ok \d{4}-\d{2}-\d{2}T/);
      const t = await r.innerText();
      for (const p of FORBIDDEN) expect(t, p).not.toContain(p);
    }
    await expect(page.getByTestId("health-job-runner")).toContainText("Job runner: idle · last background run 2026-11-09 22:05 (completed) · last app run 2026-11-13 09:00 (ok)");
    // the issues that name an unported job keep the revision 2 wording
    for (const name of ["Triage queue compression", "Case preparation freshness"]) {
      const t = await page.getByTestId("health-issue").filter({ hasText: name }).innerText();
      for (const p of FORBIDDEN) expect(t, p).not.toContain(p);
    }
    // an unported job's period
    await mx.locator('[data-job="case_refresh"] button[data-state="budget_blocked"]').click();
    const d = page.getByTestId("health-detail");
    await expect(d).toContainText("Next runnot ported yet");
    await expect(page.getByTestId("health-runs-snapshot")).toHaveText("This job is not ported yet: its state and history are the imported snapshot.");
    const dt = await d.innerText();
    for (const p of FORBIDDEN) expect(dt, p).not.toContain(p);
    await page.keyboard.press("Escape");
    await runButtons(page).first().click();
    await expect.poll(() => api.posts().length).toBe(1);
    expect(api.posts()[0].body.only).toEqual(PORTED_OVERDUE);
    w.expectClean();
  });

  test("no Scout text anywhere, with the banner up and every section open", async ({ page }) => {
    const w = watch(page);
    await mockApi(page, { phase: "running", runningReads: 1000 });
    await open(page);
    await expect(page.getByTestId("catchup-banner")).toBeVisible();
    for (const id of DIAGNOSTICS) {
      await expand(page, id);
      expect(await text(page)).not.toMatch(/\bScout\b|Grok|search bridge|repair research/i); // the shell tagline says "scouting"
    }
    expect(await text(page)).not.toContain(SNAPSHOT);
    w.expectClean();
  });

  test("the deferred fallback: the lock still deferred keeps the 032a snapshot and the disabled Run overdue now", async ({ page }) => {
    const w = watch(page);
    const h = load("jobs/health_runner.json");
    h.job_runner.lock = { deferred: "The job runner lock is not ported yet: no runner is alive." };
    const api = await mockApi(page, { health: h });
    await open(page);
    await expect(page.getByTestId("health-jobs-snapshot")).toHaveText(SNAPSHOT);
    await expect(page.getByTestId("health-run-overdue-note")).toHaveText([RUNNER, RUNNER]);
    for (const b of await runButtons(page).all()) {
      await expect(b).toHaveAttribute("aria-disabled", "true");
      await b.click({ force: true });
    }
    await page.waitForTimeout(400);
    expect(api.posts()).toEqual([]);
    await expand(page, "health-jobs");
    await expect(page.getByTestId("health-job-runner")).toContainText("The job runner lock is not ported yet: no runner is alive.");
    await expect(page.getByTestId("health-job-not-ported")).toHaveCount(6);
    w.expectClean();
  });

  for (const [name, size] of [
    ["1366", { width: 1366, height: 768 }],
    ["1920", { width: 1920, height: 1080 }],
    ["390 (phone)", { width: 390, height: 844 }],
  ] as const) {
    test(`no horizontal overflow at ${name}, with the banner up`, async ({ page }) => {
      await mockApi(page, { phase: "running", runningReads: 1000 });
      await page.setViewportSize(size);
      await open(page);
      await expect(page.getByTestId("catchup-banner")).toBeVisible();
      await expectNoHorizontalOverflow(page);
      await expand(page, "health-jobs");
      await expectNoHorizontalOverflow(page);
      await runButtons(page).first().scrollIntoViewIfNeeded();
      await expectNoHorizontalOverflow(page);
    });
  }

  test("no horizontal overflow at 150 % zoom, with the banner up", async ({ page }) => {
    await mockApi(page, { phase: "running", runningReads: 1000 });
    await zoom150(page);
    await open(page);
    await expect(page.getByTestId("catchup-banner")).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await expand(page, "health-jobs");
    await expectNoHorizontalOverflow(page);
  });
});
