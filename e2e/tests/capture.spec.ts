/**
 * Old vs new Deal Flow, same data, side by side (review 009, Codex #2): 1366 and 1920 wide, light and dark, plus the
 * 150 % zoom view. Opt-in: PZ_OLD_URL (the old app on a scratch copy of its data) and PZ_CAPTURE_DIR (scratch folder —
 * real data, never the repository). The images are compared by eye and by the DOM signature below.
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, rows } from "./helpers";

const OLD = process.env.PZ_OLD_URL;
const NEW = process.env.PZ_BASE_URL ?? "http://localhost:5173";
const DIR = process.env.PZ_CAPTURE_DIR;

/** Counts of CSS-module local class names, test ids and roles inside <main> — layout structure without hashes. */
const signature = (page: Page) =>
  page.evaluate(() => {
    const out: Record<string, number> = {};
    const add = (k: string) => (out[k] = (out[k] || 0) + 1);
    for (const e of (document.querySelector("main") ?? document.body).querySelectorAll("*")) {
      for (const k of e.classList) add(`c:${/^_(.+?)_[a-z0-9]{5}_\d+$/.exec(k)?.[1] ?? k}`);
      if ((e as HTMLElement).dataset.testid) add(`t:${(e as HTMLElement).dataset.testid}`);
      if (e.getAttribute("role")) add(`r:${e.getAttribute("role")}`);
    }
    return out;
  });

test.describe.configure({ mode: "serial" });
test.skip(!OLD || !DIR, "set PZ_OLD_URL and PZ_CAPTURE_DIR");

const VIEWS = [
  { key: "deal-flow", path: "/deal-flow", ready: (p: Page) => rows(p).first(), detail: "cand-detail" },
  { key: "conviction", path: "/conviction?company=kyrok", ready: (p: Page) => p.locator("[data-slug=kyrok]"), detail: "operator-view" },
  { key: "network", path: "/network", ready: (p: Page) => p.getByTestId("person-row").first(), detail: "person-profile" },
  { key: "watchlist", path: "/watchlist", ready: (p: Page) => p.locator("main table, main [class*=empty]").first(), detail: "" },
  { key: "events", path: "/events", ready: (p: Page) => p.getByRole("button", { name: "source health" }), detail: "event-calendar" }, // health loads after the list
] as const;

for (const view of VIEWS)
for (const width of [1366, 1920])
  for (const theme of ["light", "dark"] as const)
    test(`capture ${view.key} ${width} ${theme}`, async ({ browser }) => {
      mkdirSync(DIR!, { recursive: true });
      const sigs: Record<string, Record<string, number>> = {};
      for (const [app, base] of [["old", OLD!], ["new", NEW]] as const) {
        const ctx = await browser.newContext({ viewport: { width, height: 1000 }, colorScheme: theme, reducedMotion: "reduce" });
        await ctx.addInitScript((t) => localStorage.setItem("pz.theme", t), theme);
        const page = await ctx.newPage();
        await page.goto(`${base}${view.path}`);
        await expect(view.ready(page)).toBeVisible({ timeout: 90_000 });
        if (view.detail) await expect(page.getByTestId(view.detail).first()).toBeVisible({ timeout: 30_000 });
        await page.waitForTimeout(1500);
        expect(await page.evaluate(() => document.documentElement.dataset.theme ?? "light")).toBe(theme === "dark" ? "dark" : "light");
        await expectNoHorizontalOverflow(page);
        await page.screenshot({ path: join(DIR!, `${view.key}-${app}-${width}-${theme}.png`) });
        sigs[app] = await signature(page);
        if (width === 1366 && theme === "light") {
          await page.setViewportSize({ width: Math.round(1366 / 1.5), height: Math.round(768 / 1.5) });
          await page.waitForTimeout(500);
          await expectNoHorizontalOverflow(page);
          await page.screenshot({ path: join(DIR!, `${view.key}-${app}-zoom150.png`) });
        }
        await ctx.close();
      }
      // report structural differences (the scan report and the disabled-reason elements are expected)
      const keys = [...new Set([...Object.keys(sigs.old), ...Object.keys(sigs.new)])].sort();
      const delta = keys.filter((k) => (sigs.old[k] ?? 0) !== (sigs.new[k] ?? 0)).map((k) => `${k}: ${sigs.old[k] ?? 0} -> ${sigs.new[k] ?? 0}`);
      console.log(`[${view.key} ${width} ${theme}] signature differences: ${delta.length ? delta.join(", ") : "none"}`);
    });
