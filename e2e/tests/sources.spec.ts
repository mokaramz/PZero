/**
 * Sources (review 021) — the new app on a preview database (the real snapshot in a scratch schema; writes land only
 * there). The registry, the detail, the coverage matrix and the lists from one payload; the toggle round trip.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

type Source = { id: string; name: string; enabled: boolean; geo?: string[] };
const sources = async (page: Page) => ((await (await page.request.get("/api/sources")).json()).sources as Source[]);

test.describe("Sources — new app, preview database", () => {
  test("the registry, a detail and the coverage matrix render from one call", async ({ page }) => {
    const w = watch(page);
    const calls: string[] = [];
    page.on("request", (r) => r.url().includes("/api/") && calls.push(new URL(r.url()).pathname));
    await page.goto("/sources");
    await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("source-table")).toBeVisible();
    await expect(page.getByTestId("coverage-matrix")).toBeVisible();
    await expect(page.getByTestId("manual-sources")).toBeVisible();
    expect(calls).toContain("/api/sources");
    expect(calls).not.toContain("/api/deal-flow/inbox"); // the four inbox fields come with the registry now
    const first = page.getByTestId("source-table").locator("tbody tr").first();
    await first.click();
    await expect(page.getByTestId("source-detail")).toBeVisible();
    w.expectClean();
  });

  test("the toggle switches a source off and on, checked against a fresh read", async ({ page }) => {
    const w = watch(page);
    const all = await sources(page);
    const target = all.find((s) => s.enabled && (s.geo ?? []).some((g) => ["DACH", "CH", "EU", "DE"].includes(g))) ?? all.find((s) => s.enabled)!;
    await page.goto("/sources");
    await expect(page.getByTestId("source-table")).toBeVisible({ timeout: 60_000 });
    await page.getByRole("tab", { name: "All workspaces" }).click();
    const row = page.getByTestId("source-table").locator("tbody tr").filter({ hasText: target.name }).first();
    await expect(row).toBeVisible();
    const box = row.getByRole("checkbox");
    await expect(box).toBeChecked();
    await box.click();
    await expect(page.getByText("Source disabled")).toBeVisible();
    await expect.poll(async () => (await sources(page)).find((s) => s.id === target.id)?.enabled).toBe(false);
    await box.click();
    await expect(page.getByText("Source enabled")).toBeVisible();
    await expect.poll(async () => (await sources(page)).find((s) => s.id === target.id)?.enabled).toBe(true);
    w.expectClean();
  });

  test("1366x768, 150% zoom and 1920: no horizontal overflow", async ({ page }) => {
    const w = watch(page);
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto("/sources");
    await expect(page.getByTestId("source-table")).toBeVisible({ timeout: 60_000 });
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
