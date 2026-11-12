/**
 * Validation (review 027a, the read side) — the new app on a preview database (the real snapshot in a scratch schema).
 * Every tab of the five questions, the measurement overview, the deferred write controls (visible, disabled, with their
 * reason; never a write request), the News and native-bridge reasons, the Scout 00 packet read, and the layout at the
 * usual sizes. The MSW page tests cover every panel in detail.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, watch as watchErrors, zoom150 } from "./helpers";

const TABS = ["Are we early?", "Are we right?", "Which sources work?", "Where do we miss?", "What does it cost?"];
const WRITES_REASON = "Recording outcomes, audits and imports arrives with the Validation writes port (027b)";

/** No page / console error (the shell's not-yet-ported endpoints aside, as everywhere) and no write request at all. */
function watch(page: Page) {
  const errors = watchErrors(page);
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.method() !== "GET" && r.url().includes("/api/")) writes.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  return {
    expectClean: () => {
      errors.expectClean();
      expect(writes, writes.join(" | ")).toEqual([]);
    },
  };
}

async function openValidation(page: Page) {
  await page.goto("/validation");
  await expect(page.getByTestId("val-questions")).toBeVisible({ timeout: 60_000 });
}

test.describe("Validation — new app, preview database", () => {
  test("the overview and every question tab render; nothing is written", async ({ page }) => {
    const w = watch(page);
    await openValidation(page);
    await expect(page.getByRole("heading", { name: "Validation & Learning" })).toBeVisible();
    await page.getByTestId("val-measurement-d").locator("summary").click();
    await expect(page.getByTestId("val-measure")).toHaveCount(6);
    const tabs = page.getByTestId("val-questions").getByRole("tab");
    await expect(tabs).toHaveText(TABS);
    await expect(tabs.first()).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("val-edge")).toBeVisible();
    await tabs.nth(1).click();
    await expect(page.getByTestId("val-conversion")).toBeVisible();
    await expect(page.getByTestId("val-calibration")).toBeVisible();
    await expect(page.getByTestId("val-outcomes")).toBeVisible();
    await tabs.nth(2).click();
    await expect(page.getByTestId("val-sources")).toBeVisible();
    await expect(page.getByTestId("val-benchmarks")).toBeVisible();
    await expect(page.getByText("News & Learning arrives with its port").first()).toBeVisible();
    await tabs.nth(3).click();
    await expect(page.getByTestId("val-misses")).toBeVisible();
    await expect(page.getByTestId("val-scout")).toBeVisible();
    await tabs.nth(4).click();
    await expect(page.getByTestId("val-native-bridge")).toBeVisible();
    await expect(page.getByTestId("val-footer")).toContainText("Daily snapshots kept:");
    w.expectClean();
  });

  test("the write controls are visible, disabled and give their reason; the packet only reads", async ({ page }) => {
    const w = watch(page);
    await openValidation(page);
    const deferred = async (testId: string) => {
      const el = page.getByTestId(testId);
      await expect(el).toBeVisible();
      await expect(el).toHaveAttribute("aria-disabled", "true");
      await expect(el).toHaveAttribute("title", WRITES_REASON);
      await el.click({ force: true }); // does nothing: no request below
    };
    await deferred("record-outcome");
    await page.getByTestId("val-questions").getByRole("tab", { name: "Where do we miss?" }).click();
    await deferred("record-fp");
    const packet = page.waitForResponse((r) => r.url().includes("/api/validation/scout_packet"));
    await page.getByTestId("scout-packet").click();
    expect((await packet).status()).toBe(200);
    await expect(page.getByTestId("scout-packet-text")).toContainText("PROJECT ZERO → CHIEF SCOUT 00");
    await deferred("scout-packet-copy");
    w.expectClean();
  });

  for (const size of [{ width: 1366, height: 900 }, { width: 1920, height: 1080 }, { width: 390, height: 844 }]) {
    test(`no horizontal overflow at ${size.width}`, async ({ page }) => {
      await page.setViewportSize(size);
      await openValidation(page);
      for (const name of TABS) {
        await page.getByTestId("val-questions").getByRole("tab", { name }).click();
        await expectNoHorizontalOverflow(page);
      }
    });
  }

  test("no horizontal overflow at 150 %", async ({ page }) => {
    await openValidation(page);
    await zoom150(page);
    for (const name of TABS) {
      await page.getByTestId("val-questions").getByRole("tab", { name }).click();
      await expectNoHorizontalOverflow(page);
    }
  });
});
