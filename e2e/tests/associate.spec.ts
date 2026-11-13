/**
 * PZ Associate (review 033a) — the new app on a preview database (the real snapshot in a scratch schema). Paid calls
 * are off there (`PZ_AI_PAID` is not `on`), so the Associate is in its honest offline mode: it says the model is not
 * available and every answer comes from the PZ documentation. No provider call, no Project Zero record changed.
 *
 * The old `associate.spec.ts` checks are ported where they work offline: the identity, the Ardea illustration and the
 * offline banner; an ask that is cited and remembered, with the business data unchanged; the Conviction context and
 * the command-palette hand-over; drafts only after the confirmation; Ardea with reduced motion and in dark mode; no
 * overflow at 1366, 1920, 390 and 150 %. The unsaved-answer notice (revision 2) needs a conversation deleted while the
 * model runs, which an offline answer is too fast to race: associate-mocked.spec.ts covers it on invented payloads.
 *
 * Writes: the page may POST only to `associate/*` (its own store), and every other write request fails the test. The
 * conversations and drafts this spec creates are removed again at the end of each test, through the page.
 */
import { expect, test, type Page } from "@playwright/test";

import { expectNoHorizontalOverflow, watch as watchErrors, zoom150 } from "./helpers";

type Signal = { slug: string; status?: string };

/** No page / console error (the shell's not-yet-ported endpoints aside) and no write outside `associate/*`. */
function watch(page: Page) {
  const errors = watchErrors(page);
  const writes: string[] = [];
  page.on("request", (r) => {
    if (r.method() !== "GET" && r.url().includes("/api/")) writes.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  return {
    writes,
    expectClean: () => {
      errors.expectClean();
      const outside = writes.filter((w) => !/^POST \/api\/associate\//.test(w));
      expect(outside, outside.join(" | ")).toEqual([]);
    },
  };
}

/** The business data an ask must not change: the Conviction records, the people and the Deal Flow inbox. */
const fingerprint = async (page: Page) =>
  JSON.stringify(await Promise.all(["conviction/pipeline", "network/people", "deal-flow/inbox"].map(async (n) => (await page.request.get(`/api/${n}`)).text())));

async function open(page: Page, url = "/associate") {
  await page.goto(url);
  await expect(page.getByRole("heading", { level: 1, name: "PZ Associate" })).toBeVisible({ timeout: 60_000 });
}

const answers = (page: Page) => page.getByTestId("associate-answer");
const drawer = (page: Page) => page.getByRole("complementary", { name: "Conversations" });
const box = (page: Page) => page.getByRole("textbox", { name: "Ask PZ Associate" });

/** No Scout text in the page or an open dialog (the shell's brand line, "VC scouting", is outside both), no Scout link. */
async function expectNoScout(page: Page) {
  expect((await page.locator("main, [role=dialog]").allInnerTexts()).join(" ")).not.toMatch(/scout/i);
  expect(await page.locator("a[href*='scout' i]").count()).toBe(0);
}

/** Remove, through the drawer, every conversation this test created (their ids, from the URLs it saw). */
async function removeConversations(page: Page, ids: Set<string>) {
  for (const id of ids) {
    const del = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/associate/conversation_delete");
    await open(page, `/associate?c=${id}`);
    await expect(drawer(page).locator('[aria-current="true"]')).toBeVisible({ timeout: 30_000 });
    await drawer(page).locator("li", { has: page.locator('[aria-current="true"]') }).getByRole("button", { name: /^Remove conversation/ }).click();
    await del;
  }
}

/** Collect the conversation ids the page opens (`?c=`). */
function trackConversations(page: Page) {
  const ids = new Set<string>();
  page.on("framenavigated", (f) => {
    const c = new URL(f.url()).searchParams.get("c");
    if (f === page.mainFrame() && c) ids.add(c);
  });
  page.on("response", async (r) => {
    if (new URL(r.url()).pathname !== "/api/associate/ask" || !r.ok()) return;
    const id = ((await r.json().catch(() => null)) as { conversation?: { id?: string } } | null)?.conversation?.id;
    if (id) ids.add(id);
  });
  return ids;
}

test.describe("PZ Associate — preview database (offline)", () => {
  test("the identity, the Ardea illustration and the honest offline banner", async ({ page }) => {
    const w = watch(page);
    await open(page);
    await expect(page.getByRole("complementary", { name: "Main navigation" }).getByRole("link", { name: "PZ Associate" })).toBeVisible();
    await expect(page.getByRole("img", { name: "Ardea, the PZ Associate heron" })).toBeVisible();
    await expect(page.locator("header [data-testid=ardea-avatar]").first()).toHaveAttribute("aria-hidden", "true");
    const status = (await (await page.request.get("/api/associate/status")).json()) as { kill_switch: string | null; model: { ready?: boolean } };
    expect(!!status.kill_switch || !status.model?.ready).toBe(true); // paid calls are off on a preview
    await expect(page.getByTestId("associate-offline")).toContainText("Model not available");
    await expect(page.getByTestId("associate-offline")).toContainText("still answers from the Project Zero documentation");
    await expect(page.getByTestId("associate-welcome").getByRole("button")).toHaveCount(6);
    await expectNoScout(page);
    await expectNoHorizontalOverflow(page);
    expect(w.writes).toEqual([]);
    w.expectClean();
  });

  test("asking: answered from the docs, cited, remembered — and nothing in PZ changes", async ({ page }) => {
    const w = watch(page);
    const ids = trackConversations(page);
    await open(page);
    const before = await fingerprint(page);
    await page.getByTestId("associate-welcome").getByRole("button", { name: "Explain how a company reaches Radar." }).click();
    const answer = answers(page).last();
    await expect(answer).toContainText("model is not available", { timeout: 60_000 });
    await expect(answer).toContainText("Documentation only");
    await expect(page).toHaveURL(/[?&]c=c-[0-9a-f]{12}/);
    await expect(drawer(page).getByRole("button", { name: /^Explain how a company reaches Radar/ }).first()).toBeVisible();
    // a follow-up in the same conversation, typed (Enter sends; Shift+Enter is a newline)
    await box(page).fill("And what does Deal Flow triage mean?");
    await box(page).press("Enter");
    await expect(answers(page)).toHaveCount(2, { timeout: 60_000 });
    // remembered: a reload reads the same two turns back
    await page.reload();
    await expect(answers(page)).toHaveCount(2, { timeout: 60_000 });
    for (const a of await answers(page).all()) await expect(a).toContainText("Documentation only");
    expect(await fingerprint(page)).toBe(before);
    await expectNoScout(page);
    await expectNoHorizontalOverflow(page);
    await removeConversations(page, ids);
    w.expectClean();
  });

  test("a question about the retired Scout views is answered without naming them", async ({ page }) => {
    const w = watch(page);
    const ids = trackConversations(page);
    await open(page, "/associate?item=s-0001");
    await expect(page.getByTestId("associate-context")).toHaveCount(0); // the retired ?item= context is ignored
    await box(page).fill("Where is Scout Intake? Open the scout item link.");
    await box(page).press("Enter");
    const answer = answers(page).last();
    await expect(answer).toContainText("model is not available", { timeout: 60_000 });
    // the retired views and their links, never the plain word: an investor named "... Scout" in the documents is fine
    expect(await answer.innerText()).not.toMatch(/scout[\s_-]?(bridge|00|intake|item)|native[\s_-]?(scout|signals)|\?item=/i);
    expect(await answer.locator("a[href*='scout' i]").count()).toBe(0);
    await removeConversations(page, ids);
    w.expectClean();
  });

  test("context from Conviction travels as a trusted id; the palette hands a question over", async ({ page }) => {
    const w = watch(page);
    const ids = trackConversations(page);
    const pipe = (await (await page.request.get("/api/conviction/pipeline")).json()) as { signals: Signal[] };
    const slug = pipe.signals.find((s) => s.status !== "dropped")!.slug;
    await page.goto(`/conviction?company=${encodeURIComponent(slug)}`);
    await page.getByTestId("company-actions").locator("summary").click({ timeout: 60_000 });
    await page.getByRole("button", { name: "Ask PZ Associate" }).click();
    await expect(page).toHaveURL((u) => u.pathname === "/associate" && u.searchParams.get("company") === slug);
    await expect(page.getByTestId("associate-context")).toContainText(slug);
    const asked = page.waitForRequest((r) => new URL(r.url()).pathname === "/api/associate/ask");
    await box(page).fill("What is missing on this case?");
    await box(page).press("Enter");
    expect((await asked).postDataJSON()).toEqual({ message: "What is missing on this case?", conversation_id: null, context: { company: slug } });
    await expect(answers(page).last()).toBeVisible({ timeout: 60_000 });
    await page.getByRole("button", { name: "Clear the selected record" }).click();
    await expect(page.getByTestId("associate-context")).toHaveCount(0);

    await page.keyboard.press("Control+k");
    await page.getByRole("textbox", { name: "Search" }).fill("what needs my attention");
    const handed = page.waitForRequest((r) => new URL(r.url()).pathname === "/api/associate/ask");
    await page.getByRole("option").filter({ hasText: "Ask PZ Associate" }).click();
    expect((await handed).postDataJSON()).toEqual({ message: "what needs my attention", conversation_id: null, context: null });
    await expect(page).toHaveURL((u) => u.pathname === "/associate" && !u.searchParams.has("q") && /^c-[0-9a-f]{12}$/.test(u.searchParams.get("c") ?? ""), { timeout: 60_000 });
    await expect(answers(page).last()).toContainText("Documentation only");
    await removeConversations(page, ids);
    w.expectClean();
  });

  test("drafts are saved only after an explicit confirmation, to the Associate's own drafts", async ({ page }) => {
    const w = watch(page);
    const ids = trackConversations(page);
    await open(page);
    // the API refuses an unconfirmed draft outright
    expect((await page.request.post("/api/associate/draft", { data: { title: "x", body: "y" } })).status()).toBe(400);
    await page.getByRole("button", { name: "Drafts" }).click();
    const drafts = page.getByRole("dialog", { name: "Drafts" });
    await expect(drafts).toContainText("Nothing here has been sent");
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Your context" }).click();
    const ctx = page.getByRole("dialog", { name: "Your context" });
    await expect(ctx).toContainText("never changes Project Zero's methodology");
    await expect(ctx.getByRole("textbox")).toHaveCount(6);
    await page.keyboard.press("Escape");
    // an offline answer has no save action: a draft is saved only from an answer that offers one, after the Modal
    await page.getByTestId("associate-welcome").getByRole("button", { name: "Which events are coming up?" }).click();
    await expect(answers(page).last()).toContainText("Documentation only", { timeout: 60_000 });
    await expect(answers(page).last().getByRole("button", { name: "Save as draft" })).toHaveCount(0);
    expect(w.writes.filter((x) => x.endsWith("/associate/draft"))).toEqual([]);
    await removeConversations(page, ids);
    w.expectClean();
  });

  test("Ardea respects reduced motion and never loops; dark mode keeps it legible", async ({ page }) => {
    const w = watch(page);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await open(page);
    await expect(page.getByTestId("ardea-illustration")).toBeVisible();
    expect(await page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length)).toBe(0);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.addInitScript(() => localStorage.setItem("pz.theme", "dark"));
    await open(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.waitForTimeout(1200); // the one-shot entrance has finished
    expect(await page.evaluate(() => document.getAnimations().filter((a) => a.effect?.getTiming().iterations === Infinity).length)).toBe(0);
    expect(await page.getByTestId("ardea-illustration").locator('path[class*="_body_"]').first().evaluate((el) => getComputedStyle(el).fill)).toBe("rgb(138, 149, 166)");
    await expectNoHorizontalOverflow(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });

  for (const [name, size] of [
    ["1366", { width: 1366, height: 768 }],
    ["1920", { width: 1920, height: 1080 }],
    ["390 (phone)", { width: 390, height: 844 }],
  ] as const) {
    test(`no horizontal overflow at ${name}`, async ({ page }) => {
      const w = watch(page);
      await page.setViewportSize(size);
      await open(page);
      await expectNoHorizontalOverflow(page);
      await page.getByRole("button", { name: "Drafts" }).click();
      await expectNoHorizontalOverflow(page);
      expect(w.writes).toEqual([]);
      w.expectClean();
    });
  }

  test("no horizontal overflow at 150 % zoom", async ({ page }) => {
    const w = watch(page);
    await zoom150(page);
    await open(page);
    await expectNoHorizontalOverflow(page);
    await page.getByRole("button", { name: "Your context" }).click();
    await expectNoHorizontalOverflow(page);
    expect(w.writes).toEqual([]);
    w.expectClean();
  });
});
