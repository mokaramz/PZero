/**
 * Today (review 030a) — the new app on a preview database (the real snapshot in a scratch schema). The page renders
 * from the two real reads (`GET /api/today`, `GET /api/conviction/pipeline`) and matches them: the missions, the
 * Manager decisions and events, the Machine details with the snapshot note (decision f) and the footer listing only the
 * sections the server considered (decision c). Every mission's Open link is a valid in-app route, the verification card
 * opens the company with its verification section on the Conviction page, and the layout fits at the usual sizes.
 * This spec only READS: Today has no write (decision j), and nothing here clicks a control of the pages it opens.
 * today-mocked.spec.ts covers every action type on invented payloads.
 */
import { expect, test, type Page } from "@playwright/test";

import { expand, expectNoHorizontalOverflow, watch as watchErrors, zoom150 } from "./helpers";

type Action = { type: string; title: string; link: string; subject: string };
type Day = {
  actions: Action[];
  more: number;
  considered: Record<string, number | string>;
  exceptions?: Array<{ key: string; n: number; text: string }>;
  triage?: { total: number } | null;
  rules: string;
  snapshot?: { note: string; triage_at: string | null; cases_prepared_at: string | null } | null;
};

const NOTE = "Triage routes and prepared cases are the imported snapshot until their runs are ported";

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

const day = async (page: Page): Promise<Day> => (await (await page.request.get("/api/today")).json()) as Day;

async function open(page: Page) {
  await page.goto("/today");
  await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("list", { name: "Orientation" })).toBeVisible({ timeout: 60_000 });
}

const machine = (page: Page) => page.getByTestId("today-triage");

/** A route of the app that is ported: neither "Page not found." nor the not-ported placeholder, and not Today. */
async function expectInAppRoute(page: Page, link: string) {
  const want = new URL(link, "http://x");
  await expect(page).toHaveURL((u) => u.pathname === want.pathname && u.search === want.search, { timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Page not found.")).toHaveCount(0);
  await expect(page.getByTestId("not-ported")).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1, name: "Today" })).toHaveCount(0);
}

test.describe("Today — new app, preview database", () => {
  test("the page renders the day the server computed; nothing is written", async ({ page }) => {
    const w = watch(page);
    const d = await day(page);
    expect(d.actions.length).toBeLessThanOrEqual(7);
    expect(Object.keys(d.considered)).toEqual(["pipeline", "calls", "events", "triage", "watch", "cases"]); // decision c
    expect((d.exceptions ?? []).map((x) => x.key)).not.toContain("jobs"); // decision d
    await open(page);
    await expect(page.getByTestId("today-date")).toHaveText(/^\w+day, \d{1,2} \w+ · \d{2}:\d{2}$/);
    await expect(page.getByTestId("today-action")).toHaveCount(d.actions.length);
    if (!d.actions.length) await expect(page.getByTestId("today-empty")).toHaveText("Nothing needs you today.");
    const flow = page.getByTestId("today-flow");
    const n = async (step: string) => parseInt((await flow.locator(`text[data-step="${step}"]`).textContent()) ?? "", 10);
    expect(await n("missions")).toBe(await page.getByTestId("today-list").getByTestId("today-action").count());
    if (d.triage) expect(await n("signals")).toBe(d.triage.total);
    else await expect(flow.locator('text[data-step="signals"]')).toHaveCount(0);
    expect(await machine(page).evaluate((el) => (el as HTMLDetailsElement).open)).toBe(false);
    await machine(page).locator("summary").first().click();
    await expect(page.getByTestId("today-exceptions")).toBeVisible();
    // the snapshot note, with the original run timestamps — or nothing when the server sends none
    if (d.snapshot?.note) await expect(page.getByTestId("today-snapshot")).toContainText(NOTE);
    else await expect(page.getByTestId("today-snapshot")).toHaveCount(0);
    if (d.snapshot?.triage_at) await expect(page.getByTestId("today-snapshot")).toContainText(`triage run ${d.snapshot.triage_at.slice(0, 16).replace("T", " ")}`);
    if (d.snapshot?.cases_prepared_at)
      await expect(page.getByTestId("today-snapshot")).toContainText(`newest prepared case ${d.snapshot.cases_prepared_at.slice(0, 16).replace("T", " ")}`);
    // the footer lists exactly the sections considered, in the server's order
    const considered = Object.entries(d.considered)
      .map(([k, v]) => `${k} ${v}`)
      .join(" · ");
    await expect(page.getByTestId("today-footer")).toHaveText(`${d.more ? `${d.more} lower-priority action(s) not shown. ` : ""}${d.rules} Sources considered: ${considered}.`);
    // role labels, never personal names
    expect(await page.locator("main").evaluate((m) => (m.textContent?.match(/\b(Omar|Mohamed)\b/g) ?? []).length)).toBe(0);
    w.expectClean();
  });

  test("every mission's Open link is a valid in-app route", async ({ page }) => {
    const w = watch(page);
    const d = await day(page);
    if (!d.actions.length) test.skip(true, "no mission in this data set");
    for (const a of d.actions) {
      await open(page);
      const links = page.getByTestId("today-action").getByRole("link", { name: /^Open: / });
      const hrefs = await links.evaluateAll((els) => els.map((e) => e.getAttribute("href")));
      expect(hrefs, `the ${a.type} card links where the server says`).toContain(a.link);
      await links.nth(hrefs.indexOf(a.link)).click();
      await expectInAppRoute(page, a.link);
    }
    w.expectClean();
  });

  test("the verification card opens the company with its verification section on the Conviction page", async ({ page }) => {
    const w = watch(page);
    const d = await day(page);
    let verify = d.actions.find((a) => a.type === "REVIEW_VERIFICATION");
    if (!verify) {
      // The real snapshot ranks no verification card in its first 7 (the research queue is empty on this data). The
      // card is then the server's own shape for a REAL company of the preview pipeline, served in place of
      // `/api/today` only: the Conviction page it opens is the real one, on the real data.
      const pipeline = (await (await page.request.get("/api/conviction/pipeline")).json()) as {
        signals: Array<{ company: string; slug: string; status?: string }>;
      };
      const s = pipeline.signals.find((x) => x.slug && x.status !== "dropped");
      expect(s, "a company in the preview pipeline").toBeTruthy();
      verify = {
        type: "REVIEW_VERIFICATION",
        title: `Verify ${s!.company} (founders, traction)`,
        link: `/conviction?company=${s!.slug}`,
        subject: s!.company,
      };
      const card = {
        ...verify,
        why: "Provisional 66 ≥ 65 — it enters Radar only once verified (frozen rule).",
        next_step: "Open Verification: accept or reject each proposal with its evidence; traction stays your judgment.",
        urgency: "medium",
        evidence: ["missing: founders, traction"],
        conflict: "none",
        contact_appropriate: false,
      };
      await page.route("**/api/today", (route) => route.fulfill({ json: { ...d, actions: [card, ...d.actions.slice(0, 6)] } }));
    }
    const a = verify;
    expect(a.title).toMatch(/^Verify .+ \(.+\)$/); // decision e: never "1-click verification ready" before the Claim Index
    const slug = new URL(a.link, "http://x").searchParams.get("company");
    expect(a.link).toBe(`/conviction?company=${slug}`);
    await open(page);
    const card = page.getByTestId("today-action").filter({ has: page.locator(`a[href="${a.link}"]`) }).first();
    await expect(card).toHaveAttribute("data-type", "REVIEW_VERIFICATION");
    await card.getByRole("link", { name: /^Open: / }).click();
    await expect(page).toHaveURL(new RegExp(`/conviction\\?company=${slug}$`));
    await expect(page.getByRole("heading", { level: 2, name: a.subject })).toBeVisible({ timeout: 60_000 });
    await expect(page.locator(`[data-slug="${slug}"]`)).toHaveAttribute("aria-current", "true");
    await expand(page, "sec-evidence");
    await expect(page.getByTestId("checklist")).toBeVisible();
    await expect(page.getByTestId("verification-proposals")).toBeVisible();
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
      await machine(page).locator("summary").first().click();
      await expectNoHorizontalOverflow(page);
    });
  }

  test("no horizontal overflow at 150 % zoom", async ({ page }) => {
    await zoom150(page);
    await open(page);
    await expectNoHorizontalOverflow(page);
    await machine(page).locator("summary").first().click();
    await expectNoHorizontalOverflow(page);
  });
});
