/**
 * Public work (review 020) — the new app on a preview database (the real snapshot in a scratch schema; writes land
 * only there). Create, edit and delete round trips against a fresh read, and the layout at the usual sizes.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

type Content = { items: Array<{ id: string; title?: string; kind?: string; platform?: string; inbound?: string }> };
const content = async (page: Page) => (await (await page.request.get("/api/content")).json()) as Content;

test.describe("Public work — new app, preview database", () => {
  test("create, edit and delete round trips", async ({ page }) => {
    const w = watch(page);
    const tag = Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8);
    const title = `E2E post ${tag} about industrial AI`;
    await page.goto("/public-work");
    await expect(page.getByRole("heading", { name: "Public work" })).toBeVisible({ timeout: 60_000 });
    await page.getByRole("button", { name: "+ New item" }).click();
    const form = page.getByRole("form", { name: "Public work item" });
    await form.locator('[name="title"]').fill(title);
    await form.locator('[name="kind"]').selectOption("draft");
    await form.getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Saved", { exact: true })).toBeVisible();
    const row = page.getByTestId("work-row").filter({ hasText: title });
    await expect(row).toBeVisible();
    await expect(page.getByTestId("work-row").first()).toContainText(title); // a new item goes on top
    const created = (await content(page)).items.find((i) => i.title === title);
    expect(created).toMatchObject({ kind: "draft", platform: "linkedin" });

    await row.getByRole("button", { name: title }).click();
    await expect(page.getByRole("dialog", { name: "Edit item" })).toBeVisible();
    await form.locator('[name="inbound"]').fill("Two DMs worth following");
    await form.locator('[name="kind"]').selectOption("published");
    await form.getByRole("button", { name: "Save" }).click();
    await expect(row).toContainText("Two DMs worth following");
    expect((await content(page)).items.find((i) => i.id === created!.id)).toMatchObject({ kind: "published", inbound: "Two DMs worth following" });

    await row.getByRole("button", { name: title }).click();
    await form.getByRole("button", { name: "Delete" }).click();
    await expect(page.getByText("Deleted", { exact: true })).toBeVisible();
    await expect(row).toHaveCount(0);
    expect((await content(page)).items.some((i) => i.id === created!.id)).toBe(false);
    w.expectClean();
  });

  test("1366x768, 150% zoom and 1920: no horizontal overflow", async ({ page }) => {
    const w = watch(page);
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto("/public-work");
    await expect(page.getByRole("heading", { name: "Public work" })).toBeVisible({ timeout: 60_000 });
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
