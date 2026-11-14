/**
 * WATCH on the Watchlist and in the Deal Flow candidate detail (reviews 037a and 037b) — the watched companies panel
 * (rows, badges, the trigger list, the official pages with Save pages, Check now, Reviewed / Dismiss) and the "On WATCH — sensors"
 * section — with the API MOCKED by route interception, so no backend is needed: only the frontend (`npm run dev` in
 * frontend/, or PZ_BASE_URL). Every company in fixtures/watch/ is invented (byte-identical copies of
 * `frontend/src/features/watchlist/test/*.json`).
 *
 * Covered: nothing is posted before a click; Save pages posts the pages split on any whitespace and toasts; a refused
 * page is the error toast; Reviewed / Dismiss post `{id, status}`, toast and the refetch shows the status; "Check now"
 * (037b) posts `{name}` and toasts "{fired} new trigger(s)" with " · {failures} page(s) failed" and " · {skipped}
 * page(s) left for the next run" only when non-zero, the refetch shows what fired, and the busy 409 is the error toast;
 * no deferral line anywhere; the Deal Flow section (no Check now, as before) with pages and without; no horizontal
 * overflow at 1366, 1920, 390 and 150 %, after a Check now toast too.
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
const CHECK = "/api/watch_check";
const CHECK_AT = "2026-11-13T10:05:00";
const BUSY = "A WATCH check is already running.";
const CATCHUP = { running: false, queue: [], current: null, done: [], enabled: true };
/** Two invented people for the Watchlist's people table. */
const PEOPLE = [
  { id: "p-ilse-marrow", name: "Ilse Marrow", role: "CTO", company: "Halvard Optics", why_interesting: "Built an optics line before", watch: true },
  { id: "p-tomas-quill", name: "Tomas Quill", role: "Researcher", why_interesting: "Enzyme coatings", watch: true },
];
const PUBLIC_URL = /^https?:\/\/[^\s/]+\.[^\s]+/;

/** A Check now answer: `{status, json}`; it may change the world first (a new trigger, a failed check). */
type CheckRoute = (body: J, db: J) => { status?: number; json: J };

/** The default Check now: each of the named company's pages checked "unchanged", nothing fired. */
const unchanged: CheckRoute = (body, db) => {
  const c = db.companies.find((x: J) => x.name === body.name);
  const urls: string[] = c ? c.urls : [];
  for (const u of urls) c.checks[u] = { last_checked: CHECK_AT, last_state: "unchanged", last_ok: CHECK_AT, failures_in_row: 0, last_error: "" };
  return { json: { fired: 0, pages: urls.map((url) => ({ entity: c.name, url, state: "unchanged", fired: [], new_lines: 0, error: "" })), failures: 0, skipped: 0 } };
};

/**
 * Mock the Watchlist's and Deal Flow's reads and the three WATCH writes, over one world that keeps what a write applied
 * (so the refetch shows it). Anything else under /api is a 404.
 */
async function mockApi(page: Page, check: CheckRoute = unchanged) {
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
  await page.route(/\/api\/watch_check$/, (route) => {
    const a = check(route.request().postDataJSON(), db);
    return route.fulfill({ status: a.status ?? 200, json: a.json });
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
    await expect(panel.getByTestId("watch-checks-deferred")).toHaveCount(0);
    await expect(panel).not.toContainText("Page checks arrive");
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

  test("Check now on every row: a company with no pages answers '0 new trigger(s)'; nothing is posted before a click", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await openWatchlist(page);
    const checks = page.getByTestId("watch-check");
    await expect(checks).toHaveCount(3);
    for (const b of await checks.all()) {
      await expect(b).toBeEnabled();
      await expect(b).not.toHaveAttribute("aria-disabled", "true");
      await expect(b).not.toHaveAttribute("title");
    }
    await page.waitForTimeout(300);
    expect(api.posts()).toEqual([]);
    await company(page, "Brisa Hydrogen").getByRole("button", { name: "Check now" }).click();
    await expect(page.getByText("0 new trigger(s)", { exact: true })).toBeVisible();
    expect(api.posts()).toEqual([{ method: "POST", path: CHECK, body: { name: "Brisa Hydrogen" } }]);
    w.expectClean();
  });

  test("Check now fired: the toast counts it and the refetch shows the new trigger and the page's check", async ({ page }) => {
    const w = watch(page);
    const news = "https://halvard-optics.example/news";
    const api = await mockApi(page, (body, db) => {
      const c = db.companies.find((x: J) => x.name === body.name);
      const t = {
        ...c.triggers[0],
        id: "wt-c9d8e7f6a5b4",
        predicate: "customer",
        label: "Customer",
        high_value: false,
        source_date: "2026-11-13",
        first_observed: CHECK_AT,
        evidence: "Halvard Optics signs an invented regional rail operator as its first inspection-camera customer.",
        status: "new",
      };
      c.triggers.unshift(t);
      c.open += 1;
      c.checks[news] = { last_checked: CHECK_AT, last_state: "changed", last_ok: CHECK_AT, failures_in_row: 0 };
      return { json: { fired: 1, pages: [{ entity: c.name, url: news, state: "changed", fired: [t], new_lines: 1, error: "" }], failures: 0, skipped: 0 } };
    });
    await openWatchlist(page);
    const halvard = company(page, "Halvard Optics");
    const reads = api.requested.filter((r) => r.path === "/api/watch").length;
    await halvard.getByRole("button", { name: "Check now" }).click();
    await expect(page.getByText("1 new trigger(s)", { exact: true })).toBeVisible();
    expect(api.posts()).toEqual([{ method: "POST", path: CHECK, body: { name: "Halvard Optics" } }]);
    await expect(halvard.getByText("3 new")).toBeVisible();
    await expect(halvard.getByTestId("watch-trigger").filter({ hasText: "first inspection-camera customer" })).toContainText("· page check · first seen 2026-11-13 · dated 2026-11-13");
    expect(api.requested.filter((r) => r.path === "/api/watch").length).toBeGreaterThan(reads);
    await halvard.getByText("Official pages to watch (2)").click();
    await expect(halvard.getByTestId("watch-page-check").first()).toHaveText(`${news}: changed · ${CHECK_AT}`);
    w.expectClean();
  });

  test("Check now with failures and with pages left at the deadline: the two suffixes, and the failure streak", async ({ page }) => {
    const w = watch(page);
    const careers = "https://halvard-optics.example/careers";
    let skipped = 0;
    await mockApi(page, (body, db) => {
      const c = db.companies.find((x: J) => x.name === body.name);
      c.checks[careers] = { last_checked: CHECK_AT, last_state: "failed", failures_in_row: 3, last_error: "HTTP 503" };
      return { json: { fired: 0, pages: [{ entity: c.name, url: careers, state: "failed", fired: [], error: "HTTPError: HTTP 503" }], failures: 1, skipped: skipped++ } };
    });
    await openWatchlist(page);
    const halvard = company(page, "Halvard Optics");
    await halvard.getByRole("button", { name: "Check now" }).click();
    await expect(page.getByText("0 new trigger(s) · 1 page(s) failed", { exact: true })).toBeVisible();
    await expect(page.getByText(/left for the next run/)).toHaveCount(0);
    await halvard.getByText("Official pages to watch (2)").click();
    await expect(halvard.getByTestId("watch-page-check").nth(1)).toHaveText(`${careers}: failed · ${CHECK_AT} · 3 failure(s) in a row: HTTP 503`);
    await expect(halvard.getByRole("button", { name: "Check now" })).toBeEnabled();
    await halvard.getByRole("button", { name: "Check now" }).click();
    await expect(page.getByText("0 new trigger(s) · 1 page(s) failed · 1 page(s) left for the next run", { exact: true })).toBeVisible();
    w.expectClean();
  });

  test("Check now while a check runs: the busy 409 is the error toast and nothing changes", async ({ page }) => {
    const w = watch(page, { expected: [409] });
    const api = await mockApi(page, () => ({ status: 409, json: { ok: false, error: BUSY } }));
    await openWatchlist(page);
    const halvard = company(page, "Halvard Optics");
    await halvard.getByRole("button", { name: "Check now" }).click();
    await expect(page.getByText(`✕ Checking watched pages failed — ${BUSY}`)).toBeVisible();
    expect(api.posts()).toEqual([{ method: "POST", path: CHECK, body: { name: "Halvard Optics" } }]);
    await expect(page.getByText(/new trigger\(s\)/)).toHaveCount(0);
    await expect(halvard.getByText("2 new")).toBeVisible();
    await expect(halvard.getByRole("button", { name: "Check now" })).toBeEnabled();
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
    await expect(section.getByTestId("watch-checks-deferred")).toHaveCount(0);
    await expect(section).not.toContainText("Page checks arrive");
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
    test(`no horizontal overflow at ${name}: the panel with its pages open, after a Check now toast, and the Deal Flow section`, async ({ page }) => {
      const w = watch(page);
      await mockApi(page, () => ({ json: { fired: 12, pages: [], failures: 3, skipped: 4 } }));
      if (size) await page.setViewportSize(size);
      else await zoom150(page);
      await openWatchlist(page);
      await company(page, "Halvard Optics").getByText("Official pages to watch (2)").click();
      await expect(company(page, "Halvard Optics").getByTestId("watch-page-check")).toHaveCount(2);
      await expectNoHorizontalOverflow(page);
      await company(page, "Halvard Optics").getByRole("button", { name: "Check now" }).click();
      await expect(page.getByText("12 new trigger(s) · 3 page(s) failed · 4 page(s) left for the next run")).toBeVisible();
      await expect(company(page, "Halvard Optics").getByRole("button", { name: "Check now" })).toBeVisible();
      await expectNoHorizontalOverflow(page);
      await page.goto("/deal-flow?candidate=c-wt-01");
      await expect(page.getByTestId("watch-section").getByTestId("watch-trigger")).toHaveCount(4, { timeout: 60_000 });
      await expectNoHorizontalOverflow(page);
      w.expectClean();
    });
  }
});
