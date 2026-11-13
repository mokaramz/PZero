/**
 * Machine triage writes on the Deal Flow page (review 035a) — the panel's Accept / Override, a KEEP opening the existing
 * Keep & score form, and "Accept obvious REJECTs…" with its preview and the old confirm dialog — with the API MOCKED by
 * route interception, so no backend is needed: only the frontend (`npm run dev` in frontend/, or PZ_BASE_URL). Every
 * company in fixtures/triage/ is invented (byte-identical copies of `frontend/src/features/deal-flow/test/triage/*.json`).
 *
 * Covered: an accept posts `{id, verdict, mode, expected_status}` only on the click, toasts and leaves the list; an
 * override posts the picked verdict; Accept KEEP opens Keep & score and writes no status; a 409 is the error toast saying
 * to reload; the batch previews, asks "Reject N", applies only on the confirm and toasts "Rejected N"; Cancel applies
 * nothing; the analysis batches stay deferred; no horizontal overflow at 1366, 1920, 390 and 150 %.
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test triage-mocked
 */
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expectNoHorizontalOverflow, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures/triage");
const SCAN = resolve(import.meta.dirname, "fixtures/scan");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (dir: string, n: string): J => JSON.parse(readFileSync(resolve(dir, n), "utf8"));
const answers = load(FIX, "answers.json");

const DECIDE = "/api/deal-flow/triage/decide";
const BATCH = "/api/deal-flow/triage/batch_reject";
const CATCHUP = { running: false, queue: [], current: null, done: [], enabled: true };
const ladder = (...steps: number[]) => steps.map((p) => [`step ${p}`, p]);
/** The Conviction scoring tables the Keep form reads (invented). */
const META = {
  archetypes: [{ id: 1, name: "Vertical AI agent" }],
  ladders: { founder: ladder(0, 10, 20), venture_scale: ladder(0, 10, 20), why_now: ladder(0, 5, 15), taste: ladder(0, 5, 15), insight: ladder(0, 5, 10) },
  earliness: { unknown: "Unknown", pre_company: "Pre-company" },
  timing: { unknown: "Unknown", raising_now: "Raising now" },
  conflict: { none: "None", unclear: "Unclear" },
  penalties: { consumer: "Consumer (−20)" },
  tiers: { announcement: "Announcement — public news" },
  portfolio: [],
};
const STORED: Record<string, string> = { rejected: "rejected", watch: "watch", research: "reviewing" };

/**
 * Mock Deal Flow's reads and the two triage writes. The inbox keeps what a write applied, so the refetch shows it.
 * `decide` names the answer of every decide (a `status` of its own for the 409); `batch` the preview and the applied
 * answer. Anything else under /api is a 404 (the shell's not-ported reads are allowed by `watch`).
 */
async function mockApi(page: Page, { decide = "accept_reject", decideStatus = 200, preview = "preview", applied = "applied" } = {}) {
  const requested: Array<{ method: string; path: string; body: J }> = [];
  page.on("request", (r) => {
    if (!r.url().includes("/api/")) return;
    let body: J = null;
    try {
      body = r.postDataJSON();
    } catch {
      body = null;
    }
    requested.push({ method: r.method(), path: new URL(r.url()).pathname, body });
  });
  const db = load(FIX, "inbox.json");
  const store = (id: string, d: string) => Object.assign(db.candidates.find((c: J) => c.id === id), { decision: d, pz_status: STORED[d] });
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/deal-flow\/inbox(\?.*)?$/, (route) => route.fulfill({ json: db }));
  await page.route(/\/api\/deal-flow\/triage(\?.*)?$/, (route) => route.fulfill({ json: load(FIX, "triage.json") }));
  await page.route(/\/api\/deal-flow\/find_status(\?.*)?$/, (route) => route.fulfill({ json: load(SCAN, "find_status.json").idle }));
  await page.route(/\/api\/catchup(\?.*)?$/, (route) => route.fulfill({ json: CATCHUP }));
  await page.route(/\/api\/conviction\/meta(\?.*)?$/, (route) => route.fulfill({ json: META }));
  await page.route(/\/api\/deal-flow\/triage\/decide$/, (route) => {
    const body = route.request().postDataJSON();
    const a = answers[decide];
    if (decideStatus === 200 && a.inbox_decision) store(body.id, a.inbox_decision);
    return route.fulfill({ status: decideStatus, json: a });
  });
  await page.route(/\/api\/deal-flow\/triage\/batch_reject$/, (route) => {
    const body = route.request().postDataJSON();
    if (body.confirm) for (const id of body.ids) store(id, "rejected");
    return route.fulfill({ json: answers[body.confirm ? applied : preview] });
  });
  return { requested, posts: () => requested.filter((r) => r.method === "POST") };
}

const rowIds = (page: Page) => page.getByTestId("cand-row").evaluateAll((rs) => rs.map((r) => r.getAttribute("data-id")));

/** The Machine triage view, with `id` selected (the list starts with the KEEP). */
async function openTriage(page: Page, id?: string) {
  await page.goto("/deal-flow?filter=triage");
  await expect(page.getByTestId("cand-row").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("triage-bar")).toBeVisible();
  // KEEP, RESEARCH, WATCH, then the REJECTs by confidence (t-0205 has none)
  await expect.poll(() => rowIds(page)).toEqual(["t-0201", "t-0202", "t-0203", "t-0204", "t-0206", "t-0205"]);
  if (id) await page.locator(`[data-testid="cand-row"][data-id="${id}"]`).click();
  const name = load(FIX, "inbox.json").candidates.find((c: J) => c.id === (id ?? "t-0201")).name;
  await expect(page.getByTestId("cand-detail").getByRole("heading", { level: 2 })).toHaveText(name);
  return page.getByTestId("triage-panel");
}

test.describe("Machine triage — mocked API", () => {
  test("Accept REJECT: nothing before the click, then the post, the toast and the row leaves the list", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    const panel = await openTriage(page, "t-0204");
    await expect(panel.getByTestId("triage-accept")).toHaveText("Accept REJECT");
    await expect(panel.getByTestId("triage-override")).toBeDisabled();
    await page.waitForTimeout(500);
    expect(api.posts()).toEqual([]);
    await panel.getByTestId("triage-accept").click();
    await expect(page.getByText("Accepted REJECT")).toBeVisible();
    expect(api.posts()).toEqual([{ method: "POST", path: DECIDE, body: { id: "t-0204", verdict: "REJECT", mode: "accept", expected_status: "new" } }]);
    await expect(page.locator('[data-testid="cand-row"][data-id="t-0204"]')).toHaveCount(0);
    w.expectClean();
  });

  test("Override posts the verdict picked in the select", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page, { decide: "override_watch" });
    const panel = await openTriage(page);
    await panel.getByLabel("Override verdict").selectOption("WATCH");
    await panel.getByTestId("triage-override").click();
    await expect(page.getByText("Overrode to WATCH")).toBeVisible();
    expect(api.posts()).toEqual([{ method: "POST", path: DECIDE, body: { id: "t-0201", verdict: "WATCH", mode: "override", expected_status: "new" } }]);
    await expect(page.locator('[data-testid="cand-row"][data-id="t-0201"]')).toHaveCount(0);
    w.expectClean();
  });

  test("Accept KEEP — score it opens the existing Keep & score form and writes no status", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page, { decide: "accept_keep" });
    const panel = await openTriage(page);
    await panel.getByTestId("triage-accept").click();
    const dlg = page.getByRole("dialog", { name: "Keep & score: Corvane Thermal" });
    await expect(dlg).toBeVisible();
    await expect(dlg.getByTestId("livescore")).toBeVisible();
    await expect(dlg.locator('[name="company"]')).toHaveValue("Corvane Thermal");
    expect(api.posts()).toEqual([{ method: "POST", path: DECIDE, body: { id: "t-0201", verdict: "KEEP", mode: "accept", expected_status: "new" } }]);
    await expect(page.locator('[data-testid="cand-row"][data-id="t-0201"]')).toHaveCount(1);
    w.expectClean();
  });

  test("a 409 is the error toast saying to reload; nothing opens", async ({ page }) => {
    const w = watch(page, { expected: [409] });
    const api = await mockApi(page, { decide: "conflict", decideStatus: 409 });
    const panel = await openTriage(page);
    await panel.getByTestId("triage-accept").click();
    await expect(page.getByText("✕ Saving your triage decision failed — the candidate changed meanwhile; reload and decide again")).toBeVisible();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    expect(api.posts()).toHaveLength(1);
    w.expectClean();
  });

  test("Accept obvious REJECTs…: the preview, the old dialog with “Reject N”, then the confirm and the toast", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await openTriage(page);
    await page.getByTestId("triage-batch").click();
    const dlg = page.getByRole("dialog", { name: "Batch-accept obvious REJECTs" });
    await expect(dlg).toBeVisible();
    await expect(dlg).toContainText("Accept 2 machine REJECT proposals where both models agreed on a supported reason (or the record is junk)?");
    await expect(dlg.getByTestId("confirm-ok")).toHaveText("Reject 2");
    expect(api.posts()).toEqual([{ method: "POST", path: BATCH, body: { ids: ["t-0204", "t-0205"] } }]);
    await dlg.getByTestId("confirm-ok").click();
    await expect(page.getByText("Rejected 2")).toBeVisible();
    expect(api.posts()[1]).toEqual({ method: "POST", path: BATCH, body: { ids: ["t-0204", "t-0205"], confirm: true } });
    await expect.poll(() => rowIds(page)).toEqual(["t-0201", "t-0202", "t-0203", "t-0206"]);
    w.expectClean();
  });

  test("Cancel applies nothing; the analysis batches stay deferred and silent", async ({ page }) => {
    const w = watch(page);
    const api = await mockApi(page);
    await openTriage(page);
    await page.getByTestId("triage-batch").click();
    const dlg = page.getByRole("dialog", { name: "Batch-accept obvious REJECTs" });
    await dlg.getByRole("button", { name: "Cancel" }).click();
    await expect(dlg).toHaveCount(0);
    for (const id of ["triage-analyst", "triage-redteam"]) {
      const b = page.getByTestId(id);
      await expect(b).toHaveAttribute("aria-disabled", "true");
      await expect(b).toHaveAttribute("title", /arrives with the analysis port/);
      await b.click({ force: true });
    }
    await page.waitForTimeout(500);
    expect(api.posts()).toEqual([{ method: "POST", path: BATCH, body: { ids: ["t-0204", "t-0205"] } }]);
    w.expectClean();
  });

  /** The triage view with a REJECT's panel, then the batch dialog open. */
  async function triageAndDialog(page: Page) {
    await openTriage(page, "t-0204");
    await expectNoHorizontalOverflow(page);
    await page.getByTestId("triage-batch").click();
    await expect(page.getByRole("dialog", { name: "Batch-accept obvious REJECTs" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }

  for (const [name, size] of [
    ["1366", { width: 1366, height: 768 }],
    ["1920", { width: 1920, height: 1080 }],
    ["390 (phone)", { width: 390, height: 844 }],
  ] as const) {
    test(`no horizontal overflow at ${name}: the triage panel and the batch dialog`, async ({ page }) => {
      const w = watch(page);
      await mockApi(page);
      await page.setViewportSize(size);
      await triageAndDialog(page);
      w.expectClean();
    });
  }

  test("no horizontal overflow at 150 % zoom", async ({ page }) => {
    const w = watch(page);
    await mockApi(page);
    await zoom150(page);
    await triageAndDialog(page);
    w.expectClean();
  });
});
