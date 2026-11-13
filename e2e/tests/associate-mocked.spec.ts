/**
 * PZ Associate (review 033a) — the old `associate.spec.ts` checks (the identity, the Ardea illustration and the honest
 * offline banner; an offline ask, cited and remembered; the Conviction context and the palette hand-over; drafts only
 * after a confirmation; Ardea with reduced motion and in dark mode; no overflow), ported to the new page. The API is
 * MOCKED with route interception, so no backend is needed: only the frontend (`npm run dev` in frontend/, or
 * PZ_BASE_URL). The mock is a small Associate store behind the nine `associate/*` routes, seeded from fixtures/associate/
 * (byte-identical copies of `frontend/src/features/associate/test/*.json`); every name in it is invented.
 *
 * New here: the retired Scout parts are gone (no Scout suggestion, text or link, and the `?item=` context is ignored),
 * and an answer the server could not save (`saved: false`, revision 2) shows its notice and is not added back to the
 * conversation drawer. Old checks of the page's hues (`forbiddenHues`) and screenshots (`shot`) have no helper here.
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test associate-mocked
 */
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures", "associate");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (n: string): J => JSON.parse(readFileSync(resolve(FIX, n), "utf8"));

const FIRST = "c-0a1b2c3d4e5f";
const NEW = "c-5e6f7a8b9c0d";
const NOTICE = "This conversation was deleted while the answer was being prepared; the answer was not saved.";
const SUGGESTIONS = [
  "What should I focus on today?",
  "Which Conviction companies are waiting on a Manager decision?",
  "How does Deal Flow find and triage new candidates?",
  "Explain how a company reaches Radar.",
  "Show me the strongest Deal Flow candidates this week.",
  "Which events are coming up?",
];

/** A minimal invented Conviction set for the hand-over from the Conviction page (one company, the meta tables). */
const CONVICTION = {
  week: "2026-W46",
  signals: [
    {
      slug: "lumenfold",
      company: "Lumenfold",
      status: "new",
      conflict: "none",
      one_liner: "Optical sensing for cold-chain logistics.",
      location: "Lisbon, Portugal",
      discovery_source: "Invented Wire",
      discovery_date: "2026-10-01",
      earliness: "seed",
      archetype: 1,
      scores: { founder: 15, venture_scale: 15, why_now: 10, taste: 10, insight: 10 },
      verified: { founders: false, traction: false, funding: false },
      founders: [{ name: "Ines Varela", background: "ex-photonics lab" }],
      next_action: "Call Lumenfold",
      sc: { provisional: 70, verified: 40, missing: ["founders", "traction", "funding"], fully_verified: false, verdict: "INVESTIGATE", timing_label: "timing unknown", timing_action: "" },
    },
  ],
};
const ladder = (...steps: number[]) => steps.map((p) => [`step ${p}`, p]);
const META = {
  archetypes: [{ id: 1, name: "Vertical AI agent" }],
  ladders: { founder: ladder(0, 5, 10, 15, 20, 25), venture_scale: ladder(0, 5, 10, 15, 20), why_now: ladder(0, 5, 10, 15), taste: ladder(0, 5, 10, 15), insight: ladder(0, 5, 10) },
  earliness: { unknown: "Unknown", seed: "Seed" },
  timing: { unknown: "Unknown" },
  conflict: { none: "None", unclear: "Unclear" },
  penalties: {},
  tiers: { manual: "Manual — found by hand" },
  portfolio: [],
};

type Opts = { status?: J; ask?: (body: J, api: Api) => J };
type Api = Awaited<ReturnType<typeof mockApi>>;

/** Mock the Associate (a stateful store) and the reads the shell and the palette make; anything else under /api answers
 *  404 (the shell's not-ported reads are allowed by `watch`, any other 404 fails the test). Records every API request. */
async function mockApi(page: Page, opts: Opts = {}) {
  const requested: Array<{ method: string; path: string; body: J }> = [];
  const store = new Map<string, J>([[FIRST, load("conversation.json")]]);
  let index: J[] = load("conversations.json").conversations;
  let drafts: J[] = load("drafts.json").drafts;
  let profile: J = load("profile.json");
  let asks = 0;
  page.on("request", (r) => {
    if (!r.url().includes("/api/")) return;
    const u = new URL(r.url());
    let body: J = null;
    try {
      body = r.postDataJSON();
    } catch {
      body = null;
    }
    requested.push({ method: r.method(), path: u.pathname + u.search, body });
  });
  const api = {
    requested,
    writes: () => requested.filter((r) => r.method !== "GET"),
    posts: (path: string) => requested.filter((r) => r.method === "POST" && r.path === `/api/associate/${path}`).map((r) => r.body),
    drop: (id: string) => {
      store.delete(id);
      index = index.filter((c) => c.id !== id);
    },
  };
  const keep = (body: J, res: J) => {
    asks++;
    if (res.saved === false || !res.conversation) return;
    const { id, title } = res.conversation;
    const c = store.get(id) ?? { id, title, messages: [] };
    c.messages = [...c.messages, { role: "user", at: "2026-11-13T08:30:00Z", text: body.message, context: body.context ?? null }, res.message];
    c.updated = res.message.at;
    store.set(id, c);
    index = [{ id, title: c.title, updated: c.updated }, ...index.filter((x: J) => x.id !== id)];
  };
  await page.clock.setFixedTime(new Date(2026, 10, 13, 9, 30));
  await page.route(/\/api\//, async (route) => {
    const req = route.request();
    const u = new URL(req.url());
    const p = u.pathname.replace(/^\/api\//, "");
    const body: J = req.method() === "POST" ? req.postDataJSON() : null;
    const ok = (json: J) => route.fulfill({ json });
    const key = `${req.method()} ${p}`;
    switch (key) {
      case "GET associate/status":
        return ok(opts.status ?? load("status_offline.json"));
      case "GET associate/conversations":
        return ok({ conversations: index });
      case "GET associate/conversation": {
        const c = store.get(u.searchParams.get("id") ?? "");
        return c ? ok(c) : route.fulfill({ status: 404, json: { ok: false, error: "conversation not found" } });
      }
      case "POST associate/ask": {
        let res: J;
        if (opts.ask) res = opts.ask(body, api);
        else {
          res = load("ask_offline.json");
          const id = body.conversation_id || (asks === 0 ? NEW : `c-5e6f7a8b9c${String(asks).padStart(2, "0")}`);
          res.conversation = { id, title: store.get(id)?.title ?? String(body.message).slice(0, 60) };
        }
        keep(body, res);
        return ok(res);
      }
      case "POST associate/conversation_delete":
        api.drop(body.id);
        return ok({ ok: true });
      case "GET associate/profile":
        return ok(profile);
      case "POST associate/profile":
        profile = { ...profile, profile: { ...Object.fromEntries(profile.fields.map((f: J) => [f.key, String(body[f.key] ?? "")])), updated: "2026-11-13T08:45:00Z" } };
        return ok({ profile: profile.profile });
      case "GET associate/drafts":
        return ok({ drafts });
      case "POST associate/draft": {
        if (body.confirm !== true) return route.fulfill({ status: 400, json: { ok: false, error: "saving a draft needs your explicit confirmation (confirm: true)" } });
        const d = { id: "d-1a2b3c4d5e", title: body.title, body: body.body, created: "2026-11-13T08:50:00Z" };
        drafts = [d, ...drafts];
        return ok({ draft: d });
      }
      case "POST associate/draft_delete":
        drafts = drafts.filter((d) => d.id !== body.id);
        return ok({ ok: true });
      case "GET events":
        return ok({ events: [] });
      case "GET conviction/pipeline":
        return ok(CONVICTION);
      case "GET conviction/meta":
        return ok(META);
      case "GET conviction/case":
        return ok({ state: "NOT STARTED", why: "No case has been prepared yet.", steps: [], usd: 0, audit: [] });
    }
    return route.fulfill({ status: 404, json: { ok: false, error: "not found" } });
  });
  return api;
}

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

test.describe("PZ Associate — mocked API", () => {
  test("the identity, the Ardea illustration and the honest offline banner; only Associate reads", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    await expect(page.getByRole("complementary", { name: "Main navigation" }).getByRole("link", { name: "PZ Associate" })).toBeVisible();
    // the full character carries the accessible name; the header avatar duplicates the visible name, so it is hidden
    await expect(page.getByRole("img", { name: "Ardea, the PZ Associate heron" })).toBeVisible();
    await expect(page.locator("header [data-testid=ardea-avatar]").first()).toHaveAttribute("aria-hidden", "true");
    await expect(page.locator("header [data-testid=ardea-avatar]").first()).toHaveAttribute("data-state", "ready");
    await expect(page.getByTestId("associate-offline")).toHaveText(
      "Model not available — paid AI is switched off. PZ Associate still answers from the Project Zero documentation; record lookups need the model.",
    );
    await expect(page.getByTestId("associate-welcome").getByRole("button")).toHaveText(SUGGESTIONS);
    await expect(drawer(page).getByRole("button", { name: /^Which Conviction companies/ })).toBeVisible();
    await expectNoScout(page);
    expect([...new Set(api.requested.filter((r) => r.path.startsWith("/api/associate/")).map((r) => r.path))].sort()).toEqual(["/api/associate/conversations", "/api/associate/status"]);
    expect(api.writes()).toEqual([]);
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });

  test("asking: answered from the docs, cited, remembered; the follow-up stays in the conversation", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page);
    await page.getByTestId("associate-welcome").getByRole("button", { name: SUGGESTIONS[2] }).click();
    const answer = answers(page).last();
    await expect(answer).toContainText("The model is not available right now");
    await expect(answer).toContainText("Documentation only");
    await expect(answer.getByText("Documentation", { exact: true })).toBeVisible();
    await expect(answer).toContainText("PZ_DEAL_FLOW.md › Deal Flow triage · PZ_DEAL_FLOW.md › Your queue");
    await expect(page).toHaveURL(new RegExp(`[?&]c=${NEW}`));
    await expect(drawer(page).getByRole("button", { name: /^How does Deal Flow/ })).toHaveAttribute("aria-current", "true");
    await expect(page.locator("header [data-testid=ardea-avatar]").first()).toHaveAttribute("data-state", "uncertain");
    // a follow-up in the same conversation, typed (Enter sends; Shift+Enter is a newline)
    await box(page).fill("And what does Radar mean?");
    await box(page).press("Shift+Enter");
    expect(api.posts("ask")).toHaveLength(1);
    await box(page).press("Enter");
    await expect(answers(page)).toHaveCount(2);
    expect(api.posts("ask")).toEqual([
      { message: SUGGESTIONS[2], conversation_id: null, context: null },
      { message: "And what does Radar mean?", conversation_id: NEW, context: null }, // trimmed, as before
    ]);
    // remembered: a reload opens the same conversation from the drawer
    await page.reload();
    await expect(answers(page)).toHaveCount(2, { timeout: 60_000 });
    expect(api.writes().every((r) => r.path === "/api/associate/ask")).toBe(true);
    await expectNoScout(page);
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });

  test("a saved conversation: every part of a model answer, and its open action", async ({ page }) => {
    const w = watch(page);
    await mockApi(page, { status: load("status_ready.json") });
    await open(page, `/associate?c=${FIRST}`);
    await expect(page.getByTestId("associate-offline")).toHaveCount(0);
    const a = answers(page).first();
    await expect(a.getByRole("link", { name: "the case" })).toHaveAttribute("href", "/conviction?company=lumenfold");
    await expect(a).toContainText("their site (https://lumenfold.example)");
    await expect(a.getByRole("link", { name: "Lumenfold", exact: true })).toHaveAttribute("href", "/conviction?company=lumenfold");
    await expect(a.getByText("Nimbra Labs")).toBeVisible();
    await expect(a.getByTestId("associate-trace")).toHaveText(/Read: manager decisions, company detail, candidate detail.*1 uncited reference\(s\) removed.*kept with you/);
    await expect(a.getByRole("button", { name: "Save as draft" })).toBeVisible();
    await a.getByRole("link", { name: "Open Lumenfold" }).click();
    await expect(page).toHaveURL((u) => u.pathname === "/conviction" && u.search === "?company=lumenfold");
    w.expectClean();
  });

  test("the Conviction context travels as a trusted id; the palette hands a question over; ?item= is ignored", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await page.goto("/conviction?company=lumenfold");
    await page.getByTestId("company-actions").locator("summary").click({ timeout: 60_000 });
    await page.getByRole("button", { name: "Ask PZ Associate" }).click();
    await expect(page).toHaveURL(/\/associate\?company=lumenfold$/);
    await expect(page.getByTestId("associate-context")).toHaveText("About: Company lumenfold");
    await box(page).fill("What is missing on this case?");
    await box(page).press("Enter");
    await expect(answers(page)).toHaveCount(1);
    expect(api.posts("ask")[0]).toEqual({ message: "What is missing on this case?", conversation_id: null, context: { company: "lumenfold" } });
    await page.getByRole("button", { name: "Clear the selected record" }).click();
    await expect(page.getByTestId("associate-context")).toHaveCount(0);

    await page.keyboard.press("Control+k");
    await page.getByRole("textbox", { name: "Search" }).fill("what needs my attention");
    await page.getByRole("option").filter({ hasText: "Ask PZ Associate" }).click();
    await expect.poll(() => api.posts("ask").length).toBe(2);
    expect(api.posts("ask")[1]).toEqual({ message: "what needs my attention", conversation_id: null, context: null });
    await expect(page).toHaveURL((u) => u.pathname === "/associate" && !u.searchParams.has("q") && u.searchParams.has("c"));
    await expect(answers(page).last()).toBeVisible();

    await page.goto("/associate?item=s-0042");
    await expect(page.getByRole("heading", { level: 1, name: "PZ Associate" })).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("associate-context")).toHaveCount(0);
    await expectNoScout(page);
    expect(api.writes().every((r) => r.path === "/api/associate/ask")).toBe(true);
    w.expectClean();
  });

  test("drafts are saved only after an explicit confirmation, to the Associate's own drafts", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await open(page, `/associate?c=${FIRST}`);
    const save = answers(page).first().getByRole("button", { name: "Save as draft" });
    await save.click();
    const dlg = page.getByRole("dialog", { name: "Save as a draft" });
    await expect(dlg).toContainText("It is not sent to anyone and changes no record.");
    await dlg.getByRole("button", { name: "Cancel" }).click();
    await expect(dlg).toHaveCount(0);
    await save.click();
    await page.keyboard.press("Escape");
    await expect(dlg).toHaveCount(0);
    expect(api.writes()).toEqual([]);
    await save.click();
    await expect(dlg.getByRole("textbox", { name: "Title" })).toHaveValue("Manager questions for Lumenfold");
    await dlg.getByRole("button", { name: "Save draft" }).click();
    await expect(page.getByText("Draft saved to your PZ Associate drafts — nothing was sent")).toBeVisible();
    expect(api.posts("draft")).toEqual([
      expect.objectContaining({ title: "Manager questions for Lumenfold", conversation_id: FIRST, confirm: true, ref: expect.objectContaining({ id: "lumenfold" }) }),
    ]);
    await page.getByRole("button", { name: "Drafts" }).click();
    const drafts = page.getByRole("dialog", { name: "Drafts" });
    await expect(drafts).toContainText("Nothing here has been sent");
    await expect(drafts.locator("li strong")).toHaveText(["Manager questions for Lumenfold", "Manager questions for Lumenfold", "Intro note to Orvella"]);
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "Your context" }).click();
    const ctx = page.getByRole("dialog", { name: "Your context" });
    await expect(ctx).toContainText("never changes Project Zero's methodology");
    await expect(ctx.getByRole("textbox")).toHaveCount(6);
    await expectNoScout(page);
    w.expectClean();
  });

  test("an answer the server could not save shows its notice and is not added back to the drawer", async ({ page }) => {
    const w = watch(page);
    await mockApi(page, {
      ask: (body, api) => {
        api.drop(body.conversation_id); // deleted in another tab while the answer was prepared
        return load("ask_unsaved.json");
      },
    });
    await open(page, `/associate?c=${FIRST}`);
    await expect(answers(page)).toHaveCount(1);
    await box(page).fill("Explain how a company reaches Radar.");
    await box(page).press("Enter");
    await expect(page.getByTestId("associate-unsaved")).toHaveText(NOTICE);
    await expect(answers(page)).toHaveCount(1);
    await expect(answers(page).first()).toContainText("A company reaches Radar only once every claim on its case is verified.");
    await expect(page).toHaveURL((u) => u.pathname === "/associate" && !u.searchParams.has("c"));
    await expect(drawer(page).getByRole("button", { name: /^Which Conviction companies/ })).toHaveCount(0);
    await expect(drawer(page).locator("[aria-current]")).toHaveCount(0);
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });

  test("Ardea respects reduced motion and never loops; dark mode keeps it legible", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await open(page);
    await expect(page.getByTestId("ardea-illustration")).toBeVisible();
    const running = () => page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running").length);
    expect(await running()).toBe(0);
    const lightBody = await page.getByTestId("ardea-illustration").locator('path[class*="_body_"]').first().evaluate((el) => getComputedStyle(el).fill);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await page.addInitScript(() => localStorage.setItem("pz.theme", "dark"));
    await open(page);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.waitForTimeout(1200); // the one-shot entrance has finished
    expect(await page.evaluate(() => document.getAnimations().filter((a) => a.effect?.getTiming().iterations === Infinity).length)).toBe(0);
    const darkBody = await page.getByTestId("ardea-illustration").locator('path[class*="_body_"]').first().evaluate((el) => getComputedStyle(el).fill);
    expect(darkBody).toBe("rgb(138, 149, 166)"); // the lighter dark-mode plumage
    expect(darkBody).not.toBe(lightBody);
    await expect(page.getByRole("img", { name: "Ardea, the PZ Associate heron" })).toBeVisible();
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
      await mockApi(page);
      await page.setViewportSize(size);
      await open(page);
      await expectNoHorizontalOverflow(page);
      await drawer(page).getByRole("button", { name: /^Which Conviction companies/ }).click();
      await expect(answers(page)).toHaveCount(1);
      await expectNoHorizontalOverflow(page);
      await page.getByRole("button", { name: "Drafts" }).click();
      await expectNoHorizontalOverflow(page);
    });
  }

  test("no horizontal overflow at 150 % zoom", async ({ page }) => {
    await mockApi(page);
    await zoom150(page);
    await open(page, `/associate?c=${FIRST}`);
    await expect(answers(page)).toHaveCount(1);
    await expectNoHorizontalOverflow(page);
    await page.getByRole("button", { name: "Your context" }).click();
    await expectNoHorizontalOverflow(page);
  });
});
