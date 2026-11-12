/**
 * News & Learning (reviews 028a, 028b) — the new app on a preview database (the real snapshot in a scratch schema).
 * Every section renders from the real reads, the sources view answers each window, the decision controls (028b) are
 * enabled and opening / cancelling the early-signal form writes nothing, the run controls (028c) are visible, disabled
 * and give their reason, the Scout Bridge button is gone, and the layout fits at the usual sizes. This spec NEVER
 * performs a write (no decision, audit or signal is clicked through): news-mocked.spec.ts asserts the exact POSTs, and the
 * stubbed page tests cover every panel in detail.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, watch as watchErrors, zoom150 } from "./helpers";

const TABS = ["Today", "All stories", "Caught early", "Misses", "Historical cases", "What's moving", "My companies", "Weekly review", "News sources"];
const WRITES_028B = "Recording News decisions arrives with the News writes port (028b)"; // the 028a deferral, gone
const REFRESH = "Refreshing News arrives with the News refresh port (028c)";

/** No page / console error (the shell's not-yet-ported endpoints aside, as everywhere) and no write request at all. */
function watch(page: Page) {
  const errors = watchErrors(page);
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.method() !== "GET" && r.url().includes("/api/")) writes.push(`${r.method()} ${new URL(r.url()).pathname}`);
    if (/\/api\/(news_backcast_job|bridge_create)\b/.test(r.url())) writes.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  return {
    expectClean: () => {
      errors.expectClean();
      expect(writes, writes.join(" | ")).toEqual([]);
    },
  };
}

const sections = (page: Page) => page.getByRole("tablist", { name: "News sections" });
const section = (page: Page, name: string) => sections(page).getByRole("tab", { name, exact: true }).click();

async function openNews(page: Page) {
  await page.goto("/news");
  await expect(page.getByTestId("news-concept")).toBeVisible({ timeout: 60_000 });
}

/** A section shows its stories (or its themes, review, sources) — or its empty text. */
async function rendered(page: Page, name: string) {
  if (name === "Weekly review") return expect(page.getByTestId("news-weekly")).toBeVisible();
  if (name === "News sources") return expect(page.getByTestId("news-sources-best")).toBeVisible({ timeout: 60_000 });
  if (name === "What's moving") return expect(page.getByTestId("news-theme").or(page.getByText("Two articles are not a trend.")).first()).toBeVisible();
  return expect(page.getByTestId("news-story").or(page.locator("[class*='empty']")).first()).toBeVisible();
}

async function expectDeferred(el: Locator, reason: string) {
  await expect(el).toBeVisible();
  await expect(el).toHaveAttribute("aria-disabled", "true");
  await expect(el).toHaveAttribute("title", reason);
  await el.click({ force: true }); // does nothing: no request below
}

test.describe("News & Learning — new app, preview database", () => {
  test("the header, the refresh line and every section render; nothing is written", async ({ page }) => {
    const w = watch(page);
    await openNews(page);
    await expect(page.getByRole("heading", { name: "News & Learning", level: 1 })).toBeVisible();
    await expect(page.getByTestId("news-concept")).toContainText("VC concept of the day");
    await expect(page.getByText("Project Zero vs the news")).toBeVisible();
    await expect(page.getByTestId("news-refresh")).toContainText(/Refresh (complete|partly done)|News refresh failed|Last refresh was interrupted|Not refreshed yet\./);
    await expect(page.getByTestId("news-refresh-progress")).toHaveCount(0); // no run is ever active in 028a
    await expect(sections(page).getByRole("tab")).toHaveText(TABS);
    for (const name of TABS) {
      await section(page, name);
      await expect(sections(page).getByRole("tab", { name, exact: true })).toHaveAttribute("aria-selected", "true");
      await rendered(page, name);
    }
    await expect(page.getByText(/^Last refresh: .*Project Zero started on/)).toBeVisible();
    w.expectClean();
  });

  test("the stories open: the check, the backcast or sources — and the Scout Bridge button is gone", async ({ page }) => {
    const w = watch(page);
    await openNews(page);
    await section(page, "All stories");
    const first = page.getByTestId("news-story").first();
    await expect(first).toBeVisible();
    await expect(first.getByTestId("news-check")).toContainText("Project Zero check");
    await first.getByRole("button", { name: /^(Backcast & sources|Sources & learning)$/ }).click();
    await expect(first.getByText("Sources", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /Prepare backcast research/ })).toHaveCount(0);
    await section(page, "Historical cases");
    const cases = page.getByTestId("news-story");
    if (await cases.count()) {
      await cases.first().getByRole("button", { name: "Backcast & sources" }).click();
      await expect(cases.first().getByTestId("news-backcast")).toContainText("Earliest plausible signal");
    }
    w.expectClean();
  });

  test("the run controls are disabled with their reason; the decisions are enabled (never clicked through here)", async ({ page }) => {
    const w = watch(page);
    await openNews(page);
    await expectDeferred(page.getByTestId("news-refresh-button"), REFRESH);
    await section(page, "All stories");
    const enabled = async (el: Locator) => {
      await expect(el).toBeVisible();
      await expect(el).toBeEnabled();
      await expect(el).not.toHaveAttribute("aria-disabled", "true");
    };
    const proposals = page.getByTestId("news-outcome-proposal");
    if (await proposals.count()) for (const name of ["Confirm outcome", "Reject", "Not enough evidence"]) await enabled(proposals.first().getByRole("button", { name, exact: true }));
    const audits = page.getByTestId("news-audit");
    if (await audits.count()) await enabled(audits.first());
    await expect(page.getByText(WRITES_028B)).toHaveCount(0);
    await expect(page.locator(`[title="${WRITES_028B}"]`)).toHaveCount(0);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await section(page, "News sources");
    await expectDeferred(page.getByTestId("news-sources").getByRole("button", { name: "Re-measure now" }), REFRESH);
    await page.waitForTimeout(300);
    w.expectClean();
  });

  test("'Add an early signal' opens the old form; cancelling (✕ or Escape) writes nothing", async ({ page }) => {
    const w = watch(page);
    await openNews(page);
    await section(page, "All stories");
    const important = page.getByTestId("news-story").filter({ hasText: "🔥 IMPORTANT" });
    test.skip((await important.count()) === 0, "no important story on this snapshot");
    const story = important.first();
    await story.getByRole("button", { name: /^(Backcast & sources|Sources & learning)$/ }).click();
    const add = story.getByRole("button", { name: "Add an early signal" });
    test.skip((await add.count()) === 0, "the first important story names no company");
    await expect(add).toBeEnabled();
    await add.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Add an early signal" })).toBeVisible();
    const save = dialog.getByRole("button", { name: "Add", exact: true });
    await expect(save).toBeDisabled();
    await dialog.getByRole("textbox", { name: "Date (YYYY, YYYY-MM or YYYY-MM-DD)" }).fill("2020");
    await dialog.getByRole("textbox", { name: "Source URL" }).fill("https://example.invalid/never-sent");
    await expect(save).toBeEnabled(); // ready, but never clicked: this spec writes nothing
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await add.click();
    await expect(dialog.getByRole("textbox", { name: "Date (YYYY, YYYY-MM or YYYY-MM-DD)" })).toHaveValue("2020"); // kept, as before
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.waitForTimeout(300);
    w.expectClean(); // no request other than GET reached /api
  });

  test("the sources view answers each window", async ({ page }) => {
    const w = watch(page);
    await openNews(page);
    await section(page, "News sources");
    const box = page.getByTestId("news-sources");
    await expect(box.getByTestId("news-sources-best")).toBeVisible({ timeout: 60_000 });
    for (const [name, window] of [
      ["30 days", "30"],
      ["180 days", "180"],
      ["All time", "all"],
    ]) {
      const answer = page.waitForResponse((r) => r.url().includes(`/api/news/sources?window=${window}`));
      await box.getByRole("tab", { name, exact: true }).click();
      expect((await answer).status()).toBe(200);
      await expect(box.getByTestId("news-sources-bias")).toContainText("How fair is this benchmark?");
    }
    const rows = box.getByTestId("news-source-row");
    expect(await rows.count()).toBeGreaterThan(0);
    await rows.first().getByRole("button", { name: "Details" }).click();
    await expect(rows.first().getByTestId("news-source-detail")).toContainText("Coverage");
    w.expectClean();
  });

  for (const size of [{ width: 1366, height: 900 }, { width: 1920, height: 1080 }, { width: 390, height: 844 }]) {
    test(`no horizontal overflow at ${size.width}`, async ({ page }) => {
      await page.setViewportSize(size);
      await openNews(page);
      for (const name of TABS) {
        await section(page, name);
        await rendered(page, name);
        await expectNoHorizontalOverflow(page);
      }
    });
  }

  test("no horizontal overflow at 150 %", async ({ page }) => {
    await openNews(page);
    await zoom150(page);
    for (const name of TABS) {
      await section(page, name);
      await rendered(page, name);
      await expectNoHorizontalOverflow(page);
    }
  });
});
