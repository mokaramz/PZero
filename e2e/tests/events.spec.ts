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

  test("deep link opens the event with its score; GO saves the status (checked against a fresh read)", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    const p = await payload(page);
    const hs = upcoming(p).find((e) => e.eligibility.tier === "HIGH-SIGNAL" && e.status !== "planned");
    expect(hs, "the snapshot has an upcoming high-signal event").toBeTruthy();
    await openEvents(page, `/events?event=${encodeURIComponent(hs!.id)}`);
    const dlg = page.getByRole("dialog");
    await expect(dlg.getByTestId("event-detail")).toBeVisible();
    await dlg.getByText("Evidence & scoring").click();
    await expect(page.getByTestId("event-score")).toBeVisible();
    await dlg.getByRole("button", { name: "GO", exact: true }).click();
    await expect(page.getByText("Status → planned")).toBeVisible();
    expect(posted.filter((x) => x.path === "/api/events/save").map((x) => x.body)).toEqual([{ id: hs!.id, status: "planned" }]);
    await expect.poll(async () => (await payload(page)).events.find((e) => e.id === hs!.id)?.status).toBe("planned");
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

  test("Scout 00 suggestions are labelled suggestions, never shown as tracked", async ({ page }) => {
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
      await expect(cards.getByRole("button", { name: "Add to Events" }).first()).toBeEnabled();
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

  test("only the source scan is deferred: it explains itself and sends nothing", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    await openEvents(page);
    await page.getByRole("button", { name: /^More/ }).first().click();
    const scan = page.locator("[data-deferred]").filter({ hasText: "Scan sources" }).first();
    await expect(scan).toHaveAttribute("title", /event source scan port/);
    await scan.click({ force: true });
    for (const t of await page.locator("[data-deferred]").evaluateAll((els) => els.map((e) => e.getAttribute("title")))) {
      expect(t).toMatch(/event source scan port/); // nothing else is deferred any more
    }
    expect(posted).toEqual([]);
    w.expectClean();
  });
});

test.describe("Events writes — new app, preview database (review 016)", () => {
  type Rec = Ev & { price?: unknown; url?: string; notes?: string };
  const posts = (posted: ReturnType<typeof recordPosts>, path: string) => posted.filter((x) => x.path === `/api/events/${path}`);
  const find = async (page: Page, id: string) => (await payload(page)).events.find((e) => e.id === id) as Rec | undefined;

  test("+ Event auto-suggests the ladder and saves; a conflicting duplicate offers the existing event", async ({ page }) => {
    const w = watch(page, { expected: [409] });
    const posted = recordPosts(page);
    await openEvents(page);
    // two random letter words: never "similar" (the old dedup) to an event an earlier run left behind
    const word = () => Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8);
    const name = `${word()} ${word()} Founder Night`;
    const fill = async (city: string) => {
      await page.getByRole("button", { name: "+ Event" }).click();
      const form = page.getByRole("form", { name: "Event form" });
      await form.getByLabel("Event name").fill(name);
      await form.getByLabel(/^Start/).fill("2026-12-04");
      await form.getByLabel("City").fill(city);
      await form.getByRole("button", { name: "Save event" }).click();
    };
    await fill("Karlsruhe");
    await expect(page.getByRole("dialog", { name })).toBeVisible(); // saved: it opens
    await page.keyboard.press("Escape"); // the saved event opens in its drawer; close it before the next add
    expect(Object.keys((posts(posted, "save")[0].body as { score_parts: object }).score_parts)).toHaveLength(7);
    await expect.poll(async () => (await payload(page)).events.filter((e) => e.name === name).length).toBe(1);
    await fill("Berlin"); // the same name and date in another city
    await expect(page.getByTestId("save-collision")).toContainText("already exists with different details");
    await page.getByTestId("save-collision").getByRole("button", { name: "Open existing event" }).click();
    await expect(page.getByRole("dialog", { name })).toBeVisible();
    expect((await payload(page)).events.filter((e) => e.name === name)).toHaveLength(1);
    w.expectClean();
  });

  test("an edit keeps a structured price", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    const ev = (upcoming(await payload(page)) as Rec[]).find((e) => e.price && typeof e.price === "object");
    test.skip(!ev, "no upcoming event with a structured price in the snapshot");
    await openEvents(page, `/events?event=${encodeURIComponent(ev!.id)}`);
    await page.getByRole("button", { name: "Edit event & notes" }).click();
    const form = page.getByRole("form", { name: "Event form" });
    await form.getByLabel("Notes").fill("e2e (edited)");
    await form.getByRole("button", { name: "Save event" }).click();
    await expect(page.getByText("Event saved & scored")).toBeVisible();
    expect((posts(posted, "save")[0].body as Rec).price).toEqual(ev!.price);
    await expect.poll(async () => (await find(page, ev!.id))?.notes).toBe("e2e (edited)");
    expect((await find(page, ev!.id))?.price).toEqual(ev!.price);
    w.expectClean();
  });

  test("a needs-review event can be verified", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    const nr = upcoming(await payload(page)).find((e) => e.eligibility.label === "NEEDS REVIEW");
    test.skip(!nr, "no upcoming needs-review event in the snapshot");
    await openEvents(page, `/events?event=${encodeURIComponent(nr!.id)}`);
    await page.getByRole("dialog").getByRole("button", { name: "Mark as verified" }).click();
    await expect(page.getByText("Marked as verified by you — now eligible (HUMAN JUDGMENT)")).toBeVisible();
    expect(posts(posted, "verify").map((x) => x.body)).toEqual([{ id: nr!.id, verified: true }]);
    await expect.poll(async () => (await find(page, nr!.id))?.eligibility.label).toBe("VERIFIED BY YOU");
    w.expectClean();
  });

  test("leads: dismiss posts the old body; convert is ONE save carrying the lead", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    const openLeads = async () => ((await (await page.request.get("/api/events")).json()).leads as Array<{ id: string; title: string }>);
    const leads = await openLeads();
    test.skip(leads.length < 2, "fewer than two open leads in the snapshot");
    await openEvents(page);
    await more(page, /^Leads/);
    const rows = await page.getByRole("button", { name: "Convert" }).count();
    await page.getByRole("button", { name: "Dismiss" }).first().click();
    await expect.poll(() => posts(posted, "lead").length).toBe(1);
    await expect(page.getByRole("button", { name: "Convert" })).toHaveCount(rows - 1); // the list refreshed
    const dismissed = posts(posted, "lead")[0].body as { id: string; decision: string };
    expect(dismissed.decision).toBe("dismissed");
    expect(leads.map((x) => x.id)).toContain(dismissed.id); // the page lists leads in its own order
    await page.getByRole("button", { name: "Convert" }).first().click();
    const form = page.getByRole("form", { name: "Event form" });
    const title = await form.getByLabel("Event name").inputValue();
    const converting = leads.find((x) => x.title === title && x.id !== dismissed.id);
    expect(converting, "the form is prefilled with an open lead").toBeTruthy();
    if (!(await form.getByLabel(/^Start/).inputValue())) await form.getByLabel(/^Start/).fill("2026-12-11");
    await form.getByRole("button", { name: "Save event" }).click();
    await expect.poll(() => posts(posted, "save").length).toBe(1);
    expect((posts(posted, "save")[0].body as { convert_lead?: string }).convert_lead).toBe(converting!.id);
    expect(posts(posted, "lead")).toHaveLength(1); // no second request
    await expect.poll(async () => (await openLeads()).map((x) => x.id)).not.toContain(converting!.id);
    w.expectClean();
  });

  test("debrief after attending: people and Deal Flow leads", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    const ev = ((await payload(page)).events as Rec[]).find((e) => e.past && e.url?.startsWith("http"));
    test.skip(!ev, "no past event with a URL in the snapshot");
    const stamp = Date.now();
    const person = `E2E Met Person ${stamp}`;
    await openEvents(page, `/events?event=${encodeURIComponent(ev!.id)}&debrief=1`);
    const f = page.getByTestId("debrief-form");
    await expect(f).toContainText("The loop: Event → Person → Talent Graph → Founder → Startup.");
    await f.getByLabel("Person 1", { exact: true }).fill(person);
    await f.getByLabel("Person 1 — why interesting / what they do").fill("Builds grid batteries");
    await f.getByLabel("Startup/team 1", { exact: true }).fill(`E2E Startup ${stamp}`);
    await f.getByLabel("Startup/team 1 — what they do").fill("Battery analytics");
    await f.getByRole("button", { name: "Save debrief" }).click();
    await expect(page.getByText(/1 people? added, 1 startup leads? → Deal Flow/)).toBeVisible();
    expect(posts(posted, "debrief")[0].body).toMatchObject({ id: ev!.id, people_met: [{ name: person, note: "Builds grid batteries" }] });
    const people = (await (await page.request.get("/api/network/people")).json()).people as Array<{ name: string }>;
    expect(people.some((x) => x.name === person)).toBe(true);
    await expect.poll(async () => (await find(page, ev!.id))?.status).toBe("attended");
    w.expectClean();
  });
});
