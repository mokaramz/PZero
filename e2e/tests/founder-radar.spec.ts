/**
 * Founder Radar (review 026a) — the new app on a preview database (the real snapshot in a scratch schema; writes land
 * only there). The views on real data, a person's drawer, a watch action read back after a fresh load, the disabled
 * network controls (026b), and the layout at the usual sizes. The mocked spec (`founder-radar-mocked.spec.ts`) covers
 * every action's exact POST body, the review drawer and the dialogs.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

type Radar = { people: Array<{ id: string; name: string; watch?: boolean; radar_state?: string }> };
const radar = async (page: Page) => (await (await page.request.get("/api/founder-radar")).json()) as Radar;

test.describe("Founder Radar — new app, preview database", () => {
  test("the four views on the real snapshot", async ({ page }) => {
    const w = watch(page);
    await page.goto("/founder-radar");
    await expect(page.getByTestId("fr-counts")).toBeVisible({ timeout: 60_000 });
    for (const view of ["Near Matches", "Research Queue", "Diagnostics", "Top Founder Leads"]) {
      await page.getByRole("tab", { name: view }).click();
      await expect(page.getByRole("tab", { name: view })).toHaveAttribute("aria-selected", "true");
    }
    await page.getByRole("tab", { name: "Diagnostics" }).click();
    await expect(page.getByTestId("fr-health")).toBeVisible();
    w.expectClean();
  });

  test("Scan and Research stay disabled with their reason, and nothing calls them", async ({ page }) => {
    const w = watch(page);
    const calls: string[] = [];
    page.on("request", (r) => r.url().includes("/api/") && calls.push(new URL(r.url()).pathname));
    await page.goto("/founder-radar");
    await expect(page.getByTestId("fr-counts")).toBeVisible({ timeout: 60_000 });
    const scan = page.getByRole("button", { name: /Scan founder signals/ });
    await expect(scan).toHaveAttribute("aria-disabled", "true");
    await scan.click({ force: true });
    await expect(page.getByText(/arrive with the founder scan port \(026b\)/).first()).toBeVisible();
    expect(calls.some((p) => /scan|research(?!-queue)|research_queue|bridge/.test(p))).toBe(false);
    w.expectClean();
  });

  test("a watch action from a person's drawer is read back after a fresh load", async ({ page }) => {
    const w = watch(page);
    const person = (await radar(page)).people.find((p) => !p.watch);
    test.skip(!person, "the preview data has no unwatched radar person");
    const origin = new URL(process.env.PZ_BASE_URL ?? "http://localhost:5173").origin;
    const r = await page.request.post("/api/founder-radar/action", { data: { id: person!.id, action: "watch" }, headers: { Origin: origin } });
    expect(r.ok()).toBe(true);
    await page.goto(`/founder-radar?person=${encodeURIComponent(person!.id)}`);
    await expect(page.getByTestId("fr-person")).toBeVisible({ timeout: 60_000 });
    const after = (await radar(page)).people.find((p) => p.id === person!.id);
    expect(after?.watch).toBe(true);
    w.expectClean();
  });

  test("1366x768, 150% zoom and 1920: no horizontal overflow", async ({ page }) => {
    const w = watch(page);
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto("/founder-radar");
    await expect(page.getByTestId("fr-counts")).toBeVisible({ timeout: 60_000 });
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
