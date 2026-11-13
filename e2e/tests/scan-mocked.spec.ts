/**
 * The Deal Flow scan (review 034a) on the page — Find New Candidates, the polling, the finish toast, the per-source
 * report and the scan history — with the API MOCKED by route interception, so no backend is needed: only the frontend
 * (`npm run dev` in frontend/, or PZ_BASE_URL). Every source, company and note in fixtures/scan/ is invented
 * (byte-identical copies of `frontend/src/features/deal-flow/test/scan/*.json`); the old e2e it ports is the scan part
 * of the old `deal-flow.spec.ts` ("Find New Candidates: progress, then the ledger toast", the scan ledger, the
 * `?find=1` deep link).
 *
 * Covered: a click posts `find {days}`, the running label and progress while `find_status` is polled, then the finish
 * toast with the declared refusal, the fresh inbox, the catch-up and the post-scan triage status read again (the triage
 * view only once a new triage run finished — covered by `triage-auto-mocked.spec.ts`); a scan started elsewhere is picked up on load, and a stopped one gives the old error toast; the report (the
 * workspace's geographies, the failed source, the refused row, the ledger) and the lazy history; `?find=1` focuses Find
 * and posts nothing; no horizontal overflow at 1366, 1920, 390 and 150 %.
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test scan-mocked
 */
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expand, expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures/scan");
const AUTO = resolve(import.meta.dirname, "fixtures/triage_auto");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (n: string): J => JSON.parse(readFileSync(resolve(FIX, n), "utf8"));

type Case = "idle" | "running" | "running_more" | "done" | "stopped";
const DONE_TOAST = "2 genuinely new (1 pre-company) · 4 baseline · 1 noise · 9 already known · 1 existing pipeline · 1 refused by the intake";
/** The post-scan machine-triage line (review 035b) for the previous scan's run (fixtures/triage_auto/status.json). */
const AUTO_DONE = "Machine triage after scan (proposals only — the Attention score is separate): Machine triage complete — 3 processed (1 KEEP · 1 WATCH · 1 REJECT) · $0.0031.";
const TRIAGE = { architecture: { prompt_version: "v3" }, proposals: {}, counts: {}, calibration: { decisions: 0, agreement: null }, note: "Proposals only." };
const CATCHUP = { running: false, queue: [], current: null, done: [], enabled: true };

/** The inbox a read finds after the `done` scan: its run, summary and report, and its two new companies. */
function afterScan(): J {
  const ib = load("inbox.json");
  const done = load("find_status.json").done;
  const r = done.result;
  const fresh = r.new_companies.map((n: J) => ({ id: n.id, name: n.name, decision: "new", pz_status: "new", source: n.source, location: "Berlin, Germany", run_id: r.run_id, first_seen: n.first_seen }));
  return { ...ib, candidates: [...fresh, ...ib.candidates], last_run: r.run_id, last_summary: r, report: done.rows };
}

/**
 * Mock Deal Flow's reads and the scan. `find_status` answers `before` until `POST find` starts a scan, then each read
 * takes the next answer of `script` (the last one stays). The inbox is the scanned one, and the fresh one once the scan
 * is done. Anything else under /api is a 404 (the shell's not-ported reads are allowed by `watch`).
 */
async function mockApi(page: Page, { before = "idle" as Case, script = ["running", "running", "running_more", "done"] as Case[], find = "started" } = {}) {
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
  const status = load("find_status.json");
  const state = { started: before !== "idle", queue: [...script], last: before };
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/deal-flow\/inbox(\?.*)?$/, (route) => route.fulfill({ json: state.last === "done" ? afterScan() : load("inbox.json") }));
  await page.route(/\/api\/deal-flow\/triage(\?.*)?$/, (route) => route.fulfill({ json: TRIAGE }));
  await page.route(/\/api\/catchup(\?.*)?$/, (route) => route.fulfill({ json: CATCHUP }));
  await page.route(/\/api\/deal-flow\/triage_auto(\?.*)?$/, (route) => route.fulfill({ json: JSON.parse(readFileSync(resolve(AUTO, "status.json"), "utf8")).done }));
  await page.route(/\/api\/deal-flow\/find_status(\?.*)?$/, (route) => {
    if (state.started) state.last = state.queue.length > 1 ? state.queue.shift()! : state.queue[0];
    return route.fulfill({ json: status[state.last] });
  });
  await page.route(/\/api\/deal-flow\/find$/, (route) => {
    state.started = true;
    return route.fulfill({ json: load("find_answers.json")[find] });
  });
  await page.route(/\/api\/deal-flow\/scan_history(\?.*)?$/, (route) => route.fulfill({ json: load("scan_history.json") }));
  const reads = (p: string) => requested.filter((r) => r.method === "GET" && r.path === p).length;
  return { state, requested, reads, posts: () => requested.filter((r) => r.method === "POST") };
}

async function open(page: Page, url = "/deal-flow") {
  await page.goto(url);
  await expect(page.getByTestId("cand-row").first()).toBeVisible({ timeout: 60_000 });
}

const findBtn = (page: Page) => page.getByTestId("find-btn");

test.describe("Deal Flow scan — mocked API", () => {
  test("Find New Candidates: the post, the polled progress, then the finish toast, the fresh inbox and the triage status", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    await expect(findBtn(page)).toHaveText("Find New Candidates");
    await expect(page.getByLabel("Feed window")).toHaveValue("7");
    const inboxReads = api.reads("/api/deal-flow/inbox");
    const catchupReads = api.reads("/api/catchup");
    const triageReads = api.reads("/api/deal-flow/triage");
    const autoReads = api.reads("/api/deal-flow/triage_auto");
    await page.getByLabel("Feed window").selectOption("14");
    await findBtn(page).click();
    await expect(findBtn(page)).toHaveText("Scanning 2 / 7…");
    await expect(findBtn(page)).toBeDisabled();
    await expect(page.getByTestId("find-status")).toContainText("Scanning 2 / 7 — sources run concurrently; slow ones cannot block the rest.");
    await expect(page.getByTestId("scan-progress")).toContainText("✓ Isarwerk Venture Lab");
    await expect(page.getByTestId("scan-progress")).toContainText("✕ Halden Feed");
    await expect(findBtn(page)).toHaveText("Scanning 5 / 7…");
    expect(api.posts()).toEqual([{ method: "POST", path: "/api/deal-flow/find", body: { days: "14" } }]);

    await expect(page.getByText(DONE_TOAST)).toBeVisible({ timeout: 15_000 });
    await expect(findBtn(page)).toHaveText("Find New Candidates");
    expect(api.reads("/api/deal-flow/find_status")).toBeGreaterThanOrEqual(4);
    await expect.poll(() => api.reads("/api/deal-flow/inbox")).toBeGreaterThan(inboxReads);
    await expect.poll(() => api.reads("/api/catchup")).toBeGreaterThan(catchupReads);
    await expand(page, "scan-fold");
    await expect(page.getByTestId("find-status")).toContainText("Last run 2026-11-13 09:30 — 2 genuinely new (1 from pre-company channels)");
    await expect(page.getByTestId("scan-ledger")).toContainText("Scan ledger 2026-11-13 09:30");
    await expect(page.getByTestId("scan-ledger")).toContainText("genuinely new 2");
    await expect(page.getByTestId("auto-triage-status")).toHaveText(AUTO_DONE);
    // the scan's polling has stopped; the triage status is watched (no new triage run here, so the triage view is not read again)
    const after = api.reads("/api/deal-flow/find_status");
    await page.waitForTimeout(3000);
    expect(api.reads("/api/deal-flow/find_status")).toBe(after);
    expect(api.reads("/api/deal-flow/triage_auto")).toBeGreaterThan(autoReads + 1);
    expect(api.reads("/api/deal-flow/triage")).toBe(triageReads);
    expect(api.posts()).toHaveLength(1);
    w.expectClean();
  });

  test("a scan started elsewhere is picked up on load and polled; a stopped scan gives the old error toast", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page, { before: "running", script: ["running", "running", "stopped"] });
    await open(page);
    await expect(findBtn(page)).toHaveText("Scanning 2 / 7…");
    await expect(page.getByTestId("scan-fold")).toHaveAttribute("open", "");
    await expect(page.getByText("Scan stopped: the source registry could not be read — nothing was half-saved; start it again when ready")).toBeVisible({
      timeout: 15_000,
    });
    await expect(findBtn(page)).toHaveText("Find New Candidates");
    expect(api.posts()).toEqual([]);
    w.expectClean();
  });

  test("Find while a scan is already running: the old note, then its progress", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page, { script: ["running", "done"], find: "running" });
    await open(page);
    await findBtn(page).click();
    await expect(page.getByText("Scan already running — showing progress")).toBeVisible();
    await expect(page.getByText(DONE_TOAST)).toBeVisible({ timeout: 15_000 });
    expect(api.posts()).toHaveLength(1);
    w.expectClean();
  });

  test("the report: the workspace's geographies, the failed source, the refused row, the ledger; the history opens lazily", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    await expand(page, "scan-fold");
    const rep = page.getByTestId("scan-report");
    await expect(rep).toContainText("7 sources · 5 healthy · 1 failed · 1 disabled");
    await expect(rep).toContainText("showing Europe (5)");
    await expect(page.getByTestId("scan-outcome")).toContainText("Halden Feed — the publisher's server had an error");
    await rep.getByText("Show source details").click();
    const bw = rep.locator('[data-testid="scan-rep-row"][data-source="Brightwater Registry"]');
    await expect(bw).toContainText("1 item(s) refused by the intake: the name is not a company name · raw 5 · records 4 · 1 refused by the intake");
    await expect(rep.getByTestId("scan-rep-refused")).toHaveCount(1);
    await expect(rep.locator('[data-source="Prairie SBIR awards"]')).toBeHidden();
    await rep.getByText("Show all 7 rows (other geographies)").click();
    await expect(rep.locator('[data-source="Prairie SBIR awards"]')).toBeVisible();
    const led = page.getByTestId("scan-ledger");
    await expect(led).toContainText("sources attempted 6");
    await expect(led).toContainText("raw records retrieved 61");
    await expect(led).toContainText("Existing pipeline — not discovered in this scan: 2 (Varnholt Systems, Ellery Foods)");
    await expect(led).toContainText("Tamberlane Optics (Prairie SBIR awards · source date UNKNOWN");
    await expect(page.getByTestId("auto-triage-status")).toHaveText(AUTO_DONE);
    await page.locator('[data-ws="na"]').click();
    await expect(rep).toContainText("showing North America (3)");

    expect(api.requested.some((r) => r.path.includes("scan_history"))).toBe(false);
    const h = page.getByTestId("scan-history");
    await h.locator("summary").click();
    const table = page.getByTestId("scan-history-table");
    await expect(table.locator("th")).toHaveText(["Scan", "Sources ok / failed / off", "Raw", "New", "Already known", "Merged", "Baseline", "Existing pipeline — not discovered in this scan"]);
    await expect(table.locator("tbody tr").first().locator("td")).toHaveText(["2026-11-12 22:15", "5 / 1 / 1", "61", "3", "11", "3", "0", "2"]);
    await expect(h).toContainText("14 scans recorded in total · showing the latest 2.");
    expect(api.requested.filter((r) => r.path.includes("scan_history")).map((r) => r.path)[0]).toBe("/api/deal-flow/scan_history?n=10");
    expect(api.posts()).toEqual([]);
    w.expectClean();
  });

  test("?find=1 scrolls to and focuses the live Find control, and never starts a scan", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await page.setViewportSize({ width: 1366, height: 500 });
    await open(page, "/deal-flow?find=1");
    await expect(findBtn(page)).toBeFocused();
    await expect(findBtn(page)).toBeInViewport();
    await expect(findBtn(page)).toBeEnabled();
    await expect(findBtn(page)).not.toHaveAttribute("aria-disabled");
    await expect(page).toHaveURL(/\/deal-flow$/);
    await page.waitForTimeout(500);
    expect(api.posts()).toEqual([]);
    w.expectClean();
  });

  /** Everything open: the fold, the source details, the other geographies, the history. */
  async function unfoldAll(page: Page) {
    await expand(page, "scan-fold");
    const rep = page.getByTestId("scan-report");
    await rep.getByText("Show source details").click();
    await rep.getByText("Show all 7 rows (other geographies)").click();
    await page.getByTestId("scan-history").locator("summary").click();
    await expect(page.getByTestId("scan-history-table")).toBeVisible();
  }

  for (const [name, size] of [
    ["1366", { width: 1366, height: 768 }],
    ["1920", { width: 1920, height: 1080 }],
    ["390 (phone)", { width: 390, height: 844 }],
  ] as const) {
    test(`no horizontal overflow at ${name}: the report, the history and a running scan`, async ({ page }) => {
      const w = watch(page);
      await mockApi(page, { script: ["running_more"] });
      await page.setViewportSize(size);
      await open(page);
      await unfoldAll(page);
      await expectNoHorizontalOverflow(page);
      await findBtn(page).click();
      await expect(page.getByTestId("scan-progress")).toContainText("Brightwater Registry");
      await expectNoHorizontalOverflow(page);
      w.expectClean();
    });
  }

  test("no horizontal overflow at 150 % zoom", async ({ page }) => {
    const w = watch(page);
    await mockApi(page, { script: ["running_more"] });
    await zoom150(page);
    await open(page);
    await unfoldAll(page);
    await expectNoHorizontalOverflow(page);
    await findBtn(page).click();
    await expect(page.getByTestId("scan-progress")).toContainText("Brightwater Registry");
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });
});
