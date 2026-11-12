/**
 * Map (review 025) — the new app on a preview database (the real snapshot in a scratch schema; the Map only reads).
 * The OpenFreeMap tiles and fonts, the page's only external requests (decision h), are blocked, so the page shows its
 * plain-canvas fallback and the run never touches the internet. Opportunity mode with an ecosystem's "Why here?" and a
 * sourcing-day plan (exactly one POST, nothing stored), Explore with its layers, the search, the `?event=` deep link,
 * and the layout at the usual sizes. The MSW page tests cover the filters and every panel in detail.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, zoom150 } from "./helpers";

type Intel = { ecosystems: Array<{ city: string; state: string; reasons: string[] }> };

async function blockTiles(page: Page) {
  await page.route(/openfreemap\.org/, (route) => route.abort());
}

async function openMap(page: Page, path = "/map") {
  await blockTiles(page);
  await page.goto(path);
  await expect(page.getByTestId("map-canvas")).toBeVisible({ timeout: 60_000 });
}

/** Page and console errors, except the aborted tile / font requests (the expected fallback, decision h). */
function clean(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (/openfreemap|Failed to load resource|ERR_FAILED|AJAXError|Failed to fetch/i.test(t)) return;
    errors.push(`console: ${t}`);
  });
  return { expectClean: () => expect(errors, errors.join(" | ")).toEqual([]) };
}

test.describe("Map — new app, preview database", () => {
  test("Opportunity: an ecosystem's Why here? and a sourcing-day plan with exactly one POST", async ({ page }) => {
    const intel = (await (await page.request.get("/api/map/intel")).json()) as Intel;
    const city = intel.ecosystems.find((e) => e.reasons.length)?.city;
    test.skip(!city, "the preview data places no ecosystem");
    const w = clean(page);
    const posts: string[] = [];
    page.on("request", (r) => r.method() === "POST" && r.url().includes("/api/") && posts.push(new URL(r.url()).pathname));
    await openMap(page);
    await expect(page.getByTestId("geo-controls")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("geo-snapshot-note").first()).toContainText("imported snapshot");
    await page.getByTestId("geo-list").getByRole("button", { name: new RegExp(`^${city}`) }).first().click();
    const panel = page.getByTestId("geo-panel");
    await expect(panel).toBeVisible({ timeout: 60_000 });
    await expect(panel.getByTestId("geo-why")).toBeVisible();
    await expect(panel.getByTestId("geo-nba")).toBeVisible();
    await panel.getByTestId("build-day").click();
    await panel.getByRole("button", { name: "Build plan" }).click();
    await expect(panel.getByTestId("sourcing-plan")).toBeVisible({ timeout: 60_000 });
    await expect(panel.getByTestId("sourcing-plan")).toContainText("PLAN ONLY");
    expect(posts).toEqual(["/api/map/sourcing_day"]);
    w.expectClean();
  });

  test("Explore: the layers and the visible results; the search opens a city", async ({ page }) => {
    const w = clean(page);
    await openMap(page, "/map?mode=explore");
    await expect(page.getByRole("tab", { name: "Explore" })).toHaveAttribute("aria-selected", "true");
    const ctl = page.getByTestId("map-controls");
    await expect(ctl.getByLabel("Startups")).toBeChecked({ timeout: 60_000 });
    await expect(page.getByTestId("map-results")).toBeVisible();
    await page.getByRole("tab", { name: "Opportunity" }).click();
    await page.getByLabel("Search the map").fill("munich");
    await page.getByLabel("Search the map").press("Enter");
    await expect(page.getByTestId("geo-panel").or(page.getByTestId("map-panel")).first()).toBeVisible({ timeout: 60_000 });
    w.expectClean();
  });

  test("the ?event= deep link from Events", async ({ page }) => {
    const pins = (await (await page.request.get("/api/map/pins")).json()) as { events: Array<{ id: string }> };
    const ev = pins.events[0];
    test.skip(!ev, "the preview data has no event with coordinates");
    const w = clean(page);
    await openMap(page, `/map?event=${encodeURIComponent(ev.id)}`);
    await expect(page.getByTestId("map-panel")).toBeVisible({ timeout: 60_000 });
    w.expectClean();
  });

  test("1366x768, 150% zoom and 1920: no horizontal overflow", async ({ page }) => {
    const w = clean(page);
    await page.setViewportSize({ width: 1366, height: 768 });
    await openMap(page);
    await expect(page.getByTestId("geo-controls")).toBeVisible({ timeout: 60_000 });
    await expectNoHorizontalOverflow(page);
    await zoom150(page);
    await page.waitForTimeout(300);
    await expectNoHorizontalOverflow(page);
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(300);
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });
});
