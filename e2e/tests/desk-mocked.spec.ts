/**
 * Investment Desk (review 031a) — the old `desk.spec.ts`, the desk containers of `redesign.spec.ts`, the flow trace of
 * `motion.spec.ts` and the desk deep links of `deal-flow.spec.ts`, ported to the new paths. The API is MOCKED with route
 * interception, so no backend is needed: only the frontend (`npm run dev` in frontend/, or PZ_BASE_URL). Every company,
 * person, event, source and URL in fixtures/desk/ is invented; the clock is fixed (Friday 13 November 2026, 09:30) so
 * the flow's 14-day window and the greeting are the same on every run.
 *
 * New here (revision 2): the Agent Review Queue control is deferred — its visible note sits right below the controls,
 * the control names it in `aria-describedby`, and a click or Enter stays on `/` with no request; the desk builds no
 * review link. Also: every link and button lands on a ported route, the weekly drawer opens and generates, and no
 * horizontal overflow at 1366, 1920, 390 and 150 %. The old frozen-file hash guards are not ported (decision g).
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test desk-mocked
 */
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures", "desk");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (n: string): J => JSON.parse(readFileSync(resolve(FIX, n), "utf8"));

const NAVY = "rgb(31, 43, 61)";
const GREETING = "Good morning, Smooth Operator.";
const NOTE = "The Agent Review Queue arrives with the analysis port";
const WEEKLY_TEXT = "Weekly Sourcing Update — invented week (nothing cleared the bar)";

/** Mock the five reads (`home`, `deal-flow/inbox`, `conviction/pipeline`, `today`, `sources`) and the weekly drawer's
 *  POST; anything else under /api answers 404 (the shell's not-ported reads are allowed by `watch`, any other 404 fails
 *  the test). Returns every API request, in order. */
async function mockApi(page: Page, opts: { home?: J } = {}) {
  const requested: Array<{ method: string; path: string }> = [];
  page.on("request", (r) => {
    if (!r.url().includes("/api/")) return;
    const u = new URL(r.url());
    requested.push({ method: r.method(), path: u.pathname + u.search });
  });
  await page.clock.setFixedTime(new Date(2026, 10, 13, 9, 30));
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/home(\?.*)?$/, (route) => route.fulfill({ json: opts.home ?? load("home.json") }));
  await page.route(/\/api\/deal-flow\/inbox(\?.*)?$/, (route) => route.fulfill({ json: load("inbox.json") }));
  await page.route(/\/api\/conviction\/pipeline(\?.*)?$/, (route) => route.fulfill({ json: load("pipeline.json") }));
  await page.route(/\/api\/today(\?.*)?$/, (route) => route.fulfill({ json: load("today.json") }));
  await page.route(/\/api\/sources(\?.*)?$/, (route) => route.fulfill({ json: load("sources.json") }));
  await page.route(/\/api\/conviction\/weekly$/, (route) => route.fulfill({ json: { text: WEEKLY_TEXT } }));
  return {
    requested,
    gets: () => requested.filter((r) => r.method === "GET").map((r) => r.path),
    writes: () => requested.filter((r) => r.method !== "GET"),
  };
}

async function open(page: Page) {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: GREETING })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("desk-job")).toHaveCount(5); // Today and Conviction have arrived
  await expect(page.getByTestId("desk-pulse")).toContainText("2 source health warnings", { useInnerText: false }); // and Sources
}

const machine = (page: Page) => page.getByTestId("desk-machine");
const unfoldMachine = async (page: Page) => {
  if (!(await machine(page).evaluate((d) => (d as HTMLDetailsElement).open))) await machine(page).locator("summary").click();
};
const reviewQueue = (page: Page) => page.getByRole("group", { name: "Next actions" }).getByRole("button", { name: "Open Agent Review Queue" });
const hrefs = (page: Page) => page.locator("main a[href]").evaluateAll((els) => els.map((e) => e.getAttribute("href") ?? ""));

/** a "box": its own surface with a border on all sides */
const isBox = (page: Page, sel: string) =>
  page
    .locator(sel)
    .first()
    .evaluate((el) => {
      const s = getComputedStyle(el);
      return s.backgroundColor !== "rgba(0, 0, 0, 0)" && parseFloat(s.borderTopWidth) > 0 && parseFloat(s.borderBottomWidth) > 0;
    });

/** Text / background / border in a strong red, yellow, mint or violet family (the old forbidden hues), visible only. */
const forbiddenHues = (page: Page) =>
  page.locator("main").evaluate((main) => {
    const hsl = (c: string) => {
      const m = c.match(/rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)/);
      if (!m || (m[4] !== undefined && Number(m[4]) < 0.15)) return null;
      const [r, g, b] = [Number(m[1]) / 255, Number(m[2]) / 255, Number(m[3]) / 255];
      const mx = Math.max(r, g, b);
      const mn = Math.min(r, g, b);
      const l = (mx + mn) / 2;
      const d = mx - mn;
      if (d < 0.02) return { h: 0, s: 0, l };
      const s = d / (1 - Math.abs(2 * l - 1));
      let h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
      h = (h * 60 + 360) % 360;
      return { h, s, l };
    };
    const family = (c: string) => {
      const x = hsl(c);
      if (!x || x.s < 0.35 || x.l < 0.18 || x.l > 0.96) return "";
      if (x.h < 15 || x.h >= 340) return "red";
      if (x.h >= 42 && x.h < 68) return "yellow";
      if (x.h >= 135 && x.h < 175 && x.l > 0.6) return "mint";
      if (x.h >= 245 && x.h < 340) return x.l > 0.7 ? "lavender" : "violet";
      return "";
    };
    const out: string[] = [];
    for (const el of Array.from(main.querySelectorAll("[data-testid=desk-flow] *"))) {
      if (!(el as HTMLElement).checkVisibility?.()) continue;
      const s = getComputedStyle(el);
      for (const c of [s.color, s.backgroundColor, s.borderTopColor, s.borderLeftColor]) {
        const f = family(c);
        if (f) out.push(`${el.tagName}.${el.getAttribute("class")}: ${f} ${c}`);
      }
    }
    return out.slice(0, 5);
  });

/** A route of the app that is ported: neither "Page not found." nor the not-ported placeholder, and not the desk. */
async function expectInAppRoute(page: Page, link: string) {
  const want = new URL(link, "http://x");
  // Deal Flow consumes its deep-link parameters (`?candidate=`, `?find=1`) once the inbox is there
  await expect(page).toHaveURL((u) => u.pathname === want.pathname && (u.search === want.search || want.pathname === "/deal-flow"), { timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1, name: GREETING })).toHaveCount(0);
  await expect(page.getByText("Page not found.")).toHaveCount(0);
  await expect(page.getByTestId("not-ported")).toHaveCount(0);
}

test.describe("Investment Desk — mocked API", () => {
  test("the desk orients: brief, tiles, missions, Manager, best opportunity, signals, event, activity, machine folded", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page);
    await expect(page.getByTestId("desk-context")).toHaveText("Friday, 13 Nov · 09:30");
    await expect(page.getByTestId("desk-summary")).toHaveText(
      "Deal flow is active: 7 missions need judgment, 4 Manager decisions are blocked and 2 founders hold the ball.",
    );
    const tiles = page.getByRole("list", { name: "Orientation" }).getByRole("listitem");
    await expect(tiles).toHaveCount(4);
    await expect(tiles).toHaveText(["7Priority missions", "4Manager decisions", "2Awaiting founder reply", "8Candidates to decide"]);
    for (const name of ["Priority missions", "Manager decisions", "Best opportunity", "Promising signals", "Upcoming event", "Recent activity"])
      await expect(page.getByRole("region", { name })).toBeVisible();
    await expect(page.getByTestId("desk-job")).toHaveCount(5);
    await expect(page.getByRole("region", { name: "Priority missions" }).getByRole("link", { name: /View remaining 2/ })).toBeVisible();
    await expect(page.getByRole("region", { name: "Manager decisions" }).getByRole("listitem")).toHaveCount(3);
    await expect(page.getByRole("region", { name: "Manager decisions" })).toContainText("Possible overlap with Fennwick Pay");
    await expect(page.getByTestId("desk-best")).toContainText("Your move: Ask Manager whether the plant pilots overlap the portfolio");
    await expect(page.getByTestId("desk-event")).toContainText("This weekend");
    await expect(page.getByTestId("desk-event")).toContainText("Register by 2026-11-13");
    await expect(page.getByTestId("desk-signals").getByRole("listitem")).toHaveCount(6);
    await expect(page.getByTestId("desk-activity").getByRole("listitem")).toHaveCount(4);
    // machine work is last and folded; its numbers and the old next actions are one click away
    expect(await machine(page).evaluate((d) => (d as HTMLDetailsElement).open)).toBe(false);
    await expect(machine(page).locator("summary")).toContainText("5 new in the last scan · 3 analyses · 2 source warnings");
    await machine(page).locator("summary").click();
    await expect(page.getByTestId("desk-pulse")).toContainText("source health warnings");
    await expect(page.getByRole("group", { name: "Next actions" })).toContainText("Open Agent Review Queue");
    await machine(page).locator("summary").click();
    expect(await machine(page).evaluate((d) => (d as HTMLDetailsElement).open)).toBe(false);
    // one filled primary on the desk (the best opportunity's move)
    const filled = await page
      .locator("main")
      .evaluate((m, navy) => Array.from(m.querySelectorAll("a, button")).filter((b) => (b as HTMLElement).checkVisibility() && getComputedStyle(b).backgroundColor === navy).length, NAVY);
    expect(filled).toBeLessThanOrEqual(1);
    // orientation, not a text wall
    const words = await page.locator("main").evaluate((m) => {
      let n = 0;
      const walker = document.createTreeWalker(m, NodeFilter.SHOW_TEXT);
      for (let t = walker.nextNode(); t; t = walker.nextNode()) {
        const p = t.parentElement;
        if (p && p.checkVisibility() && p.getBoundingClientRect().top < window.innerHeight) n += (t.textContent?.match(/\S+/g) ?? []).length;
      }
      return n;
    });
    expect(words, "desk visible words at 1440×900").toBeLessThanOrEqual(400);
    expect(await page.locator("main").evaluate((m) => (m.textContent?.match(/\bOmar\b|\bMohamed\b/g) ?? []).length), "role labels").toBe(0);
    // the five reads, the deferred review queue never among them, and nothing written
    for (const p of ["/api/home", "/api/deal-flow/inbox", "/api/conviction/pipeline", "/api/today", "/api/sources"]) expect(api.gets()).toContain(p);
    expect(api.gets().filter((p) => /review/.test(p))).toEqual([]);
    expect(api.writes()).toEqual([]);
    w.expectClean();
  });

  test("the approved composition: each concept in its own container, one navy anchor, five distinct header tints", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await open(page);
    for (const id of ["desk-missions", "desk-manager", "desk-best", "desk-signals", "desk-event", "desk-activity"])
      expect(await isBox(page, `[data-testid=${id}]`), `${id} is a contained card`).toBe(true);
    expect(await isBox(page, "[data-testid=desk-job]"), "a mission row is not its own card").toBe(false);
    const [canvas, card] = await page.evaluate(() => [
      getComputedStyle(document.body).backgroundColor,
      getComputedStyle(document.querySelector("[data-testid=desk-missions]")!).backgroundColor,
    ]);
    expect(card).not.toBe(canvas);
    expect(await page.getByTestId("desk-best").evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(NAVY);
    const heads: string[] = [];
    for (const id of ["desk-missions", "desk-manager", "desk-signals", "desk-event", "desk-activity"]) {
      const [body, head] = await page.getByTestId(id).evaluate((el) => [getComputedStyle(el).backgroundColor, getComputedStyle(el.firstElementChild as HTMLElement).backgroundColor]);
      expect(body, `${id} body is not navy`).not.toBe(NAVY);
      expect(head, `${id} header is tinted`).not.toBe(body);
      heads.push(head);
    }
    expect(new Set(heads).size, "each concept has its own tint").toBe(5);
    await expect(page.locator("main [data-testid=desk-best] a").filter({ hasText: "Open the case" })).toHaveCount(1);
    w.expectClean();
  });

  test("Signal → Decision: the hero's one graphic is the real four-stage flow; the path draws once and stops", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page);
    const hero = page.getByRole("region", { name: "Executive brief" });
    await expect(hero.locator("[data-signature]")).toHaveCount(1);
    const f = hero.getByTestId("desk-flow");
    await expect(f.locator("figcaption")).toHaveText("Today's operating flow · signals to decisions");
    await expect(f.locator("li span")).toHaveText(["Signals", "Review", "Manager", "Decision"]);
    await expect(f.getByRole("img")).toHaveAttribute(
      "aria-label",
      "Today's operating flow: Signals 8 (new · 14 days) → Review 7 (need you) → Manager 4 (blocked) → Decision 10 (in Conviction)",
    );
    // the counts are the desk's own: Review = Priority missions tile, Manager = Manager decisions tile
    const tiles = page.getByRole("list", { name: "Orientation" }).getByRole("listitem");
    const nums = (await f.locator("li b").allTextContents()).map(Number);
    expect(String(nums[1])).toBe((await tiles.nth(0).locator("[class*=tileN]").textContent())?.trim());
    expect(String(nums[2])).toBe((await tiles.nth(1).locator("[class*=tileN]").textContent())?.trim());
    expect(await forbiddenHues(page)).toEqual([]);
    expect(await f.locator('[data-stage="decision"] circle').first().evaluate((el) => getComputedStyle(el).fill)).toBe(NAVY);
    // motion.spec: the trace runs once, briefly, and ends drawn
    const line = f.locator("path.pz-trace");
    const t = await line.evaluate((el) => ({ dur: parseFloat(getComputedStyle(el).animationDuration), it: getComputedStyle(el).animationIterationCount }));
    expect(t.it).toBe("1");
    expect(t.dur).toBeGreaterThan(0.3);
    expect(t.dur).toBeLessThanOrEqual(0.7);
    await expect.poll(() => line.evaluate((el) => Number(getComputedStyle(el).strokeDashoffset.replace("px", ""))), { timeout: 3000 }).toBe(0);
    await page.waitForTimeout(1200);
    expect(await f.evaluate((el) => el.getAnimations({ subtree: true }).filter((a) => a.playState === "running").length)).toBe(0);
    w.expectClean();
  });

  test("reduced motion: the final state at once, status still in text, no overflow on a phone", async ({ page }) => {
    await mockApi(page);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page);
    const f = page.getByTestId("desk-flow");
    await expect(f).toBeVisible();
    for (const el of await f.locator("[data-stage]").all()) expect(Number(await el.evaluate((x) => getComputedStyle(x).opacity))).toBe(1);
    const line = f.locator("path.pz-trace");
    expect(parseFloat(await line.evaluate((el) => getComputedStyle(el).animationDuration))).toBeLessThanOrEqual(0.001);
    await expect.poll(() => line.evaluate((el) => Number(getComputedStyle(el).strokeDashoffset.replace("px", "")))).toBe(0);
    await expect(page.getByRole("region", { name: "Manager decisions" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  test("every in-app link on the desk lands on a ported route — nothing is posted", async ({ page }) => {
    // the target pages' own reads are mostly not mocked (they answer 404): only the navigation is checked
    const api = await mockApi(page);
    await open(page);
    await unfoldMachine(page);
    const all = await hrefs(page);
    const internal = [...new Set(all.filter((h) => h.startsWith("/")))];
    expect(internal.sort()).toEqual(
      [
        "/conviction",
        "/conviction?company=brightwell-analytics",
        "/conviction?company=corvane-systems",
        "/conviction?company=halvorsen-robotics",
        "/conviction?company=lumora-health",
        "/conviction?company=nordvik-materials",
        "/conviction?company=tessaro-grid",
        "/conviction?seg=gated",
        "/deal-flow",
        "/deal-flow?filter=triage&route=NEEDS_MOHAMED",
        "/events",
        "/founder-calls",
        "/today",
      ].sort(),
    );
    expect(all.filter((h) => !h.startsWith("/"))).toEqual(["https://example.org/alpine-deep-tech-summit"]); // Details ↗, a new tab
    for (const link of internal) {
      await open(page);
      await page.locator(`main a[href="${link}"]`).first().click();
      await expectInAppRoute(page, link);
    }
    expect(api.writes()).toEqual([]);
  });

  test("every navigation button lands on a ported route; Find only focuses the deferred Find control — nothing is posted", async ({ page }) => {
    const api = await mockApi(page);
    const buttons: Array<[string, (p: Page) => ReturnType<Page["getByRole"]>, string]> = [
      ["best name", (p) => p.getByTestId("desk-best").getByRole("button", { name: "Halvorsen Robotics" }), "/conviction?company=halvorsen-robotics"],
      ["signal row", (p) => p.getByTestId("desk-signals").getByRole("button").first(), "/deal-flow?candidate=c-0101"],
      ["activity item", (p) => p.getByTestId("desk-activity").getByRole("button").first(), "/deal-flow?candidate=c-0103"],
      ["Manager activity", (p) => p.getByTestId("desk-activity").getByRole("button").nth(3), "/conviction"],
      ["Find New Candidates", (p) => p.getByRole("button", { name: "Find New Candidates" }), "/deal-flow?find=1"],
      ["Open Deal Flow", (p) => p.getByRole("button", { name: "Open Deal Flow" }), "/deal-flow"],
      ["Open Conviction", (p) => p.getByRole("button", { name: "Open Conviction" }), "/conviction"],
    ];
    for (const [name, button, to] of buttons) {
      await open(page);
      await unfoldMachine(page);
      await button(page).click();
      await expectInAppRoute(page, to);
      if (name === "Find New Candidates") {
        // the old deal-flow deep link: ?find=1 focuses the Find control and never starts a scan
        await expect(page.getByTestId("find-btn")).toBeFocused({ timeout: 30_000 });
        await expect(page.getByTestId("find-btn")).toHaveAttribute("aria-disabled", "true");
      }
    }
    expect(api.writes()).toEqual([]);
  });

  test("Compose weekly update opens the weekly drawer, which generates the update", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    await unfoldMachine(page);
    await page.getByRole("button", { name: "Compose weekly update" }).click();
    const dlg = page.getByRole("dialog", { name: "Weekly Sourcing Update" });
    await expect(dlg).toBeVisible();
    await dlg.getByRole("button", { name: "Generate" }).click();
    await expect(dlg.getByTestId("weekly-text")).toHaveText(WEEKLY_TEXT);
    expect(api.writes().map((r) => `${r.method} ${r.path}`)).toEqual(["POST /api/conviction/weekly"]);
    await dlg.getByRole("button", { name: "Close" }).click();
    await expect(dlg).toHaveCount(0);
    w.expectClean();
  });

  test("the Agent Review Queue is deferred: its note is visible below the controls; a click and an Enter stay on / with no request", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    await unfoldMachine(page);
    const btn = reviewQueue(page);
    const note = page.getByTestId("desk-review-note");
    await expect(btn).toBeVisible();
    await expect(note).toBeVisible();
    await expect(note).toHaveText(NOTE);
    // its place among the five, its label, its state, and the visible note as its description
    await expect(page.getByRole("group", { name: "Next actions" }).getByRole("button")).toHaveText([
      "Find New Candidates",
      "Open Deal Flow",
      "Open Agent Review Queue",
      "Open Conviction",
      "Compose weekly update",
    ]);
    await expect(btn).toHaveAttribute("aria-disabled", "true");
    await expect(btn).toHaveAttribute("data-deferred", "");
    expect(await btn.getAttribute("aria-describedby")).toBe(await note.getAttribute("id"));
    await expect(btn).toHaveAccessibleDescription(NOTE);
    // right below the controls
    const [b, n] = [await page.getByRole("group", { name: "Next actions" }).boundingBox(), await note.boundingBox()];
    expect(n!.y).toBeGreaterThanOrEqual(b!.y + b!.height - 1);
    expect(n!.y - (b!.y + b!.height)).toBeLessThan(40);
    const before = api.requested.length;
    await btn.click({ force: true }); // aria-disabled: Playwright would wait for it to be enabled
    await page.waitForTimeout(400);
    await expect(page).toHaveURL((u) => u.pathname === "/" && u.search === "");
    await btn.focus();
    await page.keyboard.press("Enter");
    await page.keyboard.press("Space");
    await page.waitForTimeout(400);
    await expect(page).toHaveURL((u) => u.pathname === "/" && u.search === "");
    await expect(page.getByRole("heading", { level: 1, name: GREETING })).toBeVisible();
    expect(api.requested.slice(before)).toEqual([]);
    w.expectClean();
  });

  test("the desk builds no review link — on any of the three home payloads", async ({ page }) => {
    for (const file of ["home.json", "home_variants.json", "home_quiet.json"]) {
      await mockApi(page, { home: load(file) });
      await page.goto("/");
      await expect(page.getByRole("heading", { level: 1, name: GREETING })).toBeVisible({ timeout: 60_000 });
      await expect(page.getByTestId("desk-pulse")).toContainText("2 source health warnings", { useInnerText: false });
      await unfoldMachine(page);
      const all = await hrefs(page);
      expect(all.length).toBeGreaterThan(5);
      expect(all.filter((h) => h.includes("review=") || h.includes("filter=review")), file).toEqual([]);
      await page.unrouteAll({ behavior: "ignoreErrors" });
    }
  });

  test("the other branches: a provisional best opportunity, an undated event; then a quiet desk", async ({ page }) => {
    const w = watch(page);
    await mockApi(page, { home: load("home_variants.json") });
    await open(page);
    const best = page.getByTestId("desk-best");
    await expect(best).toContainText("Provisional");
    await expect(best).toContainText("Provisional 66 → Radar high-confidence if verified ≥ 65");
    await expect(best).not.toContainText("Your move");
    const ev = page.getByTestId("desk-event");
    await expect(ev.getByRole("heading", { level: 2 })).toHaveText("Upcoming event");
    await expect(ev).toContainText("Copper Valley Founders Night");
    await expect(ev.getByRole("link", { name: /Details/ })).toHaveCount(0);
    w.expectClean();
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await mockApi(page, { home: load("home_quiet.json") });
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1, name: GREETING })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("desk-best")).toContainText("No clear leader yet");
    await expect(page.getByTestId("desk-event")).toContainText("No dated upcoming event — scan sources in Events.");
  });

  for (const [name, size] of [
    ["1366", { width: 1366, height: 768 }],
    ["1920", { width: 1920, height: 1080 }],
    ["390 (phone)", { width: 390, height: 844 }],
  ] as const) {
    test(`no horizontal overflow at ${name}`, async ({ page }) => {
      await mockApi(page);
      await page.setViewportSize(size);
      await open(page);
      await expectNoHorizontalOverflow(page);
      await unfoldMachine(page);
      await expect(page.getByTestId("desk-review-note")).toBeVisible();
      await expectNoHorizontalOverflow(page);
    });
  }

  test("no horizontal overflow at 150 % zoom", async ({ page }) => {
    await mockApi(page);
    await zoom150(page);
    await open(page);
    await expectNoHorizontalOverflow(page);
    await unfoldMachine(page);
    await expectNoHorizontalOverflow(page);
  });
});
