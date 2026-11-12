/**
 * Ecosystems (review 022) — the new app on a preview database (the real snapshot in a scratch schema; writes land
 * only there). Coverage, the city registry and a city view; adopting a candidate watcher through the confirmation.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

type Coverage = { ecosystems: Array<{ id: string; city: string; families: Record<string, { candidates?: Array<{ id: string; adopted?: unknown; url?: string }> }> }> };
const coverage = async (page: Page) => (await (await page.request.get("/api/ecosystems/coverage")).json()) as Coverage;

test.describe("Ecosystems — new app, preview database", () => {
  test("coverage, the city registry and a city view render; a chip opens its city", async ({ page }) => {
    const w = watch(page);
    await page.goto("/ecosystems");
    await expect(page.getByTestId("coverage-summary")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("city-registry")).toBeVisible();
    await expect(page.getByTestId("city-page")).toBeVisible();
    await expect(page.getByTestId("city-page")).toContainText("Karlsruhe");
    const chip = page.getByTestId("registry-curated").getByRole("button").nth(1);
    const name = ((await chip.textContent()) ?? "").trim().split(/\s/)[0];
    await chip.click();
    await expect(page).toHaveURL(/city=/);
    await expect(page.getByTestId("city-page")).toContainText(name);
    w.expectClean();
  });

  test("a coverage row opens its detail; adopting a candidate needs the confirmation", async ({ page }) => {
    const w = watch(page);
    const cov = await coverage(page);
    const eco = cov.ecosystems.find((e) => Object.values(e.families).some((f) => (f.candidates ?? []).some((c) => !c.adopted && String(c.url ?? "").startsWith("http"))));
    test.skip(!eco, "the preview data offers no candidate watcher");
    await page.goto("/ecosystems");
    await expect(page.getByTestId("coverage-summary")).toBeVisible({ timeout: 60_000 });
    await page.getByRole("row").filter({ hasText: eco!.city }).first().click();
    const detail = page.getByTestId("coverage-detail");
    await expect(detail).toBeVisible();
    const adopt = detail.getByRole("button", { name: /Adopt as watcher/ }).first();
    await adopt.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: /cancel/i }).click();
    await expect(dialog).toBeHidden();
    await adopt.click();
    await page.getByRole("dialog").getByRole("button", { name: /adopt/i }).last().click();
    await expect(page.getByText(/Adopted as watcher|already/i).first()).toBeVisible({ timeout: 30_000 });
    expect(page.getByRole("button", { name: /scout/i })).toHaveCount(0); // no Scout Bridge
    w.expectClean();
  });

  test("1366x768, 150% zoom and 1920: no horizontal overflow", async ({ page }) => {
    const w = watch(page);
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto("/ecosystems");
    await expect(page.getByTestId("coverage-summary")).toBeVisible({ timeout: 60_000 });
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
