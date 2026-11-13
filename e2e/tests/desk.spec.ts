/**
 * Investment Desk (review 031a) — the new app on a preview database (the real snapshot in a scratch schema). The desk
 * renders from the five real reads (`GET /api/home`, `/api/deal-flow/inbox`, `/api/conviction/pipeline`, `/api/today`,
 * `/api/sources`) and matches them: the payload key for key, the tiles and the flow from the same counts, the Manager
 * decisions, the best opportunity, the event and the machine section. Every link and navigation button lands on a
 * ported route, the weekly drawer opens, the deferred Agent Review Queue stays inert with its visible note (revision 2),
 * the desk builds no review link, and the layout fits at the usual sizes.
 * This spec only READS: nothing here clicks a write control (the weekly drawer is opened, never generated), and every
 * request it sees must be a GET. desk-mocked.spec.ts covers every branch on invented payloads.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, watch as watchErrors, zoom150 } from "./helpers";

type Signal = { slug: string; company: string; status?: string; conflict?: string; twin?: string; op?: { status: string } };
type Home = {
  priority: { slug: string; company: string; score: number; verified: boolean } | null;
  best_event: { name: string; weekend?: boolean } | null;
  progress: { found?: number };
};
type Inbox = { candidates: Array<{ decision?: string }>; last_run: string | null; last_summary?: { new?: number } };

const GREETING = /^(Good (morning|afternoon|evening)|Welcome back), Smooth Operator\.$/;
const NOTE = "The Agent Review Queue arrives with the analysis port";
const NAVY = "rgb(31, 43, 61)";

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

const read = async <T>(page: Page, path: string): Promise<T> => (await (await page.request.get(`/api/${path}`)).json()) as T;
const gatedOf = (e: Signal) => e.conflict === "potential_conflict" || e.op?.status === "CONFLICT GATED";

/** Open the desk and wait for the three reads that follow the inbox (the tiles and the rows count them). */
async function open(page: Page) {
  const later = ["/api/conviction/pipeline", "/api/today", "/api/sources"].map((p) =>
    page.waitForResponse((r) => new URL(r.url()).pathname === p && r.request().method() === "GET", { timeout: 90_000 }),
  );
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: GREETING })).toBeVisible({ timeout: 60_000 });
  await Promise.all(later);
  await expect(page.getByRole("list", { name: "Orientation" }).getByRole("listitem")).toHaveCount(4);
}

const machine = (page: Page) => page.getByTestId("desk-machine");
const unfoldMachine = async (page: Page) => {
  if (!(await machine(page).evaluate((d) => (d as HTMLDetailsElement).open))) await machine(page).locator("summary").click();
};
const tileN = (page: Page, i: number) => page.getByRole("list", { name: "Orientation" }).getByRole("listitem").nth(i).locator("[class*=tileN]");
const hrefs = (page: Page) => page.locator("main a[href]").evaluateAll((els) => els.map((e) => e.getAttribute("href") ?? ""));

/** A route of the app that is ported: neither "Page not found." nor the not-ported placeholder, and not the desk. */
async function expectInAppRoute(page: Page, link: string) {
  const want = new URL(link, "http://x");
  // Deal Flow consumes its deep-link parameters (`?candidate=`, `?find=1`) once the inbox is there
  await expect(page).toHaveURL((u) => u.pathname === want.pathname && (u.search === want.search || want.pathname === "/deal-flow"), { timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("heading", { level: 1, name: GREETING })).toHaveCount(0);
  await expect(page.getByText("Page not found.")).toHaveCount(0);
  await expect(page.getByTestId("not-ported")).toHaveCount(0);
}

test.describe("Investment Desk — new app, preview database", () => {
  test("the desk renders the server's payloads: brief, tiles, Manager decisions, best opportunity, event, machine; nothing is written", async ({ page }) => {
    const w = watch(page);
    const home = await read<Home>(page, "home");
    expect(Object.keys(home)).toEqual(["priority", "best_event", "due", "new_signals", "latest_signals", "omar", "progress", "watch", "weekday", "date"]);
    const ib = await read<Inbox>(page, "deal-flow/inbox");
    const sig = (await read<{ signals: Signal[] }>(page, "conviction/pipeline")).signals.filter((e) => e.status !== "dropped");
    const gated = sig.filter(gatedOf);
    const awaiting = sig.filter((e) => e.op?.status === "AWAITING FOUNDER RESPONSE");
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page);
    await expect(page.getByTestId("desk-context")).toHaveText(/^\w+day, \d{1,2} \w{3} · \d{2}:\d{2}$/);
    await expect(page.getByTestId("desk-summary")).toHaveText(/^(Deal flow is active: .+\.|Nothing needs your judgment right now — the machine is handling the rest\.)$/);
    for (const name of ["Priority missions", "Manager decisions", "Best opportunity", "Promising signals", "Upcoming event", "Recent activity"])
      await expect(page.getByRole("region", { name })).toBeVisible();
    expect(await page.getByTestId("desk-job").count()).toBeLessThanOrEqual(5);
    // the tiles against the reads
    await expect(tileN(page, 1)).toHaveText(String(gated.length));
    await expect(tileN(page, 2)).toHaveText(String(awaiting.length));
    await expect(tileN(page, 3)).toHaveText(String(ib.candidates.filter((c) => c.decision === "new").length));
    // the flow from the same counts: Review = Priority missions, Manager = Manager decisions, Decision = Conviction
    const nums = (await page.getByTestId("desk-flow").locator("li b").allTextContents()).map(Number);
    expect(String(nums[1])).toBe((await tileN(page, 0).textContent())?.trim());
    expect(nums[2]).toBe(gated.length);
    expect(nums[3]).toBe(sig.length);
    // Manager decisions: the first three gated companies, in Conviction's order
    const mgr = page.getByTestId("desk-manager");
    if (gated.length) await expect(mgr.getByRole("listitem").locator("b")).toHaveText(gated.slice(0, 3).map((e) => e.company));
    else await expect(mgr).toContainText("Nothing waits on the Manager.");
    // the best opportunity is the server's pick
    const best = page.getByTestId("desk-best");
    if (home.priority) {
      await expect(best.getByRole("button").first()).toHaveText(home.priority.company);
      await expect(best).toContainText(home.priority.verified ? "Verified" : "Provisional");
      await expect(best.getByRole("link", { name: /Open the case/ })).toHaveAttribute("href", `/conviction?company=${encodeURIComponent(home.priority.slug)}`);
    } else await expect(best).toContainText("No clear leader yet");
    // the event
    const ev = page.getByTestId("desk-event");
    if (home.best_event) {
      await expect(ev).toContainText(home.best_event.name);
      await expect(ev.getByRole("heading", { level: 2 })).toHaveText(home.best_event.weekend ? "This weekend" : "Upcoming event");
    } else await expect(ev).toContainText("No dated upcoming event — scan sources in Events.");
    // machine work last and folded; its line from the inbox's last scan
    expect(await machine(page).evaluate((d) => (d as HTMLDetailsElement).open)).toBe(false);
    await expect(machine(page).locator("summary")).toContainText(`${ib.last_summary?.new ?? home.progress.found ?? 0} new in the last scan · `);
    await unfoldMachine(page);
    await expect(page.getByTestId("desk-pulse")).toContainText("source health warnings");
    // one filled primary; orientation, not a text wall; role labels
    const filled = await page
      .locator("main")
      .evaluate((m, navy) => Array.from(m.querySelectorAll("a, button")).filter((b) => (b as HTMLElement).checkVisibility() && getComputedStyle(b).backgroundColor === navy).length, NAVY);
    expect(filled).toBeLessThanOrEqual(1);
    expect(await page.locator("main").evaluate((m) => (m.textContent?.match(/\bOmar\b|\bMohamed\b/g) ?? []).length), "role labels").toBe(0);
    w.expectClean();
  });

  test("the approved composition and the flow trace: contained concepts, one navy anchor, the path draws once and stops", async ({ page }) => {
    const w = watch(page);
    await open(page);
    for (const id of ["desk-missions", "desk-manager", "desk-best", "desk-signals", "desk-event", "desk-activity"]) {
      const box = await page.getByTestId(id).evaluate((el) => {
        const s = getComputedStyle(el);
        return s.backgroundColor !== "rgba(0, 0, 0, 0)" && parseFloat(s.borderTopWidth) > 0 && parseFloat(s.borderBottomWidth) > 0;
      });
      expect(box, `${id} is a contained card`).toBe(true);
    }
    expect(await page.getByTestId("desk-best").evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(NAVY);
    const f = page.getByTestId("desk-flow");
    await expect(f.locator("li span")).toHaveText(["Signals", "Review", "Manager", "Decision"]);
    expect((await f.getByRole("img").getAttribute("aria-label")) ?? "").toMatch(
      /^Today's operating flow: Signals \d+ \(new · 14 days\) → Review \d+ \(need you\) → Manager \d+ \(blocked\) → Decision \d+ \(in Conviction\)$/,
    );
    const line = f.locator("path.pz-trace");
    expect(await line.evaluate((el) => getComputedStyle(el).animationIterationCount)).toBe("1");
    await expect.poll(() => line.evaluate((el) => Number(getComputedStyle(el).strokeDashoffset.replace("px", ""))), { timeout: 3000 }).toBe(0);
    await page.waitForTimeout(1200);
    expect(await f.evaluate((el) => el.getAnimations({ subtree: true }).filter((a) => a.playState === "running").length)).toBe(0);
    w.expectClean();
  });

  test("reduced motion: the final state at once", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    await open(page);
    const f = page.getByTestId("desk-flow");
    for (const el of await f.locator("[data-stage]").all()) expect(Number(await el.evaluate((x) => getComputedStyle(x).opacity))).toBe(1);
    await expect.poll(() => f.locator("path").evaluate((el) => Number(getComputedStyle(el).strokeDashoffset.replace("px", "")))).toBe(0);
  });

  test("every in-app link and navigation button lands on a ported route", async ({ page }) => {
    test.setTimeout(900_000); // the desk is reopened for every link (about 16 times), each against the hosted database
    const w = watch(page);
    await open(page);
    await unfoldMachine(page);
    const internal = [...new Set((await hrefs(page)).filter((h) => h.startsWith("/")))];
    expect(internal.length).toBeGreaterThan(5);
    for (const link of internal) {
      await open(page);
      await page.locator(`main a[href="${link}"]`).first().click();
      await expectInAppRoute(page, link);
    }
    for (const [name, to] of [
      ["Find New Candidates", "/deal-flow?find=1"],
      ["Open Deal Flow", "/deal-flow"],
      ["Open Conviction", "/conviction"],
    ] as const) {
      await open(page);
      await unfoldMachine(page);
      await page.getByRole("button", { name }).click();
      await expectInAppRoute(page, to);
    }
    w.expectClean();
  });

  test("the weekly drawer opens from the desk (never generated here)", async ({ page }) => {
    const w = watch(page);
    await open(page);
    await unfoldMachine(page);
    await page.getByRole("button", { name: "Compose weekly update" }).click();
    const dlg = page.getByRole("dialog", { name: "Weekly Sourcing Update" });
    await expect(dlg).toBeVisible();
    await expect(dlg.getByRole("button", { name: "Generate" })).toBeVisible();
    await dlg.getByRole("button", { name: "Close" }).click();
    await expect(dlg).toHaveCount(0);
    w.expectClean();
  });

  test("the Agent Review Queue is deferred: the visible note describes it; a click and an Enter stay on / with no request; no review link", async ({ page }) => {
    const w = watch(page);
    const requested: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/")) requested.push(`${r.method()} ${new URL(r.url()).pathname}`);
    });
    await open(page);
    await unfoldMachine(page);
    const btn = page.getByRole("group", { name: "Next actions" }).getByRole("button", { name: "Open Agent Review Queue" });
    const note = page.getByTestId("desk-review-note");
    await expect(note).toBeVisible();
    await expect(note).toHaveText(NOTE);
    await expect(btn).toHaveAttribute("aria-disabled", "true");
    await expect(btn).toHaveAttribute("data-deferred", "");
    expect(await btn.getAttribute("aria-describedby")).toBe(await note.getAttribute("id"));
    await expect(btn).toHaveAccessibleDescription(NOTE);
    await page.waitForLoadState("networkidle");
    const before = requested.length;
    await btn.click({ force: true }); // aria-disabled: Playwright would wait for it to be enabled
    await btn.focus();
    await page.keyboard.press("Enter");
    await page.waitForTimeout(500);
    await expect(page).toHaveURL((u) => u.pathname === "/" && u.search === "");
    expect(requested.slice(before)).toEqual([]);
    const all = await hrefs(page);
    expect(all.filter((h) => h.includes("review=") || h.includes("filter=review"))).toEqual([]);
    w.expectClean();
  });

  for (const [name, size] of [
    ["1366", { width: 1366, height: 768 }],
    ["1920", { width: 1920, height: 1080 }],
    ["390 (phone)", { width: 390, height: 844 }],
  ] as const) {
    test(`no horizontal overflow at ${name}`, async ({ page }) => {
      await page.setViewportSize(size);
      await open(page);
      await expectNoHorizontalOverflow(page);
      await unfoldMachine(page);
      await expectNoHorizontalOverflow(page);
    });
  }

  test("no horizontal overflow at 150 % zoom", async ({ page }) => {
    await zoom150(page);
    await open(page);
    await expectNoHorizontalOverflow(page);
    await unfoldMachine(page);
    await expectNoHorizontalOverflow(page);
  });
});
