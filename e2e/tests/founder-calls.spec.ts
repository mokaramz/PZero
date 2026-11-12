/**
 * Founder Calls (review 023) — the new app on a preview database (the real snapshot in a scratch schema; writes land
 * only there). The workspace, a call's detail with the deferred call intelligence, a save round trip (the hosted tests
 * cover Conviction reading the same calls), the memo, and the layout at the usual sizes.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

type Workspace = { companies: Array<{ id: string; name: string; founders: Array<{ id: string; calls: Array<{ id: string }> }> }> };
const workspace = async (page: Page) => (await (await page.request.get("/api/founder-calls/calls")).json()) as Workspace;

test.describe("Founder Calls — new app, preview database", () => {
  test("the workspace, a call's detail, the deferred intelligence and the memo", async ({ page }) => {
    const w = watch(page);
    const ws = await workspace(page);
    const call = ws.companies.flatMap((c) => c.founders.flatMap((f) => f.calls))[0];
    test.skip(!call, "the preview data has no founder call");
    const calls: string[] = [];
    page.on("request", (r) => r.url().includes("/api/") && calls.push(new URL(r.url()).pathname));
    await page.goto(`/founder-calls?call=${call.id}`);
    await expect(page.getByTestId("calls-tree")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("call-detail")).toBeVisible();
    await expect(page.getByTestId("call-intel")).toContainText("claims & identity port");
    await page.getByTestId("call-after-tab").click();
    await expect(page.getByTestId("call-bridge")).toBeDisabled();
    expect(calls.some((p) => /call_prep|post_call|prep|post-call/.test(p))).toBe(false);
    await page.getByRole("button", { name: /Export memo/ }).click();
    await expect(page.getByTestId("call-md")).toBeVisible();
    w.expectClean();
  });

  test("editing a call saves and the detail shows it after a fresh load", async ({ page }) => {
    const w = watch(page);
    const ws = await workspace(page);
    const call = ws.companies.flatMap((c) => c.founders.flatMap((f) => f.calls))[0];
    test.skip(!call, "the preview data has no founder call");
    const tag = `E2E observation ${Math.random().toString(36).slice(2, 8)}`;
    const origin = new URL(process.env.PZ_BASE_URL ?? "http://localhost:5173").origin;
    const r = await page.request.post("/api/founder-calls/save", { data: { id: call.id, observations: tag }, headers: { Origin: origin } });
    expect(r.ok()).toBe(true);
    await page.goto(`/founder-calls?call=${call.id}`);
    await expect(page.getByTestId("call-detail")).toContainText(tag, { timeout: 60_000 });
    w.expectClean();
  });

  test("1366x768, 150% zoom and 1920: no horizontal overflow", async ({ page }) => {
    const w = watch(page);
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto("/founder-calls");
    await expect(page.getByTestId("calls-counts")).toBeVisible({ timeout: 60_000 });
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
