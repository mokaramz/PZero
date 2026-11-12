/**
 * Founder Radar (review 026a) — the old `founder-radar.spec.ts` (itself the Playwright re-expression of v1's
 * browser_output_first, browser_founder_radar_acceptance, browser_founder_radar_search, browser_review_ux and
 * browser_review_binding) ported to the new paths. The API is MOCKED with route interception, so no backend is needed:
 * only the frontend (`npm run dev` in frontend/, or PZ_BASE_URL). Every person, company and domain in
 * fixtures/founder-radar/ is invented. The exact POST bodies are asserted.
 *
 * The founder scan and the company research runs (review 026b) are live: the old spec's synchronous scan and polled
 * job, a 409 shown as the error, the research bodies and the resumable queue's batches.
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test founder-radar-mocked
 */
import { expect, test, type Page, type Request } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures", "founder-radar");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (n: string): J => JSON.parse(readFileSync(resolve(FIX, n), "utf8"));
const CSV = resolve(FIX, "sample_Connections.csv");
const KELP = "dom:kelpwise.example";
const BRIDGE = "External research jobs arrive with the bridge port";
const QUEUE = "Research company queue (all leads with an official domain, resumable)";
const BUSY = "Another founder scan or research run is in progress — try again when it finishes.";
/** the fetching endpoints (and the never-ported bridge): the identity checks below must call none of them */
const NETWORK = /\/api\/(founder-radar\/(scan|research|research_queue)|radar_scan|radar_research|radar_research_queue|bridge_create)\b/;

type Posted = { path: string; body: J };

/** Mock every endpoint the page reads or writes; anything else under /api answers 404 (the shell's not-ported reads are
 *  allowed by `watch`, any other 404 fails the test). Returns every request and every POST body, in order.
 *  `scan` replaces the scan's answer (`{status, json}`); `radarAfter` is what the radar answers from the second read after
 *  a scan on (the re-read right after the answer still has the old scan time, so a started job must be polled). */
async function mockApi(page: Page, opts: { radar?: J; proposals?: Record<string, J>; scan?: { status?: number; json: J }; radarAfter?: J } = {}) {
  const radar = opts.radar ?? load("founder_radar.json");
  const proposals = opts.proposals ?? { [KELP]: load("proposals_kelpwise.json"), "dom:borealis.example": load("proposals_borealis.json") };
  const posted: Posted[] = [];
  const requested: string[] = [];
  let radarReads = 0;
  let readsAfterScan = -1;
  let queueCalls = 0;
  const body = (r: Request) => {
    try {
      return r.postDataJSON();
    } catch {
      return null;
    }
  };
  page.on("request", (r) => r.url().includes("/api/") && requested.push(new URL(r.url()).pathname));
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/founder-radar(\?.*)?$/, (route) => {
    radarReads++;
    const after = opts.radarAfter && readsAfterScan >= 0 && ++readsAfterScan >= 2;
    return route.fulfill({ json: after ? opts.radarAfter : radar });
  });
  await page.route(/\/api\/founder-radar\/proposals$/, (route) => {
    const b = body(route.request());
    posted.push({ path: "proposals", body: b });
    return route.fulfill({ json: proposals[b?.key] ?? { ok: true, groups: [], recommended: [], summary: {}, history: [] } });
  });
  await page.route(/\/api\/(founder-radar\/(action|review|pair|company|import|promote|boardy_brief|scan|research|research_queue)|network\/person_save)$/, (route) => {
    const path = route.request().url().split("/api/")[1].replace(/^(founder-radar|network)\//, "");
    const b = body(route.request());
    posted.push({ path, body: b });
    if (path === "scan") {
      readsAfterScan = 0;
      return route.fulfill({ status: opts.scan?.status ?? 200, json: opts.scan?.json ?? { ...radar.health, scan_time: "2026-11-12 09:30" } });
    }
    const R: Record<string, J> = {
      action: b?.action === "merge" && !b?.confirm ? { ok: false, error: "merge refused: confirm it", needs_confirmation: true } : { ok: true, person: {} },
      review: { ok: true, facts: ["founded", "funding"], identity_bound: b?.bindings && Object.keys(b.bindings).length ? [{ name: "Mira Talvik" }] : [], still_pending: [], conflicts: [], refused: [] },
      pair: { ok: true, pairing: {} },
      company: { ok: true },
      import: {
        ok: true,
        format: "linkedin_connections",
        rows: 3,
        new: 3,
        merged: 0,
        skipped: [],
        note: "imported as identity-unresolved records with import provenance (official LinkedIn Connections export) — nothing was scanned from LinkedIn, nothing was verified or promoted",
      },
      promote: { ok: true, person: {}, error: null },
      boardy_brief: { ok: true, brief: "Intro request for Oskar Lindqvist — public evidence only.", sent: false, note: "No Boardy API — paste this into Boardy yourself." },
      person_save: { ok: true, id: b?.id },
      research: { ok: true, researched: [{ key: b?.key ?? "", name: "Quillstone AI", ok: true, pages: 5, proposals: 9, new: 0 }] },
      research_queue:
        path === "research_queue" && ++queueCalls === 1
          ? { ok: true, processed: [], done: 1, remaining: 1, failed: {}, skipped_no_domain: ["Grainline Labs"], in_progress: true, resume: true }
          : { ok: true, processed: [], done: 2, remaining: 0, failed: { "dom:quillstone.example": "HTTP 404" }, skipped_no_domain: ["Grainline Labs"], in_progress: false, resume: false },
    };
    return route.fulfill({ json: R[path] });
  });
  return { posted, requested, radarReads: () => radarReads, writes: () => posted.filter((p) => p.path !== "proposals") };
}

const tab = (page: Page, name: string) => page.getByRole("tab", { name: new RegExp("^" + name.replace(/[+()]/g, "\\$&")) });
async function open(page: Page, qs = "") {
  await page.goto("/founder-radar" + qs);
  await expect(page.getByRole("heading", { name: "Founder Radar", level: 1 })).toBeVisible({ timeout: 60_000 });
}
const researchQueue = async (page: Page) => {
  await tab(page, "Research Queue").click();
  await expect(page.getByTestId("fr-research")).toBeVisible();
};

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
});

/* ------------------------------------------------------------------ browser_output_first.js */
test("output-first: Top Founder Leads is the default view with understandable lead cards", async ({ page }) => {
  const w = watch(page);
  await mockApi(page);
  await open(page);
  await expect(tab(page, "Top Founder Leads")).toHaveAttribute("aria-selected", "true");
  const leads = page.getByTestId("fr-leads");
  const cards = leads.getByTestId("fr-lead-card");
  await expect(cards).toHaveCount(3);
  await expect(page.getByTestId("fr-research")).toHaveCount(0);
  await expect(page.getByTestId("fr-diag")).toHaveCount(0);
  const t = await leads.innerText();
  expect(t).not.toMatch(/rank \d|Research priority|proposal id|hiring_signal|source health/i);
  for (const k of ["Why this founder stands out", "Founder-specific evidence", "Company momentum", "Project A relevance", "LinkedIn", "Public contact", "Access", "Important unknowns", "Next action", "View evidence"])
    expect(t, k).toContain(k);
  expect(t).toContain("Mira Talvik");
  expect(t).toContain("Ilka Moravec");
  expect(t).toContain("Borealis Robotics");
  expect(t).toMatch(/machine-qualified candidate/i);
  await expect(leads.getByRole("link", { name: "Search on LinkedIn ↗" }).first()).toBeVisible();
  await expect(leads.getByRole("link", { name: /linkedin\.com\/in\/ilka-moravec-borealis/ })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await tab(page, "Near Matches").click();
  await expect(page.getByText("Founders with some sourced signal but not enough")).toBeVisible();

  await tab(page, "Diagnostics").click();
  await expect(page.locator("#frHealth")).toBeVisible();
  await expect(page.locator("#frCoverage")).toBeVisible();
  await researchQueue(page);
  await expect(page.getByTestId("fr-list")).toContainText(/company lead/i);
  w.expectClean();
});

test("honestly empty: no verified founders yet", async ({ page }) => {
  const w = watch(page);
  const radar = load("founder_radar.json");
  radar.leads = { top: [], near: [], total_candidates: 0 };
  await mockApi(page, { radar });
  await open(page);
  await expect(page.getByText(/No verified founders yet — honestly empty\. A person appears here only when an official company\/team\/press page/)).toBeVisible();
  w.expectClean();
});

/* ------------------------------------------------------------------ browser_founder_radar_acceptance.js */
test("acceptance: gates render, company queue groups claimed founders, header never sticks", async ({ page }) => {
  const w = watch(page);
  await mockApi(page);
  await open(page);
  await researchQueue(page);
  // the Research Queue opens on the company qualification queue (claim segment) with the reconciliation counts line
  await expect(tab(page, "Founder claims — unverified")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("fr-counts")).toContainText("Company leads 4 · claimed founders 6 · separately: 6 people currently in Founder claim bucket");
  const companyCards = page.getByTestId("fr-company-card");
  await expect(companyCards).toHaveCount(4);
  for (const t of await companyCards.allTextContents()) expect(t).toMatch(/claimed founder/i);
  const claimTexts = await companyCards.allInnerTexts();
  expect(claimTexts.some((t) => t.includes("grainhacker") && /LOGIN ONLY/i.test(t) && !/order \d+/.test(t))).toBe(true);
  expect((await page.getByTestId("fr-list").innerText()).includes("UNKNOWN")).toBe(true);

  await tab(page, "Gold now + Strong investigation").click();
  const gold = await page.getByTestId("fr-person-card").locator("header span").allInnerTexts();
  expect(gold).not.toContain("grainhacker");
  expect(gold).not.toContain("Oskar Lindqvist");
  await expect(page.getByText(/Nobody qualifies as Gold or Strong yet/)).toBeVisible();
  await expect(page.getByTestId("fr-counts")).toContainText("deserve attention first (Gold + Strong)");

  await tab(page, "Insufficient / out of scope").click();
  const insuf = await page.getByTestId("fr-person-card").allInnerTexts();
  expect(insuf.some((t) => t.includes("Oskar Lindqvist") && /not founder-scorable/i.test(t))).toBe(true);

  // the page header / toolbar is static: it scrolls away and never covers content (4 layouts, v1 acceptance hotfix)
  for (const [wd, h] of [
    [1366, 768],
    [1920, 1080],
    [1093, 614],
    [911, 512],
  ]) {
    await page.setViewportSize({ width: wd, height: h });
    await tab(page, "Founder claims — unverified").click();
    const pos = await page.evaluate(() => getComputedStyle(document.querySelector("[data-testid=fr-counts]")!.closest("header")!).position);
    expect(pos).toBe("static");
    await expectNoHorizontalOverflow(page);
  }
  w.expectClean();
});

test("acceptance: unresolved identity blocks promotion, opportunity and Boardy in the evidence drawer", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  await open(page);
  await researchQueue(page);
  await page.getByTestId("fr-company-card").filter({ hasText: "Kelpwise GmbH" }).getByRole("button", { name: "Mira Talvik" }).click();
  const drawer = page.getByRole("dialog", { name: "Mira Talvik" });
  await expect(drawer).toBeVisible();
  const t = await drawer.innerText();
  expect((t.match(/Resolve identity before promotion/g) ?? []).length).toBeGreaterThanOrEqual(3);
  expect(await drawer.locator("button[disabled]").count()).toBeGreaterThanOrEqual(3);
  await expect(drawer.getByLabel("Boardy status")).toBeDisabled();
  const scout = drawer.getByRole("button", { name: "Ask Scout 00 for identity evidence" });
  await expect(scout).toHaveAttribute("aria-disabled", "true");
  await expect(scout).toHaveAttribute("title", BRIDGE);
  await scout.click({ force: true }); // aria-disabled: Playwright would wait for it to be enabled
  expect(api.writes()).toEqual([]);
  expect(api.requested.filter((p) => NETWORK.test(p))).toEqual([]);
  w.expectClean();
});

/* ------------------------------------------------------------------ browser_founder_radar_search.js */
test("search: an identity-unresolved founder is found by name everywhere; company search works; nothing is written", async ({ page }) => {
  const w = watch(page);
  const { posted } = await mockApi(page);
  await open(page);
  const box = page.getByRole("searchbox", { name: "Search people" });
  await box.fill("Sana Okafor");
  const block = page.getByTestId("fr-search-block");
  await expect(block).toContainText("Search results for “sana okafor”");
  await expect(block.getByTestId("fr-company-card").filter({ hasText: "Quillstone AI" })).toContainText(/company lead/i);
  await expect(block.getByTestId("fr-person-card").filter({ hasText: "Sana Okafor" }).first()).toBeVisible();
  await expect(block).toContainText(/needs identity resolution/i);
  await expect(block).toContainText(/\d+ people · \d+ company leads/);
  await expect(tab(page, "Top Founder Leads")).toHaveAttribute("aria-selected", "true");

  await researchQueue(page);
  const leadNames = () => page.getByTestId("fr-list").getByTestId("fr-company-card").locator("header > span:first-child").allInnerTexts();
  expect(await leadNames()).toEqual(["Quillstone AI"]);
  await expect(page.getByTestId("fr-list")).toContainText("People matching “sana okafor”");
  await expect(page.getByTestId("fr-list").getByTestId("fr-person-card").filter({ hasText: "Sana Okafor" }).first()).toBeVisible();

  await tab(page, "Gold now + Strong investigation").click();
  await expect(page.getByTestId("fr-list")).toContainText("Sana Okafor");

  await tab(page, "Founder claims — unverified").click();
  await box.fill("Quillstone");
  await expect.poll(leadNames).toContain("Quillstone AI");
  await box.fill("");
  await expect.poll(async () => (await leadNames()).length).toBe(4);
  const all = await leadNames();
  await box.fill("Borealis");
  await expect.poll(leadNames).toEqual(["Borealis Robotics"]);
  await box.fill("zzzz-no-such-name");
  await expect(page.getByTestId("fr-list")).toContainText("No company lead matches");
  await expect(page.getByTestId("fr-list")).toContainText("No person matches");
  await box.fill("");
  await expect.poll(leadNames).toEqual(all);
  await tab(page, "Gold now + Strong investigation").click();
  await expect(page.getByTestId("fr-list")).not.toContainText("Sana Okafor");
  expect(posted, "searching never writes").toEqual([]);
  w.expectClean();
});

/* ------------------------------------------------------------------ browser_review_ux.js */
for (const zoom of [1, 1.5]) {
  test(`review drawer UX @${zoom * 100}%: one row per fact, alternatives collapsed, bulk excludes identity, no overflow`, async ({ page }) => {
    const w = watch(page);
    const { posted } = await mockApi(page);
    if (zoom !== 1) await zoom150(page);
    await open(page);
    await researchQueue(page);
    const card = page.getByTestId("fr-company-card").filter({ hasText: "Kelpwise GmbH" });
    const cardText = await card.innerText();
    expect(cardText).toContain("Priority:");
    expect(cardText).toContain("Why:");
    expect(cardText).toContain("Next:");
    expect(cardText).not.toContain("Research priority ");
    await card.getByRole("button", { name: /^Review proposals/ }).click();
    const drawer = page.getByRole("dialog", { name: "Review — Kelpwise GmbH" });
    await expect(drawer).toBeVisible();
    const rows = drawer.getByTestId("fr-review-row");
    await expect(rows.first()).toBeVisible();
    const keys = await rows.evaluateAll((els) => els.map((e) => `${e.getAttribute("data-field")} = ${e.getAttribute("data-value")}`));
    expect(keys.length).toBeGreaterThan(0);
    expect(new Set(keys).size, "no duplicate fact rows").toBe(keys.length);
    expect(await drawer.locator("details[open]").count()).toBe(0);
    const t = (await drawer.textContent()) ?? "";
    for (const k of ["Research summary", "Recommended facts", "Missing Gold/Strong requirements", "duplicate passage(s) hidden", "Why it matters"]) expect(t).toContain(k);
    const recFields = await drawer.locator("[data-testid=fr-review-row][data-recommended]").evaluateAll((els) => els.map((e) => e.getAttribute("data-field")));
    expect(recFields.length).toBeGreaterThan(0);
    expect(recFields).not.toContain("founder");
    expect(keys).toContain("founder = Mira Talvik");
    expect(keys).toContain("founder = Jonas Brekke");
    for (const k of keys.filter((x) => x.startsWith("founder"))) expect(k).not.toMatch(/Call|About|Contact|Meet|CEO|Co-/);
    const overflow = await drawer.evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow, "review drawer horizontal overflow").toBeLessThanOrEqual(2);
    await expectNoHorizontalOverflow(page);

    await drawer.getByRole("button", { name: /^Confirm recommended facts \(\d+\)$/ }).click();
    await expect.poll(() => posted.find((p) => p.path === "review")).toBeTruthy();
    const rv = posted.find((p) => p.path === "review")!.body;
    const fx = load("proposals_kelpwise.json");
    expect(rv).toEqual({ key: KELP, confirm: fx.recommended, bindings: {} });
    const founderIds = fx.groups.filter((g: J) => g.field === "founder").map((g: J) => g.best.id);
    for (const id of founderIds) expect(rv.confirm).not.toContain(id);
    await expect(page.getByText(/Confirmed 2 recommended fact\(s\): founded, funding/)).toBeVisible();
    w.expectClean();
  });
}

/* ------------------------------------------------------------------ browser_review_binding.js */
test("review binding: per-row founder selectors, explicit pairing, per-proposal bindings, replay blocked", async ({ page }) => {
  const w = watch(page);
  const fx = load("proposals_kelpwise.json");
  // Jonas' founder proposal already confirmed → its checkbox and selector are disabled (replays are never re-applied)
  const jonas = fx.groups.find((g: J) => g.field === "founder" && g.value === "Jonas Brekke");
  jonas.best.status = "confirmed";
  jonas.status = "confirmed";
  fx.history = [{ on: "2026-11-10 21:05:00", proposal: jonas.best.id, from: "pending", to: "confirmed", person: "p-jonas-brekke-1002" }];
  const { posted } = await mockApi(page, { proposals: { [KELP]: fx } });
  await open(page, "?view=research&review=" + encodeURIComponent(KELP));
  const drawer = page.getByRole("dialog", { name: "Review — Kelpwise GmbH" });
  await expect(drawer).toBeVisible();
  const selects = drawer.getByTestId("fr-bind");
  await expect(selects).toHaveCount(2);
  const refresh = drawer.getByRole("button", { name: "Refresh research" });
  await expect(refresh).toBeVisible();
  await expect(refresh).toBeEnabled();
  await expect(drawer.getByText("Decision history (1, append-only)")).toBeVisible();

  const mira = drawer.locator("[data-testid=fr-review-row][data-field=founder][data-value='Mira Talvik']");
  const pid = await mira.getByTestId("fr-bind").getAttribute("data-prop");
  const radar = load("founder_radar.json");
  const miraId = radar.companies.find((x: J) => x.key === KELP).founders.find((f: J) => f.name === "Mira Talvik").id;
  await mira.getByTestId("fr-bind").selectOption(miraId);
  await mira.getByRole("button", { name: "Confirm pairing…" }).click();
  const dlg = page.getByRole("dialog", { name: "Confirm pairing" });
  await dlg.getByRole("button", { name: "Pair" }).click();
  await expect(dlg).toContainText("Pair proposed human name");
  await dlg.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect.poll(() => posted.find((p) => p.path === "pair")?.body).toEqual({ key: KELP, proposal: pid, person: miraId });

  await mira.getByRole("checkbox").check();
  await drawer.getByRole("button", { name: "Confirm selected" }).click();
  await expect.poll(() => posted.find((p) => p.path === "review")?.body).toEqual({ key: KELP, bindings: { [pid!]: miraId }, confirm: [pid] });
  await expect(page.getByText(/identity: Mira Talvik ✓/)).toBeVisible();

  const jonasRow = drawer.locator("[data-testid=fr-review-row][data-field=founder][data-value='Jonas Brekke']");
  await expect(jonasRow.getByRole("checkbox")).toBeDisabled();
  await expect(jonasRow.getByTestId("fr-bind")).toBeDisabled();
  w.expectClean();
});

/* ------------------------------------------------------------------ import, the scan, research, actions, diagnostics */
test("authorized import: CSV file is read client-side and posted to founder-radar/import", async ({ page }) => {
  const w = watch(page);
  const { posted } = await mockApi(page);
  await open(page);
  await page.getByRole("button", { name: "Authorized import (CSV)" }).click();
  const dlg = page.getByRole("dialog", { name: "Authorized import (CSV / TSV)" });
  await expect(dlg).toContainText("official LinkedIn Connections export");
  await expect(dlg).toContainText("Nothing is scanned from LinkedIn — no cookies, no automation.");
  await dlg.getByPlaceholder("label, e.g. 'LinkedIn Connections export 2026-09'").fill("LinkedIn Connections export 2026-10");
  await dlg.getByTestId("fr-import-file").setInputFiles(CSV);
  await expect(dlg).toContainText("sample_Connections.csv loaded");
  await expect(dlg.getByPlaceholder("paste CSV / TSV here")).toHaveValue(/First Name,Last Name,URL/);
  await dlg.getByRole("button", { name: "Import", exact: true }).click();
  await expect.poll(() => posted.find((p) => p.path === "import")?.body).toBeTruthy();
  const b = posted.find((p) => p.path === "import")!.body;
  expect(Object.keys(b).sort()).toEqual(["csv", "include_email", "label"]);
  expect(b.label).toBe("LinkedIn Connections export 2026-10");
  expect(b.include_email).toBe(false);
  expect(b.csv).toContain("Petra,Lunde");
  await expect(page.getByText(/LinkedIn Connections export: 3 new · 0 merged/)).toBeVisible();
  await expect(dlg).toHaveCount(0);
  w.expectClean();
});

test("scan founder signals: the synchronous health report", async ({ page }) => {
  const w = watch(page);
  const { posted } = await mockApi(page);
  await open(page);
  const scan = page.getByRole("button", { name: "Scan founder signals" });
  await expect(scan).toBeEnabled();
  await scan.click();
  await expect(page.getByText(/Scan done: \d+ ok · \d+ failed · \d+ new · \d+ merged/)).toBeVisible();
  expect(posted.filter((p) => p.path === "scan").map((p) => p.body)).toEqual([{}]);
  await expect(page.getByRole("button", { name: "Scan founder signals" })).toBeEnabled();
  w.expectClean();
});

test("scan founder signals: a started job is polled until the scan time changes", async ({ page }) => {
  const w = watch(page);
  const after = load("founder_radar.json");
  after.health.scan_time = "2026-11-12 10:00";
  after.health.totals.ok = 5;
  const api = await mockApi(page, { radarAfter: after, scan: { json: { started: true } } });
  await open(page);
  await page.getByRole("button", { name: "Scan founder signals" }).click();
  await expect(page.getByRole("button", { name: "Scanning…" })).toBeDisabled();
  await expect(page.getByText(/Scan done: 5 ok/)).toBeVisible({ timeout: 15_000 });
  expect(api.radarReads()).toBeGreaterThan(2); // the first read, the re-read after the answer, at least one poll
  expect(api.posted.filter((p) => p.path === "scan").map((p) => p.body)).toEqual([{}]);
  await expect(page.getByRole("button", { name: "Scan founder signals" })).toBeEnabled();
  w.expectClean();
});

test("scan founder signals: a 409 (another run in progress) is shown as the error", async ({ page }) => {
  const w = watch(page, { expected: [409] });
  await mockApi(page, { scan: { status: 409, json: { ok: false, error: BUSY } } });
  await open(page);
  await page.getByRole("button", { name: "Scan founder signals" }).click();
  await expect(page.getByText(`✕ Scanning founders failed — ${BUSY}`)).toBeVisible();
  await expect(page.getByText("Scan failed", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Scan founder signals" })).toBeEnabled();
  w.expectClean();
});

test("company research: Research company, Research next 5 leads and Refresh research post the old bodies", async ({ page }) => {
  const w = watch(page);
  const { posted } = await mockApi(page);
  await open(page, "?view=research");
  const research = page.getByRole("button", { name: "Research company", exact: true });
  await expect(research).toHaveCount(4);
  for (const name of ["Research next 5 leads", QUEUE]) await expect(page.getByRole("button", { name })).toBeEnabled();

  await page.getByTestId("fr-company-card").filter({ hasText: "Quillstone AI" }).getByRole("button", { name: "Research company", exact: true }).click();
  await expect(page.getByText("5 page(s) retrieved · 9 proposal(s) — review before anything counts")).toBeVisible();
  const drawer = page.getByRole("dialog", { name: "Review — Quillstone AI" });
  await expect(drawer).toBeVisible(); // proposals are ready: the review opens
  expect(posted.filter((p) => p.path === "research").map((p) => p.body)).toEqual([{ key: "dom:quillstone.example" }]);

  await drawer.getByRole("button", { name: "Refresh research" }).click();
  await expect(page.getByText("5 page(s) · 0 new proposal(s)")).toBeVisible();
  await expect.poll(() => posted.filter((p) => p.path === "research").map((p) => p.body)).toEqual([{ key: "dom:quillstone.example" }, { key: "dom:quillstone.example", refresh: true }]);
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);

  await page.getByRole("button", { name: "Research next 5 leads" }).click();
  await expect(page.getByText("Quillstone AI: 9 proposals", { exact: true })).toBeVisible();
  await expect.poll(() => posted.filter((p) => p.path === "research").map((p) => p.body)).toEqual([
    { key: "dom:quillstone.example" },
    { key: "dom:quillstone.example", refresh: true },
    {},
  ]);
  w.expectClean();
});

test("per-person and company actions post the old bodies", async ({ page }) => {
  const w = watch(page);
  const { posted } = await mockApi(page);
  const radar = load("founder_radar.json");
  const oskar = radar.people.find((p: J) => p.name === "Oskar Lindqvist");
  await open(page, "?view=research&seg=insuf");
  const card = page.getByTestId("fr-person-card").filter({ hasText: "Oskar Lindqvist" });
  await card.getByRole("button", { name: "Add to Watchlist" }).click();
  await expect.poll(() => posted.find((p) => p.path === "action")?.body).toEqual({ id: oskar.id, action: "watch" });
  await expect(page.getByText("Recorded: watch")).toBeVisible();

  await card.getByRole("button", { name: "Dismiss" }).click();
  const d = page.getByRole("dialog", { name: "Dismiss" });
  await d.getByLabel("Why dismiss? (kept on record)").fill("not a founder");
  await d.getByRole("button", { name: "OK" }).click();
  await expect.poll(() => posted.filter((p) => p.path === "action")[1]?.body).toEqual({ id: oskar.id, action: "dismiss", note: "not a founder" });

  // evidence drawer: Boardy brief, judgment and promotion (Oskar has no promotion block)
  await card.getByRole("button", { name: "View evidence" }).click();
  const drawer = page.getByRole("dialog", { name: "Oskar Lindqvist" });
  await drawer.getByRole("button", { name: "Prepare Boardy request" }).click();
  await expect(drawer.getByTestId("fr-brief")).toContainText("No Boardy API — paste this into Boardy yourself.");
  expect(posted.find((p) => p.path === "boardy_brief")?.body).toEqual({ id: oskar.id });
  await drawer.getByLabel("Your judgment").fill("Strong builder, no founder signal yet");
  await drawer.getByRole("button", { name: "Save judgment" }).click();
  await expect.poll(() => posted.find((p) => p.path === "person_save")?.body).toEqual({ id: oskar.id, human_judgment: "Strong builder, no founder signal yet" });
  await drawer.getByRole("button", { name: "Add to Network" }).click();
  const pm = page.getByRole("dialog", { name: "Add to Network — Oskar Lindqvist" });
  await pm.getByLabel("How do you know them?").fill("met at Kiel Ocean Hack");
  await pm.getByRole("button", { name: "Add to Network" }).click();
  await expect.poll(() => posted.find((p) => p.path === "promote")?.body).toMatchObject({ id: oskar.id, how: "met at Kiel Ocean Hack", stage: radar.network_states[0] });
  await expect(page.getByText("Now in Network — history preserved")).toBeVisible();
  await page.keyboard.press("Escape");

  // company queue: a sourced fact (explicit confirmation step)
  await tab(page, "Founder claims — unverified").click();
  const kelp = page.getByTestId("fr-company-card").filter({ hasText: "Kelpwise GmbH" });
  await kelp.getByRole("button", { name: "Add sourced company fact" }).click();
  const f = page.getByRole("dialog", { name: "Add sourced company fact" });
  await f.getByLabel(/Which fact\?/).selectOption("recent_activity");
  await f.getByLabel(/^Value/).fill("pre-seed round announced");
  await f.getByLabel(/Public source URL that states this fact/).fill("https://kelpwise.example/news");
  await f.getByLabel("Source label").fill("Kelpwise news");
  await f.getByLabel("Exact supported claim as the page states it").fill("Kelpwise today announced its pre-seed round.");
  await f.getByLabel(/Activity date/).fill("2026-11-04");
  await f.getByRole("button", { name: "OK" }).click();
  await expect(f).toContainText("Confirm sourced fact:");
  await f.getByRole("button", { name: "Confirm", exact: true }).click();
  await expect.poll(() => posted.find((p) => p.path === "company")?.body).toEqual({
    key: KELP,
    fact: {
      field: "recent_activity",
      value: "pre-seed round announced",
      url: "https://kelpwise.example/news",
      label: "Kelpwise news",
      claim: "Kelpwise today announced its pre-seed round.",
      confirm: true,
      activity_date: "2026-11-04",
    },
  });

  // the resumable company research queue: batches of 3 until nothing remains
  await page.getByRole("button", { name: QUEUE }).click();
  await expect(page.getByTestId("fr-rq-state")).toContainText("2 done · 0 remaining · 1 failed · skipped (no official domain): Grainline Labs · complete");
  await expect(page.getByTestId("fr-rq-state")).toContainText("failures: dom:quillstone.example: HTTP 404");
  await expect(page.getByText("Company research queue: 2 done", { exact: true })).toBeVisible();
  expect(posted.filter((p) => p.path === "research_queue").map((p) => p.body)).toEqual([{ batch: 3 }, { batch: 3 }]);
  w.expectClean();
});

test("diagnostics: source coverage + founder source health", async ({ page }) => {
  const w = watch(page);
  await mockApi(page);
  await open(page, "?view=diag");
  await expect(page.locator("#frCoverage")).toContainText("live discovery");
  await expect(page.locator("#frHealth")).toContainText("separate from company and event sources · no LinkedIn scraping, no automation, no cookies");
  await expect(page.getByTestId("fr-health")).toContainText("Europe-wide coverage — rotating batches of 6 cities per scan (registry 51 cities)");
  await expect(page.getByTestId("fr-health").getByText("REQUIRES CONFIGURATION").first()).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await zoom150(page);
  await expectNoHorizontalOverflow(page);
  w.expectClean();
});

test("diagnostics: no scan yet shows the server's note", async ({ page }) => {
  const w = watch(page);
  const radar = load("founder_radar.json");
  radar.health = { scan_time: "", totals: {}, sources: [], note: "No founder scan yet — press Scan founder signals." };
  await mockApi(page, { radar });
  await open(page, "?view=diag");
  await expect(page.locator("#frHealth")).toContainText("No founder scan yet — press Scan founder signals.");
  w.expectClean();
});

test("research queue at 150% zoom fits without horizontal scroll", async ({ page }) => {
  const w = watch(page);
  await mockApi(page);
  await zoom150(page);
  await open(page, "?view=research");
  await expect(page.getByTestId("fr-company-card").first()).toBeVisible();
  await expectNoHorizontalOverflow(page);
  w.expectClean();
});
