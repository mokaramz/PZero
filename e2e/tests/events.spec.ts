/**
 * Events — the read cases of the old `e2e/tests/events.spec.ts`, against the new app on a preview database (the real
 * snapshot in a scratch schema). Review 015 is read-only: every write keeps its place, disabled with its reason, and
 * sends nothing. The old spec mocked a fixture; here events are picked from the live payload.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, recordPosts, watch } from "./helpers";

type When = { group: string; start_date: string; end_date: string };
type Ev = {
  id: string;
  name: string;
  past: boolean;
  status?: string;
  when: When;
  eligibility: { tier: string; label: string };
  action: { state: string };
  place: { city: string; area: string; area_label: string };
};
type Payload = { events: Ev[]; scout_reports: Array<{ key: string; name: string; tracked_event_id: string }>; today: string };

const payload = async (page: Page): Promise<Payload> => (await page.request.get("/api/events")).json();
const card = (page: Page, id: string) => page.locator(`[data-testid="event-card"][data-event-id="${id}"]`);
const upcoming = (p: Payload) => p.events.filter((e) => !e.past && e.status !== "attended" && e.when.group !== "undated");
const more = async (page: Page, item: string | RegExp) => {
  await page.getByRole("button", { name: /^More/ }).first().click();
  await page.getByRole("menuitem", { name: item }).click();
};

async function openEvents(page: Page, url = "/events") {
  await page.goto(url);
  await expect(page.getByTestId("event-counts")).toBeVisible({ timeout: 60_000 });
}

test.describe("Events — new app, preview database", () => {
  test("timeline default view, calendar, source health and Where should I go", async ({ page }) => {
    const w = watch(page);
    const p = await payload(page);
    await openEvents(page);
    await expect(page.getByRole("heading", { name: "Events", level: 1 })).toBeVisible();
    await expect(page.getByText("Discover where founders and investors gather.")).toBeVisible();
    await expect(page.getByTestId("event-counts")).toHaveText(/\d+ upcoming · \d+ planned/);
    await expect(page.getByRole("tab", { name: /^Upcoming/ })).toHaveAttribute("aria-selected", "true");
    for (const v of ["Priority", "Planned", "Scout suggestions"]) await expect(page.getByRole("tab", { name: new RegExp(`^${v}`) })).toBeVisible();
    await expect(page.getByTestId("event-calendar")).toBeVisible();
    const first = upcoming(p).find((e) => e.eligibility.tier !== "REJECTED");
    expect(first, "the snapshot has an upcoming event").toBeTruthy();
    await expect(page.getByTestId("timeline").getByTestId("event-card").first()).toBeVisible();
    await page.getByRole("tab", { name: /^Priority/ }).click();
    const ws = page.getByTestId("wsig");
    await expect(ws).toContainText("Where should I go?");
    const wsig30 = page.waitForResponse((r) => r.url().includes("/api/events/wsig") && r.url().includes("days=30"));
    await page.getByLabel("Where should I go window").selectOption("30");
    expect((await wsig30).status()).toBe(200);
    await more(page, "Source health & scanner log");
    const h = page.getByTestId("event-health");
    await expect(h).toContainText("separate from startup-source health · persists across reloads");
    await expect(page.getByText("Manual sources — weekly 10-min routine")).toBeVisible();
    w.expectClean();
  });

  test("calendar days filter the list, and the filter pill removes it", async ({ page }) => {
    const w = watch(page);
    const p = await payload(page);
    const month = p.today.slice(0, 7);
    const day = upcoming(p).find((e) => e.eligibility.tier !== "REJECTED" && e.when.start_date.startsWith(month) && e.when.start_date > p.today);
    test.skip(!day, "no upcoming event later this month in the snapshot");
    await openEvents(page);
    const d = new Date(`${day!.when.start_date}T12:00:00`);
    const label = new RegExp(`^${d.getDate()} ${d.toLocaleDateString("en-GB", { month: "long" })}: \\d+ events?$`);
    await page.getByTestId("event-calendar").getByRole("button", { name: label }).click();
    const pills = page.getByLabel("Active filters");
    await expect(pills).toBeVisible();
    await expect(page.getByTestId("timeline").getByTestId("event-card").first()).toBeVisible();
    await pills.getByRole("button", { name: /^Remove / }).first().click();
    await expect(pills).toHaveCount(0);
    w.expectClean();
  });

  test("general / rejected events are shown only when asked, with their reason", async ({ page }) => {
    const w = watch(page);
    const p = await payload(page);
    const rejected = upcoming(p).find((e) => e.eligibility.tier === "REJECTED");
    test.skip(!rejected, "no upcoming rejected event in the snapshot");
    await openEvents(page);
    await expect(card(page, rejected!.id)).toHaveCount(0);
    await page.getByRole("button", { name: /^More filters/ }).click();
    await page.getByLabel("Include general / rejected events").check();
    await page.getByRole("button", { name: /^Show \d+ later events?$/ }).click().catch(() => undefined);
    await expect(card(page, rejected!.id)).toContainText("Not recommended:");
    w.expectClean();
  });

  test("toolbar never overlaps content (5 viewport / zoom combos)", async ({ page }) => {
    for (const [wd, ht, z] of [[1366, 768, 1], [1366, 900, 1], [1920, 1080, 1], [1366, 768, 1.25], [1366, 768, 1.5]] as const) {
      await page.setViewportSize({ width: Math.round(wd / z), height: Math.round(ht / z) });
      await openEvents(page);
      await expect(page.getByTestId("timeline")).toBeVisible();
      await expectNoHorizontalOverflow(page);
      const r = await page.evaluate(async () => {
        const bar = document.querySelector('[aria-label="Events view"]')!.parentElement!;
        const samples = [...document.querySelectorAll('[data-testid="event-card"], [data-testid="suggestion-card"], [data-testid="event-calendar"]')].slice(0, 60);
        let covered = 0;
        let checked = 0;
        for (let y = 0; y <= document.body.scrollHeight; y += Math.max(200, innerHeight * 0.6)) {
          window.scrollTo(0, y);
          await new Promise((res) => setTimeout(res, 40));
          for (const s of samples) {
            const rc = s.getBoundingClientRect();
            if (rc.bottom < 0 || rc.top > innerHeight) continue;
            checked++;
            const el = document.elementFromPoint(Math.min(innerWidth - 2, rc.left + 8), Math.max(1, rc.top + 8));
            if (el && bar.contains(el)) covered++;
          }
        }
        return { covered, checked };
      });
      expect(r.checked, `${wd}x${ht}@${z}`).toBeGreaterThan(0);
      expect(r.covered, `${wd}x${ht}@${z}`).toBe(0);
    }
  });

  test("deep link opens the event with its score; the decision buttons are disabled and send nothing", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    const p = await payload(page);
    const hs = upcoming(p).find((e) => e.eligibility.tier === "HIGH-SIGNAL");
    expect(hs, "the snapshot has an upcoming high-signal event").toBeTruthy();
    await openEvents(page, `/events?event=${encodeURIComponent(hs!.id)}&edit=1`);
    const dlg = page.getByRole("dialog");
    await expect(dlg.getByTestId("event-detail")).toBeVisible();
    await expect(page).not.toHaveURL(/edit=1/); // the form waits for review 016: only the event is shown
    await dlg.getByText("Evidence & scoring").click();
    await expect(page.getByTestId("event-score")).toBeVisible();
    for (const name of ["GO", "MAYBE", "SKIP"]) {
      const b = dlg.getByRole("button", { name, exact: true });
      await expect(b).toHaveAttribute("aria-disabled", "true");
      await expect(b).toHaveAttribute("title", /event writes port/);
      await b.click({ force: true }); // aria-disabled: a forced click must still do nothing
    }
    expect(posted).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(page).toHaveURL(/\/events$/);
    w.expectClean();
  });

  test("a sold-out event is never offered as Register", async ({ page }) => {
    const p = await payload(page);
    const so = upcoming(p).find((e) => e.action.state === "sold_out");
    test.skip(!so, "no upcoming sold-out event in the snapshot");
    await openEvents(page, `/events?event=${encodeURIComponent(so!.id)}`);
    const rail = page.getByRole("complementary", { name: "Decision" });
    await expect(rail.getByRole("button", { name: "Sold out" })).toBeDisabled();
    await expect(rail).not.toContainText("Register");
  });

  test("the sourcing weekend is a read: one GET with the window, missions or an honest empty state", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    await openEvents(page);
    await more(page, "Weekend plan");
    const wk = page.getByTestId("weekend-plan");
    await expect(wk).toContainText("Network-density optimization, not tourism");
    const get = page.waitForRequest((r) => r.url().includes("/api/events/weekend"));
    await wk.getByRole("button", { name: "Build missions" }).click();
    const url = new URL((await get).url());
    expect((await get).method()).toBe("GET");
    expect([...url.searchParams.keys()].sort()).toEqual(["end", "start"]);
    await expect(wk).toContainText(/#1|Expected:|No /);
    expect(posted).toEqual([]);
    w.expectClean();
  });

  test("Scout 00 suggestions are labelled suggestions; their actions are disabled", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    const p = await payload(page);
    const open = p.scout_reports.filter((r) => !r.tracked_event_id);
    test.skip(!p.scout_reports.length, "no Scout 00 report in the snapshot");
    await openEvents(page);
    await page.getByRole("tab", { name: /^Scout suggestions/ }).click();
    const cards = page.getByTestId("suggestion-card");
    if (open.length) {
      // a report Events does not track yet is a labelled suggestion, never an event card
      await expect(cards.first()).toContainText("Scout 00 ·");
      await expect(cards.first()).toContainText("not on Events yet");
      const add = cards.getByRole("button", { name: "Add to Events" }).first();
      await expect(add).toHaveAttribute("aria-disabled", "true");
      await add.click({ force: true });
    } else {
      // every report is already tracked: the view lists those events, and no suggestion card
      await expect(page.getByTestId("timeline").getByTestId("event-card").first()).toBeVisible();
      await expect(cards).toHaveCount(0);
      await expect(page.getByTestId("event-counts")).toContainText("0 Scout 00 suggestions not on Events yet");
    }
    expect(posted).toEqual([]);
    w.expectClean();
  });

  test("geography reads as place and area; a suburb is never its own filter option", async ({ page }) => {
    const w = watch(page);
    const p = await payload(page);
    await openEvents(page);
    const opts = await page.getByRole("combobox", { name: "City or region" }).locator("option").allInnerTexts();
    for (const e of p.events.filter((x) => x.place.city && x.place.city !== x.place.area)) {
      expect(opts.some((o) => o.startsWith(`${e.place.city},`) || o.startsWith(`${e.place.city} (`))).toBe(false);
    }
    w.expectClean();
  });

  test("empty state says why the view is empty and offers the ways out", async ({ page }) => {
    const w = watch(page);
    await openEvents(page);
    await page.getByRole("tab", { name: /^Planned/ }).click();
    await page.getByRole("combobox", { name: "Date" }).selectOption("7");
    const empty = page.getByTestId("events-empty");
    if (await empty.count()) {
      await expect(empty).toContainText("No events in Planned");
      await empty.getByRole("button", { name: "Clear filters" }).click();
    }
    w.expectClean();
  });

  test("every deferred control explains itself and sends nothing", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    await openEvents(page);
    const deferred = page.locator("[data-deferred]");
    const n = await deferred.count();
    expect(n).toBeGreaterThan(0);
    for (let i = 0; i < Math.min(n, 25); i++) {
      const el = deferred.nth(i);
      await expect(el).toHaveAttribute("title", /arrive|arrives/);
      if (await el.isVisible()) await el.click({ force: true });
    }
    expect(posted).toEqual([]);
    w.expectClean();
  });
});
