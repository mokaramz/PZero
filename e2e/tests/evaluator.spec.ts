/**
 * Active Evaluator (review 024) — the new app on a preview database (the real snapshot in a scratch schema; writes land
 * only there). The workspace with a session open, the round trip from Conviction (start, deck, answer, end), the dated
 * why-now trigger from Conviction read back on a fresh pipeline, and the layout at the usual sizes. The hosted tests
 * cover the one-transaction end, the shared session reader and the refusals.
 */
import { expect, test, type Page } from "@playwright/test";

import { expand, expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

type Sessions = { sessions: Array<{ id: string; status: string }> };
const sessions = async (page: Page) => (await (await page.request.get("/api/evaluator/sessions")).json()) as Sessions;
const pipeline = async (page: Page) =>
  (await (await page.request.get("/api/conviction/pipeline")).json()).signals as Array<{ slug: string; company: string; imq_trigger?: { fact: string } }>;

async function openManagerSection(page: Page, slug: string) {
  await page.goto(`/conviction?company=${slug}`);
  await expect(page.locator(`[data-slug=${slug}]`)).toHaveAttribute("aria-current", "true", { timeout: 60_000 });
  await expand(page, "sec-omar");
  await expect(page.getByTestId("imq")).toBeVisible();
}

test.describe("Active Evaluator — new app, preview database", () => {
  test("the workspace with an imported session open", async ({ page }) => {
    const w = watch(page);
    const first = (await sessions(page)).sessions[0];
    test.skip(!first, "the preview data has no evaluator session");
    await page.goto(`/evaluator?session=${encodeURIComponent(first.id)}`);
    await expect(page.getByTestId("eval-counts")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("eval-sessions")).toBeVisible();
    await expect(page.getByTestId("eval-workspace")).toBeVisible();
    if (first.status === "ended") await expect(page.getByTestId("eval-ended")).toBeVisible();
    w.expectClean();
  });

  test("from Conviction: start, import a deck, answer and end", async ({ page }) => {
    const w = watch(page);
    const company = (await pipeline(page))[0];
    test.skip(!company, "the preview data has no Conviction company");
    await openManagerSection(page, company.slug);
    await page.getByRole("button", { name: "Start Active Evaluator" }).click();
    await expect(page).toHaveURL(/\/evaluator\?session=/, { timeout: 30_000 });
    await expect(page.getByTestId("eval-workspace")).toBeVisible({ timeout: 60_000 });
    const id = new URL(page.url()).searchParams.get("session")!;

    await page.getByLabel("Pitch deck text").fill("- ARR of €1.2m with 18 paying customers across Europe.\nGross margin 70% on platform revenue.");
    await page.getByRole("button", { name: "Import deck claims" }).click();
    await expect(page.getByTestId("eval-right").or(page.getByTestId("eval-left")).first()).toContainText("ARR of €1.2m", { timeout: 30_000 });

    await expect(page.getByTestId("eval-question")).toBeVisible();
    await page.getByLabel("Founder's answer").fill("We have 12 paying customers today.");
    await page.getByRole("button", { name: "Record answer → next" }).click();
    await expect(page.getByLabel("Founder's answer")).toHaveValue("", { timeout: 30_000 });

    await page.getByRole("button", { name: "End evaluation" }).click();
    await page.getByRole("dialog").getByRole("button", { name: "End evaluation" }).click();
    await expect(page.getByTestId("eval-ended")).toBeVisible({ timeout: 30_000 });

    const stored = await (await page.request.get(`/api/evaluator/session?id=${encodeURIComponent(id)}`)).json();
    expect(stored.session.status).toBe("ended");
    expect(stored.session.ended.call_id).toBeTruthy(); // one answer: a founder call was saved in the same transaction
    w.expectClean();
  });

  test("from Conviction: a dated why-now trigger shows on a fresh pipeline read", async ({ page }) => {
    const w = watch(page);
    const company = (await pipeline(page))[0];
    test.skip(!company, "the preview data has no Conviction company");
    const fact = `E2E trigger ${Math.random().toString(36).slice(2, 8)}`;
    await openManagerSection(page, company.slug);
    await page.getByRole("button", { name: "Record dated why-now trigger (sourced)" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Date of the trigger (YYYY-MM-DD) — when it happened, not today").fill("2026-11-01");
    await dialog.getByLabel("Public source URL that documents it (not LinkedIn, not a search result)").fill("https://invented.example/round");
    await dialog.getByLabel("The dated fact as the source states it").fill(fact);
    await dialog.getByRole("button", { name: "Review" }).click();
    await expect(dialog.getByTestId("trigger-review")).toContainText(fact);
    await dialog.getByRole("button", { name: "Record trigger" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0, { timeout: 30_000 });
    const after = (await pipeline(page)).find((e) => e.slug === company.slug);
    expect(after?.imq_trigger?.fact).toBe(fact);
    w.expectClean();
  });

  test("1366x768, 150% zoom and 1920: no horizontal overflow", async ({ page }) => {
    const w = watch(page);
    const first = (await sessions(page)).sessions[0];
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto(first ? `/evaluator?session=${encodeURIComponent(first.id)}` : "/evaluator");
    await expect(page.getByTestId("eval-counts")).toBeVisible({ timeout: 60_000 });
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
