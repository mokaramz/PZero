/**
 * Radar (review 019) — the new app on a preview database (the real snapshot in a scratch schema). The page lists the
 * composition the API returns, keeps empty Top-10 slots as one quiet line, and links each card to its company.
 */
import { expect, test } from "@playwright/test";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

type Radar = Record<"high" | "emerging" | "wildcard" | "research_queue" | "gated" | "watch", Array<{ slug: string; company: string }>>;

test.describe("Radar — new app, preview database", () => {
  test("the sections follow the API, empty slots are one line, and a card opens its company", async ({ page }) => {
    const w = watch(page);
    const radar = (await (await page.request.get("/api/conviction/radar")).json()) as Radar;
    await page.goto("/radar");
    await expect(page.getByRole("heading", { name: "PROJECT A RADAR — TOP 10" })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("radar-method")).toBeVisible();
    const all = Object.values(radar).flat();
    await expect(page.getByTestId("radar-card")).toHaveCount(all.length);
    for (const [key, slots] of [["high", 8], ["emerging", 1], ["wildcard", 1]] as const) {
      const empty = slots - radar[key].length;
      const section = page.getByRole("region", { name: new RegExp(`^${key === "high" ? "High-confidence" : key === "emerging" ? "Emerging" : "Wildcard"}`) });
      if (empty > 0) await expect(section.getByTestId("radar-empty")).toHaveAttribute("data-empty", String(empty));
      else await expect(section.getByTestId("radar-empty")).toHaveCount(0);
    }
    if (radar.research_queue.length === 0) await expect(page.getByRole("region", { name: /^Research Queue/ })).toHaveCount(0);
    const first = all[0];
    test.skip(!first, "the preview data places nobody on the Radar");
    await page.getByTestId("radar-card").filter({ hasText: first.company }).first().getByRole("link", { name: first.company }).click();
    await expect(page).toHaveURL(new RegExp(`/conviction\\?company=${first.slug}`));
    await expect(page.getByRole("heading", { level: 2, name: first.company })).toBeVisible({ timeout: 60_000 });
    w.expectClean();
  });

  test("1366x768, 150% zoom and 1920: no horizontal overflow", async ({ page }) => {
    const w = watch(page);
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto("/radar");
    await expect(page.getByTestId("radar-method")).toBeVisible({ timeout: 60_000 });
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
