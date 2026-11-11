/**
 * Conviction — the core cases of the old `e2e/tests/conviction.spec.ts` plus review 011's Keep paths, against the new
 * app on a preview database (the real snapshot in a scratch schema; writes land only there).
 * Changed on purpose: the Manager card, memo / email and case preparation are not ported — their controls are disabled.
 */
import { expect, test, type Page } from "@playwright/test";

import { expand, expectNoHorizontalOverflow, filterChip, openDealFlow, recordPosts, rows, watch, zoom150 } from "./helpers";

async function openCompany(page: Page, slug: string, name: string) {
  await page.goto(`/conviction?company=${slug}`);
  await expect(page.getByRole("heading", { level: 2, name })).toBeVisible({ timeout: 60_000 });
}

async function companyAction(page: Page, name: string) {
  await page.getByTestId("company-actions").locator("summary").click();
  await page.getByRole("group", { name: "Company actions" }).getByRole("button", { name }).click();
}

const pipeline = async (page: Page) => (await (await page.request.get("/api/conviction/pipeline")).json()).signals as Array<Record<string, unknown>>;

test.describe("Conviction — new app, preview database", () => {
  test("deep link, selection, segments and filter", async ({ page }) => {
    const w = watch(page);
    await openCompany(page, "aereus", "Aereus");
    await expect(page.getByTestId("pipe-counts")).toContainText("companies");
    await expect(page.locator("[data-slug=aereus]")).toHaveAttribute("aria-current", "true");
    await expand(page, "sec-evidence");
    await expect(page.getByTestId("checklist")).toContainText("Founders — identities, backgrounds, LinkedIn");
    await page.locator("[data-slug=craci]").click();
    await expect(page).toHaveURL(/company=craci/);
    await expect(page.getByRole("heading", { level: 2, name: "CRACI" })).toBeVisible();
    await page.getByRole("tab", { name: "Gated" }).click();
    await expect(page.getByRole("group", { name: "Investigate & research" })).toHaveCount(0);
    await page.getByRole("tab", { name: "All" }).click();
    await page.getByLabel("Filter companies").fill("zzzz-no-match");
    await expect(page.getByText("No matches.")).toBeVisible();
    w.expectClean();
  });

  test("status change round-trip, checked against a fresh read", async ({ page }) => {
    await openCompany(page, "acodyne", "Acodyne");
    await page.getByTestId("company-actions").locator("summary").click();
    const bar = page.getByTestId("status-bar");
    await bar.getByLabel("Change status").selectOption("contacted");
    await expect(page.getByText("Status → contacted")).toBeVisible();
    expect((await pipeline(page)).find((s) => s.slug === "acodyne")?.status).toBe("contacted");
    await bar.getByLabel("Change status").selectOption("new");
    await expect(bar.getByLabel("Change status")).toHaveValue("new");
    expect((await pipeline(page)).find((s) => s.slug === "acodyne")?.status).toBe("new");
  });

  test("verification checkbox saves and re-scores", async ({ page }) => {
    await openCompany(page, "alqem", "alqem");
    await expand(page, "sec-evidence");
    const box = page.getByTestId("checklist").locator("[data-verify=traction]");
    const was = await box.isChecked();
    await box.click();
    await expect(page.getByText(was ? "Unchecked: traction" : "Verified: traction")).toBeVisible();
    await expect(box).toBeChecked({ checked: !was });
    const after = (await pipeline(page)).find((s) => s.slug === "alqem") as { verified: Record<string, boolean>; one_liner?: string };
    expect(after.verified.traction).toBe(!was);
    expect(after.one_liner, "a checklist save never clears other fields").toBeTruthy();
    await box.click();
    await expect(box).toBeChecked({ checked: was });
  });

  test("edit & verify saves round-trip and keeps off-ladder scores", async ({ page }) => {
    const w = watch(page);
    await openCompany(page, "kyrok", "Kyrok");
    const scoreBefore = await page.locator("[data-slug=kyrok]").getByTestId("row-score").textContent();
    await companyAction(page, "Edit & verify");
    const dlg = page.getByRole("dialog", { name: "Edit & verify: Kyrok" });
    await expect(dlg.getByTestId("livescore")).toContainText("Provisional");
    const next = `E2E next action ${Date.now()}`;
    await dlg.locator("input[name=next_action]").fill(next);
    const before = await dlg.getByTestId("livescore").textContent();
    await dlg.locator("input[name=penalties][value=wrapper]").check();
    await expect(dlg.getByTestId("livescore")).not.toHaveText(before ?? "");
    await dlg.locator("input[name=penalties][value=wrapper]").uncheck();
    await dlg.getByRole("button", { name: "Save to pipeline" }).click();
    await expect(page.getByText("Saved & scored")).toBeVisible();
    await expect(dlg).toBeHidden();
    expect((await pipeline(page)).find((s) => s.slug === "kyrok")?.next_action).toBe(next);
    await expect(page.locator("[data-slug=kyrok]").getByTestId("row-score")).toHaveText(scoreBefore ?? "");
    w.expectClean();
  });

  test("add company creates and selects; a duplicate name offers the existing entry", async ({ page }) => {
    const w = watch(page, { expected: [409] });
    await page.goto("/conviction");
    await page.getByRole("button", { name: "+ Add company" }).click();
    let dlg = page.getByRole("dialog", { name: "Add company" });
    const name = `E2E Co ${Date.now()}`;
    await dlg.locator("input[name=company]").fill(name);
    await dlg.locator("input[name=one_liner]").fill("Test entry created by Playwright");
    await dlg.getByRole("button", { name: "Save to pipeline" }).click();
    await expect(page.getByRole("heading", { level: 2, name })).toBeVisible();
    // the same name again: 409 → Open existing entry
    await page.getByRole("button", { name: "+ Add company" }).click();
    dlg = page.getByRole("dialog", { name: "Add company" });
    await dlg.locator("input[name=company]").fill("Kyrok");
    await dlg.getByRole("button", { name: "Save to pipeline" }).click();
    await expect(page.getByTestId("save-duplicate")).toBeVisible();
    await page.getByTestId("save-duplicate").getByRole("button", { name: "Open existing entry" }).click();
    await expect(page).toHaveURL(/company=kyrok/);
    await expect(page.getByRole("heading", { level: 2, name: "Kyrok" })).toBeVisible();
    expect((await pipeline(page)).filter((s) => s.company === "Kyrok")).toHaveLength(1);
    w.expectClean();
  });

  test("Keep from Deal Flow scores the lead into Conviction; the lead is kept once", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    await openDealFlow(page);
    await filterChip(page, "All to decide").click();
    const first = rows(page).first();
    const id = await first.getAttribute("data-id");
    const name = (await first.locator('[class*="candName"]').innerText()).trim();
    await first.click();
    await page.getByTestId("cand-detail").getByRole("button", { name: "Keep — score it" }).click();
    const dlg = page.getByRole("dialog");
    await expect(dlg).toBeVisible();
    await dlg.getByRole("button", { name: "Save to pipeline" }).click();
    await expect(page).toHaveURL(/\/conviction\?company=/, { timeout: 30_000 });
    const save = posted.find((p) => p.path === "/api/conviction/save");
    expect((save?.body as { inbox_id?: string }).inbox_id).toBe(id);
    const inbox = await (await page.request.get("/api/deal-flow/inbox")).json();
    const lead = inbox.candidates.find((c: { id: string }) => c.id === id);
    expect(lead).toMatchObject({ decision: "kept", pz_status: "kept" });
    expect((await pipeline(page)).filter((s) => s.inbox_id === id)).toHaveLength(1);
    // Keep the same lead again → 409 with the existing slug, nothing else changes
    const again = await page.request.post("/api/conviction/save", { data: { company: name, inbox_id: id }, headers: { Origin: new URL(page.url()).origin } });
    expect(again.status()).toBe(409);
    expect((await again.json()).slug).toBeTruthy();
    w.expectClean();
  });

  test("1366x768, 150% zoom and 1920: no horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 });
    await openCompany(page, "kyrok", "Kyrok");
    await expectNoHorizontalOverflow(page);
    await zoom150(page);
    await page.waitForTimeout(300);
    await expectNoHorizontalOverflow(page);
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(300);
    await expectNoHorizontalOverflow(page);
  });
});
