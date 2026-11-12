/**
 * Validation (review 027a) — the old `validation.spec.ts` plus the Validation assertions of the old `focus.spec.ts`
 * (the five question tabs, one tabpanel), `navy.spec.ts` (grounded sparklines, reduced motion, phone width) and
 * `a-class-ui.spec.ts` (roles), ported to the new paths. The API is MOCKED with route interception, so no backend is
 * needed: only the frontend (`npm run dev` in frontend/, or PZ_BASE_URL). Every company, source and URL in
 * fixtures/validation/ is invented.
 *
 * 027a is the read side: the old "record an outcome / a miss" and "import a benchmark" flows become checks that every
 * write control is visible, disabled with its reason, and sends no request (the writes arrive with review 027b).
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test validation-mocked
 */
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expand, expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures", "validation");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (n: string): J => JSON.parse(readFileSync(resolve(FIX, n), "utf8"));

const WRITES = "Recording outcomes, audits and imports arrives with the Validation writes port (027b)";
const NEWS = "News & Learning arrives with its port";
const QUESTIONS = ["Are we early?", "Are we right?", "Which sources work?", "Where do we miss?", "What does it cost?"];
/** the old write endpoints and their 027b paths */
const WRITE_PATHS = /\/api\/(validation_(outcome|audit|retract|benchmark_import|scout_packet)|validation\/(outcome|audit|retract|benchmark_import))\b/;

/** Mock the two Validation reads; anything else under /api answers 404 (the shell's not-ported reads are allowed by
 *  `watch`, any other 404 fails the test). Returns every API request (method + path + query), in order. */
async function mockApi(page: Page, opts: { validation?: J } = {}) {
  const data = opts.validation ?? load("validation.json");
  const packet = load("scout_packet.json");
  const requested: Array<{ method: string; path: string }> = [];
  page.on("request", (r) => {
    if (!r.url().includes("/api/")) return;
    const u = new URL(r.url());
    requested.push({ method: r.method(), path: u.pathname + u.search });
  });
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/validation(\?.*)?$/, (route) => route.fulfill({ json: data }));
  await page.route(/\/api\/validation\/scout_packet(\?.*)?$/, (route) => {
    const cycle = new URL(route.request().url()).searchParams.get("cycle") ?? "";
    return route.fulfill({ json: { ...packet, cycle: cycle || "all" } });
  });
  return {
    requested,
    writes: () => requested.filter((r) => r.method !== "GET" || WRITE_PATHS.test(r.path)),
    /** the distinct Validation requests, in first-seen order (the app shell may re-read a query on focus) */
    reads: () => [...new Set(requested.filter((r) => r.path.startsWith("/api/validation")).map((r) => `${r.method} ${r.path}`))],
  };
}

const questions = (page: Page) => page.getByTestId("val-questions");
/** Validation answers one analytical question at a time. */
const question = (page: Page, q: string) => questions(page).getByRole("tab", { name: q }).click();

async function open(page: Page) {
  await page.goto("/validation");
  await expect(page.getByRole("heading", { name: "Validation & Learning", level: 1 })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("val-edge")).toBeVisible();
}

/** Visible, focusable, disabled with the 027b reason. */
async function expectDeferred(page: Page, testIdOrName: { testId?: string; name?: string }) {
  const el = testIdOrName.testId ? page.getByTestId(testIdOrName.testId) : page.getByRole("button", { name: testIdOrName.name, exact: true }).first();
  await expect(el).toBeVisible();
  await expect(el).toHaveAttribute("aria-disabled", "true");
  await expect(el).toHaveAttribute("title", WRITES);
  await expect(el).toHaveAccessibleDescription(WRITES);
  await el.click({ force: true }); // aria-disabled: Playwright would wait for it to become enabled
  await el.focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Space");
  return el;
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
});

/* ------------------------------------------------------------------ validation.spec.ts: the overview */
test("validation: edge, sources, calibration, honest 'collecting' states", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  await open(page);
  await expect(page.getByTestId("val-edge")).toContainText("exceptional recall"); // "Are we early?" first
  await expect(page.getByTestId("val-edge")).toContainText("collecting (3/5)");
  await expand(page, "val-measurement-d");
  await expect(page.getByTestId("val-measure")).toHaveCount(6); // known / collecting / partly known, per metric
  await expect(page.getByTestId("val-measurement")).toContainText("PARTLY KNOWN");
  await expect(page.getByTestId("val-data-issues")).toContainText("Vessra Robotics");
  await question(page, "Which sources work?");
  await expect(page.getByTestId("val-sources").locator("tbody tr")).toHaveCount(12);
  await expect(page.getByTestId("val-sources").locator("tbody tr").first()).toContainText("Northgate University spin-outs");
  await question(page, "Are we right?");
  await expect(page.getByTestId("val-calibration")).toContainText("your triage decisions");
  await expect(page.getByTestId("val-calibration")).toContainText("Smooth Operator calibration — human vs machine"); // a-class-ui: roles
  await expect(page.getByTestId("val-footer")).toContainText("Validation spends no model money");
  expect(api.reads()).toEqual(["GET /api/validation"]);
  w.expectClean();
});

test("an empty data folder is honestly NOT YET MEASURABLE", async ({ page }) => {
  const w = watch(page);
  await mockApi(page, { validation: load("validation_empty.json") });
  await open(page);
  await expand(page, "val-measurement-d");
  await expect(page.getByTestId("val-measure")).toHaveCount(6);
  await expect(page.getByTestId("val-measurement")).toContainText("NOT YET MEASURABLE");
  await expect(page.getByTestId("val-trends")).toHaveCount(0); // fewer than 3 snapshots: no line
  await question(page, "Are we right?");
  await expect(page.getByTestId("val-outcomes")).toContainText("No outcomes recorded yet.");
  w.expectClean();
});

/* ------------------------------------------------------------------ focus.spec.ts: one question at a time */
test("secondary areas as tabs: one area mounted at a time", async ({ page }) => {
  const w = watch(page);
  await mockApi(page);
  await open(page);
  const q = questions(page);
  await expect(q.getByRole("tab")).toHaveText(QUESTIONS);
  await expect(q.getByRole("tab", { name: "Are we early?" })).toHaveAttribute("aria-selected", "true");
  await expect(q.getByRole("tabpanel")).toHaveCount(1);
  await question(page, "Where do we miss?");
  await expect(q.getByRole("tab", { name: "Where do we miss?" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("val-misses")).toBeVisible();
  await expect(page.getByTestId("val-edge")).toHaveCount(0);
  await expect(q.getByRole("tabpanel")).toHaveCount(1);
  await expect(page).toHaveURL(/\/validation$/); // the question is local state, as before
  w.expectClean();
});

/* ------------------------------------------------------------------ navy.spec.ts: grounded sparklines */
test("grounded sparklines: only with 3+ real snapshots, and labelled as direction only", async ({ page }) => {
  const w = watch(page);
  await mockApi(page);
  await open(page);
  const t = page.getByTestId("val-trends");
  await expect(t).toContainText("not a significance claim");
  await expect(t).toHaveAttribute("data-signature", "data");
  const imgs = await t.getByRole("img").all();
  expect(imgs).toHaveLength(3); // pre-funding share has only 2 numbers: no line
  for (const img of imgs) expect(((await img.getAttribute("aria-label")) ?? "").split(",").length).toBeGreaterThanOrEqual(3);
  await expect(t.getByRole("img").first()).toHaveAttribute("aria-label", "first seen this month: 9, 10, 12, 13, 14");
  w.expectClean();
});

test("reduced motion: the sparklines are final at once", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page);
  await open(page);
  const lines = await page.locator("path.pz-trace").all();
  expect(lines.length).toBeGreaterThanOrEqual(3);
  for (const l of lines) expect(Number(await l.evaluate((el) => getComputedStyle(el).strokeDashoffset.replace("px", "")))).toBe(0);
  await question(page, "Are we right?");
  const long = await page.evaluate(() => document.getAnimations().filter((a) => Number(a.effect?.getComputedTiming().endTime ?? 0) > 50).length);
  expect(long).toBe(0);
});

/* ------------------------------------------------------------------ the writes are deferred (027b), the reads still work */
test("validation: every write control is visible and disabled with its reason; nothing is written", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  let dialogs = 0;
  page.on("dialog", (d) => {
    dialogs++;
    void d.dismiss();
  });
  await open(page);

  await expectDeferred(page, { testId: "record-outcome" });
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByTestId("more-actions").locator("summary").click();
  await expect(page.getByTestId("record-miss")).toBeVisible();
  await expect(page.getByTestId("record-miss")).toBeDisabled();
  await expect(page.getByTestId("record-miss")).toHaveAttribute("title", WRITES);
  await page.keyboard.press("Escape");

  await question(page, "Are we right?");
  await expect(page.getByTestId("val-outcomes")).toContainText("Aurelith Systems");
  await expectDeferred(page, { name: "Retract" });

  await question(page, "Which sources work?");
  const panel = page.getByTestId("val-benchmarks");
  await expect(panel).toContainText("No private database access is assumed");
  await panel.getByText("Import a benchmark export").click();
  await panel.getByPlaceholder("Dealroom").fill("Dealroom");
  await panel.locator("textarea").fill("Name,Date added\nKestrel Labs,2026-07-01\nFuture Co,2099-01-01\n");
  await expectDeferred(page, { name: "Preview" });
  await expect(panel.getByRole("button", { name: /^Import \d+ dates$/ })).toHaveCount(0);
  await expect(page.getByTestId("val-news-deferred")).toHaveText(NEWS);

  await question(page, "Where do we miss?");
  await expect(page.getByTestId("val-misses")).toContainText("Orbelle Health");
  await expectDeferred(page, { testId: "record-fp" });
  await page.getByTestId("scout-packet").click();
  await expect(page.getByTestId("scout-packet-text")).toContainText("PROJECT ZERO → CHIEF SCOUT 00");
  await expect(page.getByTestId("scout-packet-text")).toContainText("Orbelle Health"); // misses are fed back to the scouts
  await expect(page.getByTestId("scout-packet-text")).toContainText(`- not available: ${NEWS}`);
  await expect(page.getByTestId("scout-packet-deferred")).toContainText(NEWS);
  await expectDeferred(page, { testId: "scout-packet-copy" });

  await question(page, "What does it cost?");
  await expect(page.getByTestId("val-native-bridge")).toContainText("Native search bridge — production pilot");
  await expect(page.getByTestId("val-native-bridge-deferred")).toContainText("Scout search bridge");

  await page.waitForTimeout(300);
  expect(dialogs).toBe(0);
  expect(api.writes()).toEqual([]);
  expect(api.reads()).toEqual(["GET /api/validation", "GET /api/validation/scout_packet?cycle=c-2026-10-16"]);
  w.expectClean();
});

/* ------------------------------------------------------------------ layout: 150 %, 1366, 1920 and the phone */
async function everyQuestionFits(page: Page) {
  await expectNoHorizontalOverflow(page);
  await expand(page, "val-measurement-d");
  await expectNoHorizontalOverflow(page);
  for (const q of QUESTIONS) {
    await question(page, q);
    await expect(questions(page).getByRole("tab", { name: q })).toHaveAttribute("aria-selected", "true");
    await expectNoHorizontalOverflow(page);
  }
}

test("validation fits 150% zoom", async ({ page }) => {
  await zoom150(page);
  await mockApi(page);
  await open(page);
  await everyQuestionFits(page);
});

for (const [w, h] of [
  [1366, 768],
  [1920, 1080],
]) {
  test(`validation fits ${w}px`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await mockApi(page);
    await open(page);
    await everyQuestionFits(page);
  });
}

test("validation stays inside a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await open(page);
  await everyQuestionFits(page);
  // the measurement rows stack on a phone (badge above the text)
  const row = page.getByTestId("val-measure").first();
  const cols = await row.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
  expect(cols).toBe(1);
});
