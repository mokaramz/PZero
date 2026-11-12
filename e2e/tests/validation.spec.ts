/**
 * Validation (reviews 027a, 027b) — the new app on a preview database (the real snapshot in a scratch schema).
 * Every tab of the five questions, the measurement overview, the write controls (enabled; each form opens and is
 * cancelled, the retraction prompt is dismissed — never a write request: the real writes are covered by the backend's
 * hosted tests and the mocked spec), the News and native-bridge reasons, the Scout 00 packet read, and the layout at
 * the usual sizes. The page tests cover every panel in detail.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, watch as watchErrors, zoom150 } from "./helpers";

const TABS = ["Are we early?", "Are we right?", "Which sources work?", "Where do we miss?", "What does it cost?"];

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
    await expect(page.getByTestId("val-news")).toBeVisible(); // News & Learning arrived with 028a
    await tabs.nth(3).click();
    await expect(page.getByTestId("val-misses")).toBeVisible();
    await expect(page.getByTestId("val-scout")).toBeVisible();
    await tabs.nth(4).click();
    await expect(page.getByTestId("val-native-bridge")).toBeVisible();
    await expect(page.getByTestId("val-footer")).toContainText("Daily snapshots kept:");
    w.expectClean();
  });

  test("the write controls are enabled; opening and cancelling them writes nothing; the packet only reads", async ({ page }) => {
    const w = watch(page);
    const prompts: string[] = [];
    page.on("dialog", (d) => {
      prompts.push(d.message());
      void d.dismiss();
    });
    await openValidation(page);
    const dialog = page.getByRole("dialog");
    const question = (name: string) => page.getByTestId("val-questions").getByRole("tab", { name }).click();

    await expect(page.getByTestId("record-outcome")).toBeEnabled();
    await expect(page.getByTestId("record-outcome")).not.toHaveAttribute("aria-disabled", "true");
    await page.getByTestId("record-outcome").click();
    await expect(dialog.getByRole("heading", { name: "Record an outcome" })).toBeVisible();
    await page.getByTestId("outcome-company").fill("Invented Validation Co");
    await page.getByTestId("outcome-kind").selectOption("accelerator");
    await page.getByTestId("outcome-date").fill("2026-09-01");
    await expect(page.getByTestId("outcome-save")).toBeEnabled(); // ready — but cancelled
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toHaveCount(0);

    await page.getByTestId("more-actions").locator("summary").click();
    await expect(page.getByTestId("record-miss")).toBeEnabled();
    await page.getByTestId("record-miss").click();
    await expect(dialog.getByRole("heading", { name: "Miss audit — a strong company we did not catch early" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);

    await question("Are we right?");
    const retract = page.getByTestId("val-outcome").getByRole("button", { name: "Retract" });
    if (await retract.count()) {
      await expect(retract.first()).toBeEnabled();
      await retract.first().click(); // the prompt is dismissed: nothing is sent
      expect(prompts).toEqual(["Why retract this outcome? (kept in history)"]);
    }

    await question("Which sources work?");
    const bench = page.getByTestId("val-benchmarks");
    await bench.getByText("Import a benchmark export").click();
    await expect(bench.getByRole("button", { name: "Preview" })).toBeDisabled();
    await bench.getByPlaceholder("Dealroom").fill("Invented DB");
    await bench.locator("textarea").fill("Name,Date added\nInvented Validation Co,2026-07-01\n");
    await expect(bench.getByRole("button", { name: "Preview" })).toBeEnabled(); // not clicked: a preview is a POST

    await question("Where do we miss?");
    await expect(page.getByTestId("record-fp")).toBeEnabled();
    await page.getByTestId("record-fp").click();
    await expect(dialog.getByRole("heading", { name: "False-positive audit — prioritised but proved weak" })).toBeVisible();
    await expect(page.getByTestId("audit-save")).toBeDisabled();
    await dialog.getByRole("button", { name: "Close" }).click();

    const packet = page.waitForResponse((r) => r.url().includes("/api/validation/scout_packet"));
    await page.getByTestId("scout-packet").click();
    expect((await packet).status()).toBe(200);
    await expect(page.getByTestId("scout-packet-text")).toContainText("PROJECT ZERO → CHIEF SCOUT 00");
    await expect(page.getByTestId("scout-packet-text")).toContainText(/^Generated \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} · /m); // what the mark sends
    await expect(page.getByTestId("scout-packet-copy")).toBeEnabled(); // not clicked: it logs the handover
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
