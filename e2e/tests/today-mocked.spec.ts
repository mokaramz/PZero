/**
 * Today (review 030a) — the old `today-brief.spec.ts` and `today-ux.spec.ts`, plus the Today checks of the old
 * `a-class-ui.spec.ts` (the mission board, role labels), `compression.spec.ts` (the triage intelligence, Review → the
 * compressed list) and `cases.spec.ts` (the exceptions line), ported to the new paths. The API is MOCKED with route
 * interception, so no backend is needed: only the frontend (`npm run dev` in frontend/, or PZ_BASE_URL). Every company,
 * person, event and URL in fixtures/today/ is invented.
 *
 * New here: the snapshot note (decision f) present and absent, the footer listing only the sections sent (decision c),
 * every Open link landing on its route, the triage buttons as links, nothing posted (decision j), and no horizontal
 * overflow at 1366, 1920, 150 % and phone width. The old "Today is frozen" / "the Desk is frozen" hash guards pinned the
 * old repo's source files and are not ported.
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test today-mocked
 */
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures", "today");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (n: string): J => JSON.parse(readFileSync(resolve(FIX, n), "utf8"));

const NAVY = "rgb(31, 43, 61)";
const NOTE = "Triage routes and prepared cases are the imported snapshot until their runs are ported";
const RULES = "Deterministic ranking over existing state; nothing is sent, registered, scored or forwarded.";

/** Mock the two reads (`today` and Conviction's pipeline); anything else under /api answers 404 (the shell's not-ported
 *  reads are allowed by `watch`, any other 404 fails the test). Returns every API request, in order. */
async function mockApi(page: Page, opts: { today?: J } = {}) {
  const day = opts.today ?? load("today.json");
  const requested: Array<{ method: string; path: string }> = [];
  page.on("request", (r) => {
    if (!r.url().includes("/api/")) return;
    const u = new URL(r.url());
    requested.push({ method: r.method(), path: u.pathname + u.search });
  });
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/today(\?.*)?$/, (route) => route.fulfill({ json: day }));
  await page.route(/\/api\/conviction\/pipeline(\?.*)?$/, (route) => route.fulfill({ json: load("pipeline.json") }));
  return {
    requested,
    writes: () => requested.filter((r) => r.method !== "GET"),
  };
}

async function open(page: Page) {
  await page.goto("/today");
  await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("list", { name: "Orientation" })).toBeVisible();
}

const missions = (page: Page) => page.getByTestId("today-list").getByTestId("today-action");
const machine = (page: Page) => page.getByTestId("today-triage");
const unfoldMachine = (page: Page) => machine(page).locator("summary").first().click();

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
    for (const el of Array.from(main.querySelectorAll("*"))) {
      if (!(el as HTMLElement).checkVisibility?.()) continue;
      const s = getComputedStyle(el);
      for (const c of [s.color, s.backgroundColor, s.borderTopColor, s.borderLeftColor]) {
        const f = family(c);
        if (f) out.push(`${el.tagName}.${el.getAttribute("class")}: ${f} ${c}`);
      }
    }
    return out.slice(0, 5);
  });

/** Visible links / buttons filled with navy. */
const filledNavy = (page: Page) =>
  page
    .locator("main")
    .evaluate(
      (m, navy) => Array.from(m.querySelectorAll("a, button")).filter((b) => (b as HTMLElement).checkVisibility() && getComputedStyle(b).backgroundColor === navy).length,
      NAVY,
    );

test.describe("Today — mocked API", () => {
  test("hero: the date above Today, the purpose line and Today's own flow graphic from the real counts", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await open(page);
    await expect(page.getByTestId("today-date")).toHaveText(/^\w+day, \d{1,2} \w+ · \d{2}:\d{2}$/);
    await expect(page.getByText("Your daily brief for sourcing, investigation and decisions.")).toBeVisible();
    await expect(page.locator("main [data-signature]")).toHaveCount(1); // exactly one signature graphic, in the hero
    const flow = page.getByTestId("today-flow");
    await expect(flow).toBeVisible();
    const n = async (step: string) => parseInt((await flow.locator(`text[data-step="${step}"]`).textContent()) ?? "", 10);
    expect(await n("signals")).toBe(487);
    expect(await n("missions")).toBe(await missions(page).count());
    expect(await n("decisions")).toBe(await page.getByTestId("today-context").getByTestId("today-action").count());
    await expect(flow.getByRole("img")).toHaveAttribute("aria-label", "Today's flow: 487 signals handled by the machine → 5 missions for review → 2 decisions due");
    // revealed once, then still
    await page.waitForTimeout(900);
    expect(await flow.evaluate((el) => el.getAnimations({ subtree: true }).filter((a) => a.playState === "running").length)).toBe(0);
    w.expectClean();
  });

  test("the mission board: briefing, structured missions, one featured with the one navy action, Manager decisions and events", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await open(page);
    const brief = page.getByTestId("today-brief");
    await expect(brief).toContainText("Today's briefing");
    await expect(brief).toContainText("5 priority missions · 1 Manager decision due · 1 event decision");
    await expect(brief).toContainText("Halvorsen Robotics — Two plant pilots converted to paid contracts");
    await expect(page.getByRole("heading", { level: 2, name: "Missions" })).toBeVisible();
    await expect(missions(page)).toHaveCount(5);
    expect(await missions(page).evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.type))).toEqual([
      "CONTACT_FOUNDER",
      "PREPARE_FOUNDER_CALL",
      "CASE_READY",
      "REVIEW_VERIFICATION",
      "TRIAGE_REVIEW",
    ]);
    // rows live inside one container: no row is its own floating card
    for (const r of await missions(page).locator("article").all()) {
      expect(parseFloat(await r.evaluate((el) => getComputedStyle(el).borderTopWidth))).toBe(0);
    }
    const featured = missions(page).first().locator("article");
    await expect(featured).toHaveAttribute("data-featured", "true");
    expect(await featured.evaluate((el) => getComputedStyle(el).boxShadow)).toContain(NAVY);
    for (const label of ["Why now", "Biggest unknown", "State", "Next move"]) await expect(featured).toContainText(label);
    expect(await filledNavy(page), "one filled navy action on Today").toBe(1);
    // the segmented control marks its selection in navy without becoming a second filled action
    const on = page.getByRole("group", { name: "Mission filter" }).locator('[aria-pressed="true"]');
    expect(await on.evaluate((el) => getComputedStyle(el).borderTopColor)).toBe(NAVY);
    expect(await on.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe(NAVY);
    // Manager decisions and Events: side by side under the missions, visible, never tabbed, tinted headers
    const mgr = page.getByRole("region", { name: "Manager decisions" });
    await expect(mgr).toContainText("1 blocked until the Manager answers");
    await expect(mgr).toContainText("3 possible portfolio conflict(s)");
    await expect(mgr).toContainText("Decision due");
    for (const o of await mgr.getByRole("link", { name: /^Open/ }).all()) expect(await o.evaluate((el) => getComputedStyle(el).borderTopColor)).toBe(NAVY);
    await expect(page.getByRole("region", { name: "Events" })).toContainText("Alpine Deep Tech Summit");
    const heads: string[] = [];
    for (const r of await page.getByTestId("today-context").locator(":scope > section").all()) {
      const [body, head] = await r.evaluate((el) => [getComputedStyle(el).backgroundColor, getComputedStyle(el.firstElementChild as HTMLElement).backgroundColor]);
      expect(head, "the panel header carries its tone").not.toBe(body);
      heads.push(head);
    }
    expect(new Set(heads).size).toBe(2);
    // role labels, never personal names; details and machine work folded
    expect(await page.locator("main").evaluate((m) => (m.textContent?.match(/\b(Omar|Mohamed)\b/g) ?? []).length)).toBe(0);
    expect(await machine(page).evaluate((d) => (d as HTMLDetailsElement).open)).toBe(false);
    for (const d of await page.locator("[data-testid=today-action] details").all()) expect(await d.evaluate((x) => (x as HTMLDetailsElement).open)).toBe(false);
    w.expectClean();
  });

  test("the filter: Companies and Signals narrow the missions; All brings the featured row back", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await open(page);
    const seg = page.getByRole("group", { name: "Mission filter" });
    await seg.getByRole("button", { name: /^Signals/ }).click();
    await expect(missions(page)).toHaveCount(1);
    await expect(missions(page).first()).toHaveAttribute("data-type", "TRIAGE_REVIEW");
    await seg.getByRole("button", { name: /^Companies/ }).click();
    await expect(missions(page)).toHaveCount(4);
    await seg.getByRole("button", { name: /^All/ }).click();
    await expect(missions(page).first().locator("article")).toHaveAttribute("data-featured", "true");
    w.expectClean();
  });

  test("calm mission cards: neutral paper, no forbidden hue, no motion after load, ≤ 200 words on the first screen", async ({ page }) => {
    const w = watch(page);
    // the old today-ux day: one prepared case, one Manager decision, one event
    const day = load("today.json");
    day.actions = day.actions.filter((a: { type: string }) => ["CASE_READY", "ASK_OMAR_CONFLICT", "EVENT_ACTION"].includes(a.type));
    day.more = 0;
    await mockApi(page, { today: day });
    await open(page);
    const [bg, canvas] = await missions(page)
      .first()
      .locator("article")
      .evaluate((el) => {
        let p: HTMLElement | null = el.parentElement;
        while (p && getComputedStyle(p).backgroundColor === "rgba(0, 0, 0, 0)") p = p.parentElement;
        return [getComputedStyle(p ?? el).backgroundColor, getComputedStyle(document.body).backgroundColor];
      });
    const rgb = (c: string) => (c.match(/\d+/g) ?? []).slice(0, 3).map(Number);
    const [r, g, b] = rgb(bg);
    expect(bg).not.toBe(canvas);
    expect(Math.max(r, g, b) - Math.min(r, g, b)).toBeLessThanOrEqual(8); // neutral: no tint
    expect(Math.min(r, g, b)).toBeGreaterThan(235);
    expect(await forbiddenHues(page)).toEqual([]);
    await page.waitForTimeout(900);
    const running = await page.evaluate(
      () => document.getAnimations().filter((a) => a.playState === "running" && (a.effect?.getComputedTiming().iterations ?? 1) === Infinity).length,
    );
    expect(running).toBe(0);
    const words = await page.locator("main").evaluate((main) => {
      let n = 0;
      const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
      for (let t = walker.nextNode(); t; t = walker.nextNode()) {
        const p = t.parentElement;
        if (p && p.checkVisibility({ contentVisibilityAuto: true }) && p.getBoundingClientRect().top < window.innerHeight) n += (t.textContent?.match(/\S+/g) ?? []).length;
      }
      return n;
    });
    expect(words).toBeLessThanOrEqual(200);
    w.expectClean();
  });

  test("reduced motion shows the final state at once", async ({ page }) => {
    await mockApi(page);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await open(page);
    for (const s of await page.getByTestId("today-flow").locator("g[data-step], circle").all()) expect(Number(await s.evaluate((el) => getComputedStyle(el).opacity))).toBe(1);
  });

  test("the machine work: the triage intelligence, the exceptions, the snapshot note and the footer; Review goes to the compressed list", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    await expect(page.getByTestId("today-triage").locator("summary")).toContainText("487 handled · 129 researching · 331 watching");
    await unfoldMachine(page);
    const t = machine(page);
    await expect(t).toContainText("487 machine proposals handled");
    await expect(page.getByTestId("triage-needs")).toContainText("14 need your judgment");
    await expect(t).toContainText("331 watched / deferred");
    await expect(t).toContainText("5 calibration samples");
    await expect(t).toContainText("4 more wait beyond today’s budget of 10");
    await expect(page.getByTestId("today-exceptions")).toHaveText(
      "1 company needs your judgment · 2 founder calls worth preparing · 5 possible portfolio conflicts for Manager · 2 events worth deciding on · 10 machine proposals need your judgment",
    );
    await expect(page.getByTestId("today-snapshot")).toHaveText(`${NOTE} (triage run 2026-11-12 23:05 · newest prepared case 2026-11-01 19:36).`);
    await expect(page.getByTestId("today-footer")).toHaveText(
      `3 lower-priority action(s) not shown. ${RULES} Sources considered: pipeline 4 · calls 1 · events 2 · triage 2 · watch 1 · cases 1.`,
    );
    await zoom150(page);
    await expectNoHorizontalOverflow(page);
    w.expectClean(); // before leaving: Deal Flow's own reads are not mocked here
    await page.getByTestId("triage-review").click();
    await expect(page).toHaveURL(/\/deal-flow\?filter=triage&route=NEEDS_MOHAMED$/);
    await page.goBack();
    await unfoldMachine(page);
    await page.getByTestId("triage-queue").click();
    await expect(page).toHaveURL(/\/deal-flow\?filter=triage$/);
    expect(api.writes()).toEqual([]);
  });

  test("the other branches: no triage run, a failed section, the old '… for Omars', no snapshot note", async ({ page }) => {
    const w = watch(page);
    await mockApi(page, { today: load("today_variants.json") });
    await open(page);
    await expect(page.getByTestId("today-action")).toHaveCount(7);
    await expect(page.getByRole("group", { name: "Mission filter" })).toHaveCount(0);
    await expect(machine(page).locator("summary")).toContainText("working");
    await unfoldMachine(page);
    await expect(page.getByTestId("triage-needs")).toHaveCount(0);
    await expect(page.getByTestId("triage-review")).toHaveCount(0);
    await expect(page.getByTestId("today-exceptions")).toContainText("1 possible portfolio conflict for Omars");
    await expect(page.getByTestId("today-snapshot")).toHaveCount(0);
    await expect(page.getByTestId("today-footer")).toHaveText(
      `${RULES} Sources considered: pipeline 1 · calls temporarily unavailable — the rest of Today is complete · events 1 · triage 1 · watch 2 · cases 2.`,
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });

  test("a quiet day: nothing needs you, the rest is handled, the note keeps the newest case's time", async ({ page }) => {
    const w = watch(page);
    await mockApi(page, { today: load("today_empty.json") });
    await open(page);
    await expect(page.getByTestId("today-empty")).toHaveText("Nothing needs you today.");
    await expect(page.getByTestId("today-context")).toHaveCount(0);
    await expect(page.getByTestId("today-brief")).toContainText("Nothing needs you today");
    await unfoldMachine(page);
    await expect(page.getByTestId("today-exceptions")).toHaveText("Project Zero is handling the rest.");
    await expect(page.getByTestId("today-snapshot")).toHaveText(`${NOTE} (newest prepared case 2026-11-01 19:36).`);
    w.expectClean();
  });

  test("every Open link lands on its in-app route — and nothing is posted", async ({ page }) => {
    // the target pages' own reads are not mocked here (they answer 404): only the navigation is checked
    const api = await mockApi(page);
    for (const file of ["today.json", "today_variants.json"]) {
      const day = load(file);
      await page.route(/\/api\/today(\?.*)?$/, (route) => route.fulfill({ json: day }));
      for (const a of day.actions as Array<{ link: string }>) {
        await open(page);
        const links = page.getByTestId("today-action").getByRole("link", { name: /^Open: / });
        const hrefs = await links.evaluateAll((els) => els.map((e) => e.getAttribute("href")));
        expect(hrefs).toContain(a.link);
        await links.nth(hrefs.indexOf(a.link)).click();
        const want = new URL(a.link, "http://x");
        await expect(page).toHaveURL((u) => u.pathname === want.pathname && u.search === want.search);
        await expect(page.getByRole("heading", { level: 1, name: "Today" })).toHaveCount(0);
        await expect(page.getByText("Page not found.")).toHaveCount(0);
        await expect(page.getByTestId("not-ported")).toHaveCount(0);
      }
    }
    expect(api.writes()).toEqual([]);
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
      for (const d of await page.locator("[data-testid=today-action] details summary").all()) await d.click();
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
