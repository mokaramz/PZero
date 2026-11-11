/**
 * Network and Watchlist — the core cases of the old `e2e/tests/network.spec.ts` / `watchlist-work.spec.ts`, against
 * the new app on a preview database (the real snapshot in a scratch schema; writes land only there). Review 013.
 * The old spec mocked a 7-person fixture; here people are picked from the live payload instead.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, recordPosts, watch, zoom150 } from "./helpers";

type Person = { id: string; name: string; notes?: string; watch?: boolean; company?: string; next_action?: string };
const people = async (page: Page) => ((await (await page.request.get("/api/network/people")).json()).people as Person[]);
const byId = async (page: Page, id: string) => (await people(page)).find((p) => p.id === id);
const saves = (posted: ReturnType<typeof recordPosts>) => posted.filter((p) => p.path === "/api/network/person_save");

async function openPerson(page: Page, p: Person) {
  await page.goto(`/network?person=${p.id}`);
  await expect(page.getByTestId("person-profile").getByRole("heading", { name: p.name })).toBeVisible({ timeout: 60_000 });
}

test.describe("Network — new app, preview database", () => {
  test("list, segments, search and profile", async ({ page }) => {
    const w = watch(page);
    const all = await people(page);
    await page.goto("/network");
    await expect(page.getByText("Relationships — who you know, how warm it is, and what to do next.")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("people-counts")).toHaveText(/\d+ relationships · \d+ due · \d+ from chains/);
    await expect(page.getByTestId("person-profile")).toBeVisible();
    await page.getByRole("button", { name: /^Due/ }).click();
    const rows = page.getByTestId("person-row");
    for (const r of await rows.all()) await expect(r.getByText("DUE", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /^All/ }).click();
    const target = all.find((p) => p.name.length > 6) ?? all[0];
    await page.getByLabel("Search people").fill(target.name);
    await expect(rows.filter({ hasText: target.name }).first()).toBeVisible();
    await rows.filter({ hasText: target.name }).first().click();
    await expect(page).toHaveURL(new RegExp(`person=${target.id}`));
    w.expectClean();
  });

  test("follow-up and contact log save, checked against a fresh read", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    const p = (await people(page))[2];
    await openPerson(page, p);
    const rail = page.getByTestId("person-rail");
    await rail.getByLabel("Next action", { exact: true }).fill("E2E coffee");
    await rail.getByLabel("Next action date").fill("2026-12-03");
    await rail.getByRole("button", { name: "Save follow-up" }).click();
    await expect(page.getByText("Follow-up saved")).toBeVisible();
    expect(saves(posted)[0].body).toEqual({ id: p.id, next_action: "E2E coffee", next_action_date: "2026-12-03" });
    expect(await byId(page, p.id)).toMatchObject({ next_action: "E2E coffee", next_action_date: "2026-12-03" });
    await rail.getByLabel("Interaction note").fill("talked spin-out");
    await rail.getByRole("button", { name: "Log contact today" }).click();
    await expect.poll(() => saves(posted).length).toBe(2);
    const today = new Date().toISOString().slice(0, 10);
    await expect.poll(async () => (await byId(page, p.id))?.notes ?? "", { timeout: 20_000 }).toMatch(
      new RegExp(`${today} — talked spin-out$`),
    );
    w.expectClean();
  });

  test("the talented ritual creates linked people once", async ({ page }) => {
    const w = watch(page);
    const host = (await people(page))[3];
    await openPerson(page, host);
    const inline = page.getByTestId("talented-inline");
    await inline.getByRole("button", { name: "Create linked people" }).click();
    await expect(page.getByText("Enter at least one name")).toBeVisible();
    const name = `E2E Talent ${Date.now()}`;
    await inline.getByLabel(/person 1$/).fill(name);
    await inline.getByRole("button", { name: "Create linked people" }).click();
    await expect(page.getByText(/1 people? created & linked/)).toBeVisible();
    const created = (await people(page)).filter((p) => p.name === name);
    expect(created).toHaveLength(1);
    expect((await byId(page, host.id)) as unknown as { recommended?: string[] }).toMatchObject({ recommended: expect.arrayContaining([created[0].id]) });
    w.expectClean();
  });

  test("+ Person adds; the same name again offers the existing person", async ({ page }) => {
    const w = watch(page, { expected: [409] });
    await page.goto("/network");
    await expect(page.getByTestId("people-counts")).toBeVisible({ timeout: 60_000 });
    const name = `E2E Person ${Date.now()}`;
    for (const attempt of [1, 2]) {
      await page.getByRole("button", { name: "+ Person" }).click();
      const dlg = page.getByRole("dialog");
      await dlg.getByLabel("Name", { exact: true }).fill(name);
      await dlg.getByRole("button", { name: /^Save/ }).click();
      if (attempt === 1) await expect(page.getByTestId("person-profile").getByRole("heading", { name })).toBeVisible();
    }
    await expect(page.getByTestId("save-duplicate")).toBeVisible();
    await page.getByTestId("save-duplicate").getByRole("button", { name: "Open existing person" }).click();
    await expect(page.getByTestId("person-profile").getByRole("heading", { name })).toBeVisible();
    expect((await people(page)).filter((p) => p.name === name)).toHaveLength(1);
    w.expectClean();
  });

  test("Watchlist: a watched person can be logged", async ({ page }) => {
    const w = watch(page);
    const p = (await people(page))[4];
    const origin = new URL(page.url() === "about:blank" ? (process.env.PZ_BASE_URL ?? "http://localhost:5173") : page.url()).origin;
    const mark = await page.request.post("/api/network/person_save", { data: { id: p.id, watch: true }, headers: { Origin: origin } });
    expect(mark.ok()).toBe(true);
    await page.goto("/watchlist");
    const row = page.getByRole("row").filter({ hasText: p.name });
    await expect(row).toBeVisible({ timeout: 60_000 });
    await row.getByRole("textbox").fill("E2E signal");
    await row.getByRole("button").filter({ hasText: /Log|Mark/ }).first().click();
    await expect(page.getByText(/Signal logged|Marked checked/)).toBeVisible();
    expect((await byId(page, p.id))?.notes ?? "").toContain("signal] E2E signal");
    w.expectClean();
  });

  test("1366x768, 150% zoom and 1920: no horizontal overflow", async ({ page }) => {
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto("/network");
    await expect(page.getByTestId("people-counts")).toBeVisible({ timeout: 60_000 });
    await expectNoHorizontalOverflow(page);
    await zoom150(page);
    await page.waitForTimeout(300);
    await expectNoHorizontalOverflow(page);
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(300);
    await expectNoHorizontalOverflow(page);
  });
});
