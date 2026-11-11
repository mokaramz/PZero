import { expect, type Locator, type Page, type Request } from "@playwright/test";

/**
 * Endpoints of views that are not ported yet. The shell asks for them, gets a 404 and quietly shows nothing; the
 * browser logs each 404 as a console error, which is the only console error allowed.
 */
const NOT_PORTED = [/\/api\/activity\b/, /\/api\/catchup\b/, /\/api\/pipeline\b/, /\/api\/people\b/, /\/api\/events\b/];

/** Page errors and console errors (none allowed), and every 404 of a Deal Flow endpoint (none allowed). */
export function watch(page: Page) {
  const errors: string[] = [];
  const notPorted404: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("response", (r) => {
    if (r.status() !== 404) return;
    if (NOT_PORTED.some((rx) => rx.test(r.url()))) notPorted404.push(r.url());
    else errors.push(`404: ${new URL(r.url()).pathname}`);
  });
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    if (/Failed to load resource: the server responded with a status of 404/.test(m.text())) return; // counted above
    errors.push(`console: ${m.text()}`);
  });
  return { expectClean: () => expect(errors, errors.join(" | ")).toEqual([]) };
}

export type Posted = { path: string; body: unknown };

const body = (r: Request) => {
  try {
    return r.postDataJSON();
  } catch {
    return null;
  }
};

/** Record every POST to /api/* (without altering it). */
export function recordPosts(page: Page): Posted[] {
  const posted: Posted[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/api/")) posted.push({ path: new URL(r.url()).pathname, body: body(r) });
  });
  return posted;
}

export const rows = (page: Page) => page.getByTestId("cand-row");

const chipLocator = (page: Page, name: string) => page.locator("[data-filter]", { hasText: new RegExp(`^${name}$`) });
/** a filter chip — the everyday four are visible; pipeline / machine filters open "More filters" first */
export const filterChip = (page: Page, name: string) => ({
  click: async () => {
    if (!(await chipLocator(page, name).isVisible())) await page.getByTestId("more-filters").click();
    await chipLocator(page, name).click();
  },
});

/** the Investment Manager lens lives under "More filters" */
export async function imLens(page: Page) {
  const b = page.getByRole("button", { name: "INVESTMENT MANAGER" });
  if (!(await b.isVisible())) await page.getByTestId("more-filters").click();
  await b.click();
}

/** Open a collapsed evidence / audit level (a <details> with this test id), as Mohamed would. */
export async function expand(scope: Page | Locator, testId: string) {
  const d = scope.getByTestId(testId).first();
  if (!(await d.evaluate((n) => (n as HTMLDetailsElement).open))) await d.locator("summary").first().click();
}

/** No horizontal page scroll. */
export async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "horizontal overflow in px").toBeLessThanOrEqual(1);
}

/** 150% browser zoom on a 1366x768 screen. */
export async function zoom150(page: Page) {
  await page.setViewportSize({ width: Math.round(1366 / 1.5), height: Math.round(768 / 1.5) });
}

/** Load Deal Flow and wait until the inbox (≈3 MB) has arrived and the queue is drawn. */
export async function openDealFlow(page: Page, url = "/deal-flow") {
  await page.goto(url);
  await expect(rows(page).first()).toBeVisible({ timeout: 60_000 });
}
