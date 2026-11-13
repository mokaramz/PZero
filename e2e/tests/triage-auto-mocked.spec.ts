/**
 * Machine triage after a scan on the Deal Flow page (review 035b) — the old `AutoTriageStatus` line in the FindBar,
 * "Retry now (N)" and the candidate detail's pending section — with the API MOCKED by route interception, so no backend
 * is needed: only the frontend (`npm run dev` in frontend/, or PZ_BASE_URL). Every company and reason in
 * fixtures/triage_auto/ is invented (byte-identical copies of `frontend/src/features/deal-flow/test/triage_auto/*.json`),
 * in the scan's world (fixtures/scan/inbox.json).
 *
 * Covered: a run going when the page opens is polled, then its sentence and its toast once, with the triage view read
 * again; a partial run (amber, Retry now (2)), nothing posted before the click, then the post, the old started toast,
 * the retry run and its sentence; each old refusal as the toast; the pending section of a candidate kept for a retry;
 * no horizontal overflow at 1366, 1920, 390 and 150 %.
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test triage-auto-mocked
 */
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expand, expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures/triage_auto");
const SCAN = resolve(import.meta.dirname, "fixtures/scan");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (dir: string, n: string): J => JSON.parse(readFileSync(resolve(dir, n), "utf8"));
const status = load(FIX, "status.json");
const retryAnswers = load(FIX, "retry.json");

type Case = "none" | "disabled" | "running" | "done" | "partial" | "failed" | "retry_running" | "retry_done";
const RETRY = "/api/deal-flow/triage_retry";
const HEAD = "Machine triage after scan (proposals only — the Attention score is separate):";
const DONE = "Machine triage complete — 3 processed (1 KEEP · 1 WATCH · 1 REJECT) · $0.0031.";
const PARTIAL =
  "Machine triage partially complete — 1 processed (1 KEEP); 2 preserved for automatic retry because the model provider did not answer in time (next try after 22:34) · $0.0012. No data was lost; these are proposals only.";
const RETRY_DONE = "Machine triage complete — 2 processed (1 KEEP · 1 RESEARCH) · $0.0020.";
const RETRY_STARTED = "Retrying the preserved candidates — see Background activity";
const CATCHUP = { running: false, queue: [], current: null, done: [], enabled: true };

/**
 * Mock Deal Flow's reads, the triage status and Retry now. Each `triage_auto` read takes the next answer of `script`
 * (the last one stays); a started Retry now replaces the script with `after`. Anything else under /api is a 404 (the
 * shell's not-ported reads are allowed by `watch`).
 */
async function mockApi(page: Page, { script = ["done"] as Case[], after = [] as Case[], retry = "started" } = {}) {
  const requested: Array<{ method: string; path: string; body: J }> = [];
  page.on("request", (r) => {
    if (!r.url().includes("/api/")) return;
    let body: J = null;
    try {
      body = r.postDataJSON();
    } catch {
      body = null;
    }
    requested.push({ method: r.method(), path: new URL(r.url()).pathname, body });
  });
  const queue = [...script];
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/deal-flow\/inbox(\?.*)?$/, (route) => route.fulfill({ json: load(SCAN, "inbox.json") }));
  await page.route(/\/api\/deal-flow\/triage(\?.*)?$/, (route) => route.fulfill({ json: load(FIX, "triage.json") }));
  await page.route(/\/api\/deal-flow\/find_status(\?.*)?$/, (route) => route.fulfill({ json: load(SCAN, "find_status.json").idle }));
  await page.route(/\/api\/catchup(\?.*)?$/, (route) => route.fulfill({ json: CATCHUP }));
  await page.route(/\/api\/deal-flow\/triage_auto(\?.*)?$/, (route) => route.fulfill({ json: status[queue.length > 1 ? queue.shift()! : queue[0]] }));
  await page.route(/\/api\/deal-flow\/triage_retry$/, (route) => {
    const a = retryAnswers[retry];
    if (a.started && after.length) queue.splice(0, queue.length, ...after);
    return route.fulfill({ json: a });
  });
  const reads = (p: string) => requested.filter((r) => r.method === "GET" && r.path === p).length;
  return { requested, reads, posts: () => requested.filter((r) => r.method === "POST") };
}

async function open(page: Page, url = "/deal-flow") {
  await page.goto(url);
  await expect(page.getByTestId("cand-row").first()).toBeVisible({ timeout: 60_000 });
  await expand(page, "scan-fold");
}

const line = (page: Page) => page.getByTestId("auto-triage-status");
const retryBtn = (page: Page) => page.getByTestId("triage-retry-now");

test.describe("Machine triage after a scan — mocked API", () => {
  test("a run going when the page opens: the running line, polled, then its sentence and toast once; the triage read again", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page, { script: ["running", "running", "done"] });
    await open(page);
    await expect(line(page)).toHaveText(`${HEAD} 3 new or changed candidate(s) — machine triage running…`);
    await expect(retryBtn(page)).toHaveCount(0);
    const triageReads = api.reads("/api/deal-flow/triage");
    await expect(line(page)).toHaveText(`${HEAD} ${DONE}`, { timeout: 15_000 });
    await expect(page.getByRole("status").getByText(DONE, { exact: true })).toHaveCount(1);
    await expect.poll(() => api.reads("/api/deal-flow/triage")).toBeGreaterThan(triageReads);
    expect(api.reads("/api/deal-flow/triage_auto")).toBe(3);
    // done: no more polling
    await page.waitForTimeout(4500);
    expect(api.reads("/api/deal-flow/triage_auto")).toBe(3);
    await expect(page.getByRole("status").getByText(DONE, { exact: true })).toHaveCount(1);
    expect(api.posts()).toEqual([]);
    w.expectClean();
  });

  test("partial: the warning and Retry now (2); nothing before the click, then the post, the started toast and the retry run", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page, { script: ["partial"], after: ["retry_running", "retry_running", "retry_done"] });
    await open(page);
    await expect(line(page)).toHaveText(`⚠ ${HEAD} ${PARTIAL} Retry now (2)`);
    await expect(retryBtn(page)).toHaveText("Retry now (2)");
    await page.waitForLoadState("networkidle");
    const reads = api.reads("/api/deal-flow/triage_auto");
    await page.waitForTimeout(4500);
    expect(api.posts()).toEqual([]);
    expect(api.reads("/api/deal-flow/triage_auto")).toBe(reads); // nothing running: not polled
    await retryBtn(page).click();
    await expect(page.getByText(RETRY_STARTED)).toBeVisible();
    expect(api.posts()).toEqual([{ method: "POST", path: RETRY, body: {} }]);
    await expect(line(page)).toHaveText(`${HEAD} 2 new or changed candidate(s) — machine triage running…`);
    await expect(retryBtn(page)).toHaveCount(0);
    await expect(line(page)).toHaveText(`${HEAD} ${RETRY_DONE}`, { timeout: 15_000 });
    await expect(page.getByRole("status").getByText(RETRY_DONE, { exact: true })).toHaveCount(1);
    await expect(retryBtn(page)).toHaveCount(0);
    expect(api.posts()).toHaveLength(1);
    w.expectClean();
  });

  for (const [answer, reason] of [
    ["nothing_waiting", "Nothing is waiting for a retry."],
    ["in_progress", "A machine triage run is already in progress."],
  ] as const) {
    test(`Retry now refused (${answer}): the server's reason as the toast; the line stays`, async ({ page }) => {
      const w = watch(page);
      const api = await mockApi(page, { script: ["partial"], retry: answer });
      await open(page);
      await retryBtn(page).click();
      await expect(page.getByRole("status").getByText(reason, { exact: true })).toBeVisible();
      await expect(page.getByText(RETRY_STARTED)).toHaveCount(0);
      expect(api.posts()).toEqual([{ method: "POST", path: RETRY, body: {} }]);
      await expect(line(page)).toContainText(PARTIAL);
      await expect(retryBtn(page)).toHaveText("Retry now (2)");
      w.expectClean();
    });
  }

  test("a candidate kept for a retry: the detail's Machine triage pending section with its reason", async ({ page }) => {
    const w = watch(page);
    await mockApi(page, { script: ["partial"] });
    await page.goto("/deal-flow?candidate=s-0102");
    const detail = page.getByTestId("cand-detail");
    await expect(detail.getByRole("heading", { level: 2 })).toHaveText("Fennmoor Grid", { timeout: 60_000 });
    const sec = detail.getByTestId("triage-pending");
    await expect(sec.getByRole("heading", { level: 4 })).toHaveText("Machine triage");
    await expect(sec).toContainText("TRIAGE PENDING: the model provider did not answer in time — kept for an automatic retry after 22:34");
    await expect(detail.getByTestId("triage-panel")).toHaveCount(0);
    w.expectClean();
  });

  /** The partial line with its button in the open fold, then a pending candidate's detail. */
  async function lineAndPending(page: Page) {
    await open(page);
    await expect(retryBtn(page)).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.locator('[data-testid="cand-row"][data-id="s-0102"]').click();
    await expect(page.getByTestId("cand-detail").getByTestId("triage-pending")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }

  for (const [name, size] of [
    ["1366", { width: 1366, height: 768 }],
    ["1920", { width: 1920, height: 1080 }],
    ["390 (phone)", { width: 390, height: 844 }],
  ] as const) {
    test(`no horizontal overflow at ${name}: the partial line with Retry now, and the pending section`, async ({ page }) => {
      const w = watch(page);
      await mockApi(page, { script: ["partial"] });
      await page.setViewportSize(size);
      await lineAndPending(page);
      w.expectClean();
    });
  }

  test("no horizontal overflow at 150 % zoom", async ({ page }) => {
    const w = watch(page);
    await mockApi(page, { script: ["partial"] });
    await zoom150(page);
    await lineAndPending(page);
    w.expectClean();
  });
});
