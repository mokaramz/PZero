/**
 * WATCH on the Watchlist and in the Deal Flow candidate detail (review 037a) — the watched companies panel (rows,
 * badges, the trigger list, the official pages with Save pages, Reviewed / Dismiss) and the "On WATCH — sensors"
 * section — with the API MOCKED by route interception, so no backend is needed: only the frontend (`npm run dev` in
 * frontend/, or PZ_BASE_URL). Every company in fixtures/watch/ is invented (byte-identical copies of
 * `frontend/src/features/watchlist/test/*.json`).
 *
 * Covered: nothing is posted before a click; Save pages posts the pages split on any whitespace and toasts; a refused
 * page is the error toast; Reviewed / Dismiss post `{id, status}`, toast and the refetch shows the status; "Check now"
 * is deferred with the one wording and sends nothing; the Deal Flow section with pages and without; no horizontal
 * overflow at 1366, 1920, 390 and 150 %.
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test watch-mocked
 */
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures/watch");
const SCAN = resolve(import.meta.dirname, "fixtures/scan");
const AUTO = resolve(import.meta.dirname, "fixtures/triage_auto");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (dir: string, n: string): J => JSON.parse(readFileSync(resolve(dir, n), "utf8"));

const TARGET = "/api/watch_target";
const ACK = "/api/watch_ack";
const CHECK_REASON = "Page checks arrive with the WATCH sensors port";
const CATCHUP = { running: false, queue: [], current: null, done: [], enabled: true };
/** Two invented people for the Watchlist's people table. */
const PEOPLE = [
  { id: "p-ilse-marrow", name: "Ilse Marrow", role: "CTO", company: "Halvard Optics", why_interesting: "Built an optics line before", watch: true },
  { id: "p-tomas-quill", name: "Tomas Quill", role: "Researcher", why_interesting: "Enzyme coatings", watch: true },
];
const PUBLIC_URL = /^https?:\/\/[^\s/]+\.[^\s]+/;

/**
 * Mock the Watchlist's and Deal Flow's reads and the two WATCH writes, over one world that keeps what a write applied
 * (so the refetch shows it). Anything else under /api is a 404.
 */
async function mockApi(page: Page) {
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
  const db = load(FIX, "watch.json");
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/catchup(\?.*)?$/, (route) => route.fulfill({ json: CATCHUP }));
  await page.route(/\/api\/network\/watchlist(\?.*)?$/, (route) => route.fulfill({ json: { people: PEOPLE } }));
  await page.route(/\/api\/deal-flow\/inbox(\?.*)?$/, (route) => route.fulfill({ json: load(FIX, "inbox.json") }));
  await page.route(/\/api\/deal-flow\/triage(\?.*)?$/, (route) => route.fulfill({ json: { proposals: {} } }));
  await page.route(/\/api\/deal-flow\/find_status(\?.*)?$/, (route) => route.fulfill({ json: load(SCAN, "find_status.json").idle }));
  await page.route(/\/api\/deal-flow\/triage_auto(\?.*)?$/, (route) => route.fulfill({ json: load(AUTO, "status.json").done }));
  await page.route(/\/api\/watch(\?.*)?$/, (route) => route.fulfill({ json: db }));
  await page.route(/\/api\/watch_target$/, (route) => {
    const body = route.request().postDataJSON();
    const bad = body.urls.find((u: string) => !PUBLIC_URL.test(u));
    if (bad) return route.fulfill({ status: 400, json: { ok: false, error: `not a public http(s) URL: ${bad}` } });
    const c = db.companies.find((x: J) => x.name === body.name);
    c.urls = body.urls.slice(0, 6);
    return route.fulfill({ json: { ok: true, target: { name: body.name, urls: c.urls, candidate_id: body.candidate_id, active: true } } });
  });
  await page.route(/\/api\/watch_ack$/, (route) => {
    const body = route.request().postDataJSON();
    const c = db.companies.find((x: J) => x.triggers.some((t: J) => t.id === body.id));
    const t = c.triggers.find((x: J) => x.id === body.id);
    t.status = body.status;
    c.open = c.triggers.filter((x: J) => x.status === "new").length;
    return route.fulfill({ json: { ok: true, kind: "status", trigger_id: body.id, status: body.status, at: "2026-11-13T10:00:00", note: "" } });
  });
  return { requested, posts: () => requested.filter((r) => r.method === "POST") };
}

const company = (page: Page, name: string) => page.getByTestId("watched-company").filter({ hasText: name });
const trigger = (page: Page, name: string, label: string) => company(page, name).getByTestId("watch-trigger").filter({ hasText: label });

async function openWatchlist(page: Page) {
  await page.goto("/watchlist");
  await expect(page.getByTestId("watched-company")).toHaveCount(3, { timeout: 60_000 });
  await expect(page.getByTestId("watch-row")).toHaveCount(2);
}

test.describe("WATCH — mocked API", () => {
  test("the panel: rows, badges, triggers and pages, with nothing posted on load", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await openWatchlist(page);
    const panel = page.getByTestId("watched-companies");
    await expect(panel).toContainText("Watched companies — WATCH is active, not a graveyard");
    await expect(panel.getByTestId("watch-checks-deferred")).toHaveText(`${CHECK_REASON}.`);
    const halvard = company(page, "Halvard Optics");
    await expect(halvard.getByRole("link", { name: "Halvard Optics" })).toHaveAttribute("href", "/deal-flow?candidate=c-wt-01");
    await expect(halvard.getByText("2 new")).toBeVisible();
    await expect(halvard.getByText("machine triage predates new evidence")).toBeVisible();
    await expect(halvard.getByTestId("watch-trigger")).toHaveCount(4);
    await expect(trigger(page, "Halvard Optics", "Funding round")).toContainText("· page check · first seen 2026-11-12 · dated 2026-11-10");
    await expect(trigger(page, "Halvard Optics", "Pilot")).toContainText("· new source in a scan");
    await expect(company(page, "Brisa Hydrogen")).toContainText("No triggers yet.");
    await halvard.getByText("Official pages to watch (2)").click();
    await expect(halvard.getByTestId("watch-page-check")).toHaveText([
      "https://halvard-optics.example/news: changed · 2026-11-12T08:00:00",
      "https://halvard-optics.example/careers: failed · 2026-11-12T08:00:05 · 2 failure(s) in a row: HTTP 503",
    ]);
    await page.waitForTimeout(500);
    expect(api.posts()).toEqual([]);
    w.expectClean();
  });

  test("Save pages posts the pages split on any whitespace, toasts, and the summary counts them", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await openWatchlist(page);
    const brisa = company(page, "Brisa Hydrogen");
    await brisa.getByText("Official pages to watch (0)").click();
    await brisa.getByLabel("Pages to watch for Brisa Hydrogen").fill(" https://brisa-hydrogen.example/news\n\nhttps://brisa-hydrogen.example/jobs   https://brisa-hydrogen.example/product ");
    await page.waitForTimeout(300);
    expect(api.posts()).toEqual([]);
    await brisa.getByRole("button", { name: "Save pages" }).click();
    await expect(page.getByText("Pages saved — first check records a baseline")).toBeVisible();
    expect(api.posts()).toEqual([
      {
        method: "POST",
        path: TARGET,
        body: { name: "Brisa Hydrogen", urls: ["https://brisa-hydrogen.example/news", "https://brisa-hydrogen.example/jobs", "https://brisa-hydrogen.example/product"], candidate_id: "" },
      },
    ]);
    await expect(brisa.getByText("Official pages to watch (3)")).toBeVisible();
    w.expectClean();
  });

  test("a refused page is the error toast; the text stays", async ({ page }) => {
    const w = watch(page, { expected: [400] });
    const api = await mockApi(page);
    await openWatchlist(page);
    const brisa = company(page, "Brisa Hydrogen");
    await brisa.getByText("Official pages to watch (0)").click();
    const box = brisa.getByLabel("Pages to watch for Brisa Hydrogen");
    await box.fill("ftp://brisa-hydrogen.example/files");
    await brisa.getByRole("button", { name: "Save pages" }).click();
    await expect(page.getByText("✕ Saving watched pages failed — not a public http(s) URL: ftp://brisa-hydrogen.example/files")).toBeVisible();
    expect(api.posts()).toHaveLength(1);
    await expect(box).toHaveValue("ftp://brisa-hydrogen.example/files");
    await expect(brisa.getByText("Official pages to watch (0)")).toBeVisible();
    w.expectClean();
  });

  test("Reviewed and Dismiss post {id, status}, toast, and the refetch shows the status", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await openWatchlist(page);
    await trigger(page, "Halvard Optics", "Funding round").getByRole("button", { name: "Reviewed" }).click();
    await expect(page.getByText("Trigger updated (kept on record)")).toBeVisible();
    await expect(trigger(page, "Halvard Optics", "Funding round")).toHaveAttribute("data-status", "reviewed");
    await expect(trigger(page, "Halvard Optics", "Funding round")).toContainText("· reviewed");
    await expect(company(page, "Halvard Optics").getByText("1 new")).toBeVisible();
    await trigger(page, "Halvard Optics", "Pilot").getByRole("button", { name: "Dismiss" }).click();
    await expect(trigger(page, "Halvard Optics", "Pilot")).toHaveAttribute("data-status", "dismissed");
    expect(api.posts()).toEqual([
      { method: "POST", path: ACK, body: { id: "wt-a1b2c3d4e5f6", status: "reviewed" } },
      { method: "POST", path: ACK, body: { id: "wt-b2c3d4e5f6a7", status: "dismissed" } },
    ]);
    await expect(company(page, "Halvard Optics").getByText(/^\d+ new$/)).toHaveCount(0);
    w.expectClean();
  });

  test("Check now is deferred with the one wording and sends nothing", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await openWatchlist(page);
    const checks = page.getByTestId("watch-check");
    await expect(checks).toHaveCount(3);
    for (const b of await checks.all()) {
      await expect(b).toHaveAttribute("aria-disabled", "true");
      await expect(b).toHaveAttribute("title", CHECK_REASON);
      await b.click({ force: true });
    }
    await checks.first().focus();
    await page.keyboard.press("Enter");
    await page.keyboard.press("Space");
    await page.waitForTimeout(500);
    expect(api.posts()).toEqual([]);
    expect(api.requested.some((r) => r.path.includes("watch_check"))).toBe(false);
    w.expectClean();
  });

  test("Deal Flow: the WATCH section with pages and without, the Watchlist link, and Reviewed from there", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await page.goto("/deal-flow?candidate=c-wt-01");
    const detail = page.getByTestId("cand-detail");
    await expect(detail.getByRole("heading", { level: 2 })).toHaveText("Halvard Optics", { timeout: 60_000 });
    const section = page.getByTestId("watch-section");
    await expect(section).toContainText("On WATCH — sensors");
    await expect(section).toContainText("2 official page(s) watched · manage on Watchlist");
    await expect(section.getByRole("link", { name: "manage on Watchlist" })).toHaveAttribute("href", "/watchlist");
    await expect(section.getByTestId("watch-checks-deferred")).toHaveText(`${CHECK_REASON}.`);
    await expect(section.getByTestId("watch-trigger")).toHaveCount(4);
    await expect(section.getByRole("button", { name: "Check now" })).toHaveCount(0);
    await section.getByTestId("watch-trigger").first().getByRole("button", { name: "Reviewed" }).click();
    await expect(page.getByText("Trigger updated (kept on record)")).toBeVisible();
    await expect(section.getByTestId("watch-trigger").first()).toHaveAttribute("data-status", "reviewed");
    expect(api.posts()).toEqual([{ method: "POST", path: ACK, body: { id: "wt-a1b2c3d4e5f6", status: "reviewed" } }]);

    await page.locator('[data-testid="cand-row"][data-id="c-wt-03"]').click();
    await expect(detail.getByRole("heading", { level: 2 })).toHaveText("Quellbrook Labs");
    await expect(section).toContainText("No official pages attached yet — scans still watch for new sources · manage on Watchlist");
    await expect(section.getByTestId("watch-trigger")).toHaveCount(1);
    expect(api.posts()).toHaveLength(1);
    w.expectClean();
  });

  for (const [name, size] of [
    ["1366", { width: 1366, height: 768 }],
    ["1920", { width: 1920, height: 1080 }],
    ["390 (phone)", { width: 390, height: 844 }],
    ["150 % zoom", null],
  ] as const) {
    test(`no horizontal overflow at ${name}: the panel with its pages open, and the Deal Flow section`, async ({ page }) => {
      const w = watch(page);
      await mockApi(page);
      if (size) await page.setViewportSize(size);
      else await zoom150(page);
      await openWatchlist(page);
      await company(page, "Halvard Optics").getByText("Official pages to watch (2)").click();
      await expect(company(page, "Halvard Optics").getByTestId("watch-page-check")).toHaveCount(2);
      await expectNoHorizontalOverflow(page);
      await page.goto("/deal-flow?candidate=c-wt-01");
      await expect(page.getByTestId("watch-section").getByTestId("watch-trigger")).toHaveCount(4, { timeout: 60_000 });
      await expectNoHorizontalOverflow(page);
      w.expectClean();
    });
  }
});
