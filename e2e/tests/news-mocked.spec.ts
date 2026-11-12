/**
 * News & Learning (review 028a) — the old `news.spec.ts` (the historical case with its backcast, the weekly review, the
 * sources view and the refresh line), ported to the new paths. The API is MOCKED with route interception, so no backend
 * is needed: only the frontend (`npm run dev` in frontend/, or PZ_BASE_URL). Every company, publication and URL in
 * fixtures/news/ is invented.
 *
 * The old refresh test (click → progress → outcome) is back with 028c: the run executes inside its request, so the
 * running state lasts while the POST is in flight, nothing polls, and the status, stories and sources are read again when
 * it returns; a run already active (409) is the old line and a run cut by its deadline (503) the failure toast. "Re-measure
 * now" posts the evaluation and re-reads the sources. The decisions write since 028b: the outcome proposal
 * (Confirm outcome in two clicks, Reject, Not enough evidence, an `already` answer), "Audit this miss" and "Add an early
 * signal" (its form), each with its exact POST path and body, the old toasts, the re-read and the 400 refusals; opening
 * and cancelling the form writes nothing. The old "new sources" test belongs to System health and the activity-dock
 * tests to the shell; neither is part of this page.
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test news-mocked
 */
import { expect, test, type Locator, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expectNoHorizontalOverflow, recordPosts, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures", "news");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (n: string): J => JSON.parse(readFileSync(resolve(FIX, n), "utf8"));

/** the 028a deferral of the decisions, gone since 028b */
const WRITES_028B = "Recording News decisions arrives with the News writes port (028b)";
/** the 028a deferral of the runs, gone since 028c */
const REFRESH_028C = "Refreshing News arrives with the News refresh port (028c)";
const HEALTH = "System health arrives with its port";
const TABS = ["Today", "All stories", "Caught early", "Misses", "Historical cases", "What's moving", "My companies", "Weekly review", "News sources"];
const WINDOWS = ["30 days", "90 days", "180 days", "All time"];
/** the old write endpoints, their 028b / 028c paths and the dropped Scout Bridge calls */
const WRITE_PATHS = /\/api\/(news_(outcome|audit_miss|backcast|backcast_job|refresh|sources_evaluate)\b|news\/(outcome|audit_miss|backcast|refresh|sources\/evaluate)\b|bridge_create\b)/;

type Write = "outcome" | "audit_miss" | "backcast";
type Run = "refresh" | "evaluate";
type Answer = { status: number; body: J };
const isAnswer = (x: J): x is Answer => !!x && typeof x === "object" && "status" in x && "body" in x;

/** Mock the four News reads, the three writes (028b, the old success shapes of fixtures/news/news_writes.json) and the
 *  two runs (028c, fixtures/news/news_runs.json). A write's `answer` (when it returns something) replaces the default
 *  answer; otherwise `refuse` answers it with a 400 and that text. A run's `run` handler may wait (the request stays in
 *  flight) and may answer; by default the run finishes with the fixture's answer, and the next status (refresh) or
 *  sources (evaluate) read shows it. Anything else under /api answers 404 (the shell's not-ported reads are allowed by
 *  `watch`, any other 404 fails the test). Returns every API request (method + path + query), in order. */
async function mockApi(
  page: Page,
  opts: {
    news?: J;
    weekly?: J;
    refresh?: "partial" | "failed" | "never";
    answer?: Partial<Record<Write, (body: J) => J | Answer | null>>;
    refuse?: Partial<Record<Write, string>>;
    run?: Partial<Record<Run, (body: J) => J | Answer | null | Promise<J | Answer | null>>>;
  } = {},
) {
  const news = opts.news ?? load("news.json");
  const weekly = opts.weekly ?? load("news_weekly.json");
  const sources = load("news_sources.json");
  let refresh = load("news_refresh_status.json")[opts.refresh ?? "partial"];
  let measured: string | null = null; // the evaluation's time, once "Re-measure now" has finished
  const requested: Array<{ method: string; path: string }> = [];
  page.on("request", (r) => {
    if (!r.url().includes("/api/")) return;
    const u = new URL(r.url());
    requested.push({ method: r.method(), path: u.pathname + u.search });
  });
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/news(\?.*)?$/, (route) => route.fulfill({ json: news }));
  await page.route(/\/api\/news\/weekly(\?.*)?$/, (route) => route.fulfill({ json: weekly }));
  await page.route(/\/api\/news\/refresh_status(\?.*)?$/, (route) => route.fulfill({ json: refresh }));
  await page.route(/\/api\/news\/sources(\?.*)?$/, (route) => {
    const w = new URL(route.request().url()).searchParams.get("window") ?? "90";
    const body = sources[w] ?? sources["90"];
    return route.fulfill({ json: measured ? { ...body, evaluated_at: measured } : body });
  });
  const writes = load("news_writes.json");
  await page.route(/\/api\/news\/(outcome|audit_miss|backcast)$/, (route) => {
    const name = new URL(route.request().url()).pathname.split("/").pop() as Write;
    const body = route.request().postDataJSON() as J;
    const custom = opts.answer?.[name]?.(body);
    if (custom) return isAnswer(custom) ? route.fulfill({ status: custom.status, json: custom.body }) : route.fulfill({ json: custom });
    const error = opts.refuse?.[name];
    if (error) return route.fulfill({ status: 400, json: { ok: false, error } });
    if (name === "outcome") return route.fulfill({ json: { ...writes[body.decision], event_id: body.event_id } });
    return route.fulfill({ json: writes[name] });
  });
  const runs = load("news_runs.json");
  await page.route(/\/api\/news\/(refresh|sources\/evaluate)$/, async (route) => {
    const name: Run = new URL(route.request().url()).pathname.endsWith("/refresh") ? "refresh" : "evaluate";
    const custom = await opts.run?.[name]?.(route.request().postDataJSON() as J);
    if (custom && isAnswer(custom)) return route.fulfill({ status: custom.status, json: custom.body });
    const answer = custom ?? runs[name];
    if (name === "refresh") {
      refresh = { ...answer };
      delete refresh.started;
      delete refresh.run_id;
    } else measured = answer.evaluated_at;
    return route.fulfill({ json: answer });
  });
  return {
    requested,
    writes: () => requested.filter((r) => r.method !== "GET" || WRITE_PATHS.test(r.path)),
    /** the distinct News requests, in first-seen order (the shell may re-read a query on focus) */
    reads: () => [...new Set(requested.filter((r) => r.path.startsWith("/api/news")).map((r) => `${r.method} ${r.path}`))],
  };
}
type Api = Awaited<ReturnType<typeof mockApi>>;

const sections = (page: Page) => page.getByRole("tablist", { name: "News sections" });
const section = (page: Page, name: string) => sections(page).getByRole("tab", { name, exact: true }).click();

async function open(page: Page) {
  await page.goto("/news");
  await expect(page.getByRole("heading", { name: "News & Learning", level: 1 })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("news-concept")).toBeVisible();
}

/** A run's handler that holds the request in flight until `release()`. */
function held() {
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  return {
    handler: async () => {
      await gate;
      return null;
    },
    release: () => release(),
  };
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
});

/* ------------------------------------------------------------------ news.spec.ts: the historical learning case */
test("news & learning: a historical learning case with a sourced backcast", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  await open(page);
  await expect(page.getByTestId("news-concept")).toContainText("VC concept of the day");
  await section(page, "Historical cases");
  const story = page.getByTestId("news-story").filter({ hasText: "Halvard Robotics" });
  await expect(story).toContainText("HISTORICAL CASE");
  await expect(story).toContainText("🔥 IMPORTANT");
  await expect(story.getByTestId("news-check")).toContainText("predate Project Zero");
  await story.getByTestId("news-teach").click();
  await expect(story).toContainText("What is a secondary sale?");
  await story.getByRole("button", { name: "Backcast & sources" }).click();
  const bc = story.getByTestId("news-backcast");
  await expect(bc).toContainText("Earliest plausible signal");
  await expect(bc).toContainText("only clear in retrospect");
  await expect(bc).toContainText("university spinout");
  await section(page, "Today");
  await expect(page.getByText(/caught early/).first()).toBeVisible();
  await section(page, "Weekly review");
  await expect(page.getByTestId("news-weekly")).toContainText("Weekly learning review");
  await expectNoHorizontalOverflow(page);
  expect(api.reads().sort()).toEqual(["GET /api/news", "GET /api/news/refresh_status", "GET /api/news/weekly"]);
  w.expectClean();
});

/* ------------------------------------------------------------------ every section */
test("the nine sections, one at a time, as local state", async ({ page }) => {
  const w = watch(page);
  await mockApi(page);
  await open(page);
  await expect(sections(page).getByRole("tab")).toHaveText(TABS);
  await expect(sections(page).getByRole("tab", { name: "Today" })).toHaveAttribute("aria-selected", "true");
  const states = () => page.getByTestId("news-story").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.state));
  expect(await states()).toEqual(["CAUGHT_EARLY", "UNKNOWN", "KNOWN_LATE"]);
  await section(page, "All stories");
  await expect(page.getByTestId("news-story")).toHaveCount(7);
  await section(page, "Caught early");
  await expect(page.getByTestId("news-story")).toHaveCount(1);
  await expect(page.getByTestId("news-story")).toContainText("Project Zero edge: detected 61 days before this event.");
  await section(page, "Misses");
  expect(await states()).toEqual(["UNKNOWN", "MISSED"]);
  await section(page, "What's moving");
  await expect(page.getByTestId("news-theme")).toHaveCount(2);
  await expect(page.getByTestId("news-theme").first()).toContainText("MARKET SIGNAL");
  await section(page, "My companies");
  await expect(page.getByTestId("news-story")).toHaveCount(2);
  await section(page, "Weekly review");
  await expect(page.getByTestId("news-weekly")).toContainText("Caught earlyVantor Kinetics");
  await section(page, "News sources");
  await expect(page.getByTestId("news-sources-best")).toBeVisible();
  await expect(page).toHaveURL(/\/news$/); // the section is local state, as before
  await expect(page.getByTestId("news-footer")).toContainText("Project Zero started on 27 Sept 2026.");
  w.expectClean();
});

/* ------------------------------------------------------------------ news.spec.ts: the sources view */
test("news sources: best-by-purpose answers, honest sample sizes, expandable details, each window", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  await open(page);
  await section(page, "News sources");
  const box = page.getByTestId("news-sources");
  await expect(box.getByTestId("news-sources-best")).toContainText("Best for Europe-wide coverage");
  await expect(box.getByTestId("news-sources-best")).toContainText("Munich");
  await expect(box.getByTestId("news-sources-bias")).toContainText("How fair is this benchmark?");
  await expect(box.getByTestId("news-sources-missing")).toContainText("Are we missing a publication?");
  await expect(box.getByTestId("news-sources-declining")).toContainText("Channel Tech Review");
  const rows = box.getByTestId("news-source-row");
  await expect(rows).toHaveCount(6);
  const isar = rows.filter({ hasText: "Isar Startup Post" });
  await isar.getByRole("button", { name: "Details" }).click();
  await expect(isar.getByTestId("news-source-detail")).toContainText("Early signal");
  await expect(isar.getByTestId("news-source-detail")).toContainText("Hypothesis to test");
  const swiss = rows.filter({ hasText: "Swiss deal ticker" });
  await swiss.getByRole("button", { name: "Details" }).click();
  await expect(swiss.getByTestId("news-source-health-deferred")).toHaveText(`Technical: UNKNOWN (${HEALTH})`);
  await expect(box.getByRole("tablist", { name: "Time window" }).getByRole("tab")).toHaveText(WINDOWS);
  await box.getByRole("tab", { name: "30 days" }).click();
  await expect(box.getByTestId("news-sources-bias")).toContainText("4 of 10 material events");
  await expect(box.getByTestId("news-sources-best")).toContainText("COLLECTING DATA");
  await box.getByRole("tab", { name: "180 days" }).click();
  await expect(box.getByTestId("news-sources-bias")).toContainText("22 of 66 material events");
  await box.getByRole("tab", { name: "All time" }).click();
  await expect(box.getByTestId("news-sources-best")).toBeVisible();
  await expect(box.getByTestId("news-sources-bias")).toContainText("31 of 90 material events");
  await expectNoHorizontalOverflow(page);
  expect(api.reads().filter((r) => r.includes("/sources"))).toEqual([
    "GET /api/news/sources?window=90",
    "GET /api/news/sources?window=30",
    "GET /api/news/sources?window=180",
    "GET /api/news/sources?window=all",
  ]);
  w.expectClean();
});

/* ------------------------------------------------------------------ news.spec.ts: the refresh line */
test("news refresh: the last run's outcome is explicit; 'Refresh news' is enabled and nothing polls", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  await open(page);
  const box = page.getByTestId("news-refresh");
  await expect(page.getByTestId("news-refresh-result")).toHaveAttribute("data-tone", "warn");
  await expect(page.getByTestId("news-refresh-result")).toContainText("Refresh partly done");
  await expect(page.getByTestId("news-refresh-result")).toContainText("6 sources checked (1 failed)");
  await expect(page.getByTestId("news-refresh-result")).toContainText("179 already known");
  await expect(page.getByTestId("news-refresh-button")).toHaveText("Refresh news");
  await expect(page.getByTestId("news-refresh-button")).toBeEnabled();
  await expect(page.getByTestId("news-refresh-button")).not.toHaveAttribute("aria-disabled", "true");
  await expect(page.getByTestId("news-refresh-progress")).toHaveCount(0);
  await page.getByText("Which sources failed?").click();
  await expect(box).toContainText("Channel Tech Review");
  // the old page polled every 1.5 s while a background run was active; a run now lives inside its request, so after the
  // first read (the dev build's StrictMode mount may issue it twice) no further read comes
  const statusReads = () => api.requested.filter((r) => r.path === "/api/news/refresh_status").length;
  const first = statusReads();
  expect(first).toBeGreaterThanOrEqual(1);
  await page.waitForTimeout(3500);
  expect(statusReads()).toBe(first);
  expect(api.writes()).toEqual([]);
  w.expectClean();
});

test("news refresh: one POST of {}; the old running state while it is in flight and no polling; the new outcome and re-reads when it returns", async ({ page }) => {
  const w = watch(page);
  const run = held();
  const api = await mockApi(page, { run: { refresh: run.handler } });
  const posted = recordPosts(page);
  await open(page);
  await section(page, "News sources"); // the Sources window on screen is read again too
  await expect(page.getByTestId("news-sources-best")).toBeVisible();
  await expect(page.getByTestId("news-refresh-result")).toContainText("Refresh partly done");
  const count = (path: string) => api.requested.filter((r) => r.method === "GET" && r.path === path).length;
  const before = { status: count("/api/news/refresh_status"), news: count("/api/news"), sources: count("/api/news/sources?window=90") };
  const button = page.getByTestId("news-refresh-button");
  await button.click();
  await expect(button).toHaveText("Refreshing…");
  await expect(button).toBeDisabled();
  await expect(page.getByTestId("news-refresh-progress")).toContainText("Refreshing news…");
  await expect(page.getByTestId("news-refresh-result")).toHaveCount(0);
  await page.waitForTimeout(2000); // longer than the old 1.5 s poll
  expect(count("/api/news/refresh_status")).toBe(before.status);
  expect(posted).toEqual([{ path: "/api/news/refresh", body: {} }]);

  run.release();
  await expect(page.getByTestId("news-refresh-result")).toHaveAttribute("data-tone", "ok");
  await expect(page.getByTestId("news-refresh-result")).toContainText("Refresh complete");
  await expect(page.getByTestId("news-refresh-result")).toContainText("2 new stories (1 material)");
  await expect(page.getByText("Which sources failed?")).toHaveCount(0);
  await expect(button).toHaveText("Refresh news");
  await expect(button).toBeEnabled();
  await expect(page.getByTestId("news-refresh-progress")).toHaveCount(0);
  expect(count("/api/news/refresh_status")).toBeGreaterThan(before.status);
  await expect.poll(() => count("/api/news")).toBeGreaterThan(before.news);
  await expect.poll(() => count("/api/news/sources?window=90")).toBeGreaterThan(before.sources);
  await expect(page.getByText(/^✕/)).toHaveCount(0);
  expect(posted).toHaveLength(1);
  w.expectClean();
});

test("news refresh: a run already active (409) is the old line; a run cut by its deadline (503) is the failure toast; nothing is read again", async ({ page }) => {
  const w = watch(page, { expected: [409, 503] });
  const runs = load("news_runs.json");
  let answer: Answer = { status: 409, body: runs.busy };
  const api = await mockApi(page, { run: { refresh: () => answer } });
  const posted = recordPosts(page);
  await open(page);
  await expect(page.getByTestId("news-refresh-result")).toContainText("Refresh partly done");
  const before = newsReads(api);
  const button = page.getByTestId("news-refresh-button");
  await button.click();
  await expect(page.getByTestId("news-refresh-message")).toContainText("A news refresh is already running.");
  await expect(page.getByText(/^✕/)).toHaveCount(0);
  await expect(page.getByTestId("news-refresh-result")).toContainText("Refresh partly done");
  await expect(button).toBeEnabled();
  answer = { status: 503, body: runs.deadline };
  await button.click();
  await expect(page.getByText("✕ Refreshing news failed — The news refresh did not finish within its time limit; nothing was saved.")).toBeVisible();
  await expect(page.getByTestId("news-refresh-message")).toHaveCount(0);
  await expect(page.getByTestId("news-refresh-result")).toContainText("Refresh partly done");
  expect(posted).toEqual([
    { path: "/api/news/refresh", body: {} },
    { path: "/api/news/refresh", body: {} },
  ]);
  expect(newsReads(api)).toBe(before);
  w.expectClean();
});

test("news sources: 'Re-measure now' — one POST of {}, busy while it runs, the toast, and every window read again", async ({ page }) => {
  const w = watch(page);
  const run = held();
  const api = await mockApi(page, { run: { evaluate: run.handler } });
  const posted = recordPosts(page);
  await open(page);
  await section(page, "News sources");
  const box = page.getByTestId("news-sources");
  await expect(box).toContainText("Last measured: 2026-11-12 07:00");
  await box.getByRole("tab", { name: "30 days" }).click();
  await expect(box.getByTestId("news-sources-bias")).toContainText("4 of 10 material events");
  const count = (w: string) => api.requested.filter((r) => r.path === `/api/news/sources?window=${w}`).length;
  const before = { w30: count("30"), w90: count("90") };
  const remeasure = box.getByRole("button", { name: "Re-measure now" });
  await expect(remeasure).toBeEnabled();
  await expect(remeasure).not.toHaveAttribute("aria-disabled", "true");
  await remeasure.click();
  await expect(remeasure).toBeDisabled();
  expect(posted).toEqual([{ path: "/api/news/sources/evaluate", body: {} }]);
  run.release();
  await expect(page.getByText("News sources re-measured")).toBeVisible();
  await expect(box).toContainText("Last measured: 2026-11-12 10:16");
  await expect(remeasure).toBeEnabled();
  expect(count("30")).toBeGreaterThan(before.w30);
  await box.getByRole("tab", { name: "90 days" }).click(); // the window off screen was made stale: it is read again
  await expect.poll(() => count("90")).toBeGreaterThan(before.w90);
  await expect(box).toContainText("Last measured: 2026-11-12 10:16");
  expect(posted).toHaveLength(1);
  w.expectClean();
});

test("news refresh: a failed last attempt says so and shows the last successful refresh", async ({ page }) => {
  const w = watch(page);
  await mockApi(page, { refresh: "failed" });
  await open(page);
  await expect(page.getByTestId("news-refresh-result")).toHaveAttribute("data-tone", "fail");
  await expect(page.getByTestId("news-refresh-result")).toContainText("News refresh failed");
  await expect(page.getByTestId("news-last-ok")).toContainText("2026-11-12 07:00");
  await page.getByText("Which sources failed?").click();
  await expect(page.getByTestId("news-refresh")).toContainText("Isar Startup Post");
  w.expectClean();
});

test("before any refresh and with an empty data folder, every section says what it waits for", async ({ page }) => {
  const w = watch(page);
  await mockApi(page, { news: load("news_empty.json"), weekly: load("news_weekly_empty.json"), refresh: "never" });
  await open(page);
  await expect(page.getByTestId("news-refresh")).toContainText("Not refreshed yet.");
  await expect(page.getByText("No important story yet today.")).toBeVisible();
  await section(page, "What's moving");
  await expect(page.getByText("Two articles are not a trend.")).toBeVisible();
  await section(page, "Weekly review");
  await expect(page.getByTestId("news-weekly")).toContainText("A quiet week.");
  w.expectClean();
});

/* ------------------------------------------------------------------ the decisions (028b) */
const VANTOR = "nw-3f9a1c0b7d2e";
const BRIGHTWELL = "nw-1e8b5a6c4d90";
const newsReads = (api: Api) => api.requested.filter((r) => r.method === "GET" && r.path === "/api/news").length;

test("news: the outcome proposal — Confirm takes two clicks; Reject and Not enough evidence; exact POSTs, the old toast and a re-read", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  const posted = recordPosts(page);
  await open(page);
  const proposal = page.getByTestId("news-story").filter({ hasText: "Vantor Kinetics" }).first().getByTestId("news-outcome-proposal");
  await expect(proposal).toContainText("Only your confirmation records it in Validation.");
  await expect(proposal.getByRole("button")).toHaveText(["Confirm outcome", "Reject", "Not enough evidence"]);
  for (const b of await proposal.getByRole("button").all()) await expect(b).toBeEnabled();

  const confirm = proposal.getByRole("button", { name: "Confirm outcome" });
  await confirm.click();
  await expect(proposal.getByRole("button", { name: "Click again to confirm — records a verified outcome in Validation" })).toBeVisible();
  await page.waitForTimeout(200);
  expect(posted).toEqual([]); // the first click only arms it
  const before = newsReads(api);
  await proposal.getByRole("button", { name: /^Click again to confirm/ }).click();
  await expect(page.getByText("Recorded", { exact: true }).first()).toBeVisible();
  await expect.poll(() => newsReads(api)).toBeGreaterThan(before);

  await proposal.getByRole("button", { name: "Reject", exact: true }).click();
  await expect.poll(() => posted.length).toBe(2);
  await proposal.getByRole("button", { name: "Not enough evidence", exact: true }).click();
  await expect.poll(() => posted.length).toBe(3);
  expect(posted).toEqual([
    { path: "/api/news/outcome", body: { event_id: VANTOR, decision: "confirm" } },
    { path: "/api/news/outcome", body: { event_id: VANTOR, decision: "reject" } },
    { path: "/api/news/outcome", body: { event_id: VANTOR, decision: "not_enough" } },
  ]);
  w.expectClean();
});

test("news: an `already` answer is the old success toast; a refused decision (400) is the failure toast", async ({ page }) => {
  const w = watch(page, { expected: [400] });
  const api = await mockApi(page, { answer: { outcome: (b) => (b.decision === "reject" ? load("news_writes.json").already : null) }, refuse: { outcome: "this news event cannot become an outcome" } });
  const posted = recordPosts(page);
  await open(page);
  const proposal = page.getByTestId("news-story").filter({ hasText: "Vantor Kinetics" }).first().getByTestId("news-outcome-proposal");
  const before = newsReads(api);
  await proposal.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(page.getByText("Recorded", { exact: true }).first()).toBeVisible();
  await expect.poll(() => newsReads(api)).toBeGreaterThan(before);
  await proposal.getByRole("button", { name: "Not enough evidence", exact: true }).click();
  await expect(page.getByText("✕ Recording the outcome failed — this news event cannot become an outcome")).toBeVisible();
  expect(posted).toEqual([
    { path: "/api/news/outcome", body: { event_id: VANTOR, decision: "reject" } },
    { path: "/api/news/outcome", body: { event_id: VANTOR, decision: "not_enough" } },
  ]);
  w.expectClean();
});

test("news: Audit this miss — the event alone, the old toast and a re-read; a refusal (400) is shown", async ({ page }) => {
  const w = watch(page, { expected: [400] });
  let refuse = false;
  const api = await mockApi(page, { answer: { audit_miss: () => (refuse ? { status: 400, body: { ok: false, error: "no such news event with a named company" } } : null) } });
  const posted = recordPosts(page);
  await open(page);
  await section(page, "Misses");
  const audit = page.getByTestId("news-story").filter({ hasText: "Brightwell Bio" }).getByTestId("news-audit");
  await expect(audit).toHaveText("Audit this miss");
  await expect(audit).toBeEnabled();
  const before = newsReads(api);
  await audit.click();
  await expect(page.getByText("Miss audit created in Validation (prefilled)")).toBeVisible();
  await expect.poll(() => newsReads(api)).toBeGreaterThan(before);
  refuse = true;
  await audit.click();
  await expect(page.getByText("✕ Creating the miss audit failed — no such news event with a named company")).toBeVisible();
  expect(posted).toEqual([
    { path: "/api/news/audit_miss", body: { event_id: BRIGHTWELL } },
    { path: "/api/news/audit_miss", body: { event_id: BRIGHTWELL } },
  ]);
  await expect(page.getByTestId("news-story").filter({ hasText: "Quillon Labs" })).toContainText("miss audit recorded");
  w.expectClean();
});

test("news: Add an early signal — the old form; Add needs a date and an http URL; the exact POST, the toast, the form closes", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  const posted = recordPosts(page);
  await open(page);
  const vantor = page.getByTestId("news-story").filter({ hasText: "Vantor Kinetics" }).first();
  await vantor.getByRole("button", { name: "Sources & learning" }).click();
  await vantor.getByRole("button", { name: "Add an early signal" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Add an early signal" })).toBeVisible();
  await expect(dialog).toContainText("A public signal that existed BEFORE the story, with its source.");
  const date = dialog.getByRole("textbox", { name: "Date (YYYY, YYYY-MM or YYYY-MM-DD)" });
  const url = dialog.getByRole("textbox", { name: "Source URL" });
  const add = dialog.getByRole("button", { name: "Add", exact: true });
  await expect(date).toHaveAttribute("placeholder", "2021-06");
  await expect(dialog.getByRole("combobox", { name: "Signal family" })).toHaveValue("university_lab");
  await expect(dialog.getByRole("combobox", { name: "Knowable at the time?" })).toHaveValue("known_early_signal");
  await expect(add).toBeDisabled();
  await date.fill("2026-06");
  await url.fill("meetups.example/munich-robotics-june");
  await expect(add).toBeDisabled(); // not an http URL
  await url.fill("https://meetups.example/munich-robotics-june");
  await dialog.getByRole("textbox", { name: "What was visible" }).fill("Vantor Kinetics demo at a Munich robotics meetup");
  await dialog.getByRole("combobox", { name: "Signal family" }).selectOption("event");
  await dialog.getByRole("combobox", { name: "Knowable at the time?" }).selectOption("in_retrospect");
  expect(posted).toEqual([]);
  const before = newsReads(api);
  await add.click();
  await expect(page.getByText("Signal added to the backcast")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect.poll(() => newsReads(api)).toBeGreaterThan(before);
  expect(posted).toEqual([
    {
      path: "/api/news/backcast",
      body: {
        date: "2026-06",
        text: "Vantor Kinetics demo at a Munich robotics meetup",
        url: "https://meetups.example/munich-robotics-june",
        family: "event",
        kind: "in_retrospect",
        event_id: VANTOR,
      },
    },
  ]);
  w.expectClean();
});

test("news: a refused early signal (400) keeps the form open; opening and cancelling writes nothing", async ({ page }) => {
  const w = watch(page, { expected: [400] });
  await mockApi(page, { refuse: { backcast: "date as YYYY, YYYY-MM or YYYY-MM-DD" } });
  const posted = recordPosts(page);
  await open(page);
  await section(page, "Historical cases");
  const halvard = page.getByTestId("news-story").filter({ hasText: "Halvard Robotics" });
  await halvard.getByRole("button", { name: "Backcast & sources" }).click();
  await halvard.getByRole("button", { name: "Add an early signal" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("textbox", { name: "Date (YYYY, YYYY-MM or YYYY-MM-DD)" }).fill("2020");
  await dialog.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await halvard.getByRole("button", { name: "Add an early signal" }).click();
  await expect(dialog.getByRole("textbox", { name: "Date (YYYY, YYYY-MM or YYYY-MM-DD)" })).toHaveValue("2020"); // kept, as before
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.waitForTimeout(200);
  expect(posted).toEqual([]);

  await halvard.getByRole("button", { name: "Add an early signal" }).click();
  await dialog.getByRole("textbox", { name: "Date (YYYY, YYYY-MM or YYYY-MM-DD)" }).fill("early 2020");
  await dialog.getByRole("textbox", { name: "Source URL" }).fill("https://lab.example/halvard-spinout");
  await dialog.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("✕ Adding the early signal failed — date as YYYY, YYYY-MM or YYYY-MM-DD")).toBeVisible();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(posted).toEqual([
    {
      path: "/api/news/backcast",
      body: { date: "early 2020", text: "", url: "https://lab.example/halvard-spinout", family: "university_lab", kind: "known_early_signal", event_id: "nw-case-halvard-unicorn-2026-10" },
    },
  ]);
  w.expectClean();
});

/* ------------------------------------------------------------------ nothing is deferred any more (028c) */
test("news: every control is enabled (the 028c reason is gone); the Scout Bridge button is gone; nothing is sent without a click", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  let dialogs = 0;
  page.on("dialog", (d) => {
    dialogs++;
    void d.dismiss();
  });
  await open(page);
  await section(page, "All stories");
  const closed = page.getByRole("button", { name: /^(Backcast & sources|Sources & learning)$/ });
  while ((await closed.count()) > 0) await closed.first().click();
  await expect(page.locator('[aria-disabled="true"]')).toHaveCount(0);
  await expect(page.getByTestId("news-refresh-button")).toBeEnabled();
  await expect(page.getByRole("button", { name: "Add an early signal" })).toHaveCount(4);
  for (const b of await page.getByRole("button", { name: "Add an early signal" }).all()) await expect(b).toBeEnabled();
  await expect(page.getByRole("button", { name: /Prepare backcast research/ })).toHaveCount(0);
  await expect(page.getByText(/Scout Bridge/)).toHaveCount(0);
  await expect(page.getByText(WRITES_028B)).toHaveCount(0);
  await expect(page.getByText(REFRESH_028C)).toHaveCount(0);

  await section(page, "News sources");
  await expect(page.getByTestId("news-sources-best")).toBeVisible();
  await expect(page.locator('[aria-disabled="true"]')).toHaveCount(0);
  await expect(page.getByTestId("news-sources").getByRole("button", { name: "Re-measure now" })).toBeEnabled();
  await expect(page.locator(`[title="${REFRESH_028C}"]`)).toHaveCount(0);

  await page.waitForTimeout(300);
  expect(dialogs).toBe(0);
  expect(api.writes()).toEqual([]);
  w.expectClean();
});

/* ------------------------------------------------------------------ layout: 150 %, 1366, 1920 and the phone */
async function everySectionFits(page: Page) {
  await expectNoHorizontalOverflow(page);
  for (const name of TABS) {
    await section(page, name);
    await expect(sections(page).getByRole("tab", { name, exact: true })).toHaveAttribute("aria-selected", "true");
    if (name === "News sources") {
      await expect(page.getByTestId("news-sources-best")).toBeVisible();
      await page.getByTestId("news-source-row").first().getByRole("button", { name: "Details" }).click();
    } else if (name === "Weekly review") await expect(page.getByTestId("news-weekly")).toBeVisible();
    else if (name !== "What's moving") {
      // an opened card's toggle becomes "Hide analysis", so open the first closed one until none is left
      const closed = page.getByRole("button", { name: /^(Backcast & sources|Sources & learning)$/ });
      while ((await closed.count()) > 0) await closed.first().click();
      const teach = page.getByTestId("news-teach");
      for (let i = 0; i < (await teach.count()); i++) await teach.nth(i).click();
    }
    await expectNoHorizontalOverflow(page);
  }
}

test("news fits 150% zoom", async ({ page }) => {
  await zoom150(page);
  await mockApi(page);
  await open(page);
  await everySectionFits(page);
});

for (const [w, h] of [
  [1366, 768],
  [1920, 1080],
]) {
  test(`news fits ${w}px`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await mockApi(page);
    await open(page);
    await everySectionFits(page);
  });
}

test("news stays inside a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await open(page);
  await everySectionFits(page);
});
