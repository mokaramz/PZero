/**
 * Validation (review 027a) — the old `validation.spec.ts` plus the Validation assertions of the old `focus.spec.ts`
 * (the five question tabs, one tabpanel), `navy.spec.ts` (grounded sparklines, reduced motion, phone width) and
 * `a-class-ui.spec.ts` (roles), ported to the new paths. The API is MOCKED with route interception, so no backend is
 * needed: only the frontend (`npm run dev` in frontend/, or PZ_BASE_URL). Every company, source and URL in
 * fixtures/validation/ is invented.
 *
 * The writes (review 027b): the old "record an outcome / a miss" and "import a benchmark" flows, plus a false positive,
 * a retraction, the Scout 00 handover mark (decision f: `{cycle, generated, sha}` of the packet shown, posted only after
 * the copy succeeded), the 400 / 409 refusals, and opening / cancelling every form without a write. Every POST path and
 * body is asserted exactly.
 *
 *   cd e2e && PZ_BASE_URL=http://localhost:5173 npx playwright test validation-mocked
 */
import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { expand, expectNoHorizontalOverflow, recordPosts, watch, zoom150 } from "./helpers";

const FIX = resolve(import.meta.dirname, "fixtures", "validation");
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type J = any;
const load = (n: string): J => JSON.parse(readFileSync(resolve(FIX, n), "utf8"));

const NEWS = "News & Learning arrives with its port";
const QUESTIONS = ["Are we early?", "Are we right?", "Which sources work?", "Where do we miss?", "What does it cost?"];
/** the old write endpoints and their 027b paths */
const WRITE_PATHS = /\/api\/(validation_(outcome|audit|retract|benchmark_import|scout_packet)|validation\/(outcome|audit|retract|benchmark_import))\b/;

/** The audit form's untouched fields (the old body sends all of them, whichever type). */
const AUDIT = {
  company: "",
  earliest_signal: "",
  earliest_signal_date: "",
  signal_source: "",
  should_have_found: "",
  why_missed: "source_not_covered",
  preventable: "unclear",
  improvement: "",
  causes: [],
  lesson: "",
  note: "",
};
const CSV = "Name,Date added\nKestrel Labs,2026-07-01\nFuture Co,2099-01-01\n";
const STALE = "the packet changed since it was prepared — prepare it again";

type Write = "outcome" | "audit" | "retract" | "benchmark_import" | "scout_packet";

/** Mock the two Validation reads and the five writes (the old success shapes; `refuse` answers a write with its
 *  refusal: 409 for the packet mark, 400 for the rest); anything else under /api answers 404 (the shell's not-ported
 *  reads are allowed by `watch`, any other 404 fails the test). Returns every API request (method + path + query), in
 *  order. */
async function mockApi(page: Page, opts: { validation?: J; refuse?: Partial<Record<Write, string>> } = {}) {
  const data = opts.validation ?? load("validation.json");
  const packet = load("scout_packet.json");
  const requested: Array<{ method: string; path: string }> = [];
  page.on("request", (r) => {
    if (!r.url().includes("/api/")) return;
    const u = new URL(r.url());
    requested.push({ method: r.method(), path: u.pathname + u.search });
  });
  await page.route(/\/api\//, (route) => route.fulfill({ status: 404, json: { ok: false, error: "not found" } }));
  await page.route(/\/api\/validation(\?.*)?$/, (route) => route.fulfill({ json: data }));
  await page.route(/\/api\/validation\/scout_packet(\?.*)?$/, (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as { cycle: string };
      const error = opts.refuse?.scout_packet;
      return error ? route.fulfill({ status: 409, json: { ok: false, error } }) : route.fulfill({ json: { ...packet, cycle: body.cycle || "all" } });
    }
    const cycle = new URL(route.request().url()).searchParams.get("cycle") ?? "";
    return route.fulfill({ json: { ...packet, cycle: cycle || "all" } });
  });
  await page.route(/\/api\/validation\/(outcome|audit|retract|benchmark_import)$/, (route) => {
    const name = new URL(route.request().url()).pathname.split("/").pop() as Write;
    const body = route.request().postDataJSON() as Record<string, unknown>;
    const error = opts.refuse?.[name];
    if (error) return route.fulfill({ status: 400, json: { ok: false, error } });
    if (name === "benchmark_import") return route.fulfill({ json: { ...load("benchmark_summary.json"), imported: !!body.confirm } });
    return route.fulfill({ json: { ok: true, entry: { id: "oc-0123456789", recorded_at: "2026-11-12T10:00:00", ...body } } });
  });
  return {
    requested,
    writes: () => requested.filter((r) => r.method !== "GET" || WRITE_PATHS.test(r.path)),
    /** the distinct Validation requests, in first-seen order (the app shell may re-read a query on focus) */
    reads: () => [...new Set(requested.filter((r) => r.path.startsWith("/api/validation")).map((r) => `${r.method} ${r.path}`))],
  };
}

const questions = (page: Page) => page.getByTestId("val-questions");
/** Validation answers one analytical question at a time. */
const question = (page: Page, q: string) => questions(page).getByRole("tab", { name: q }).click();

async function open(page: Page) {
  await page.goto("/validation");
  await expect(page.getByRole("heading", { name: "Validation & Learning", level: 1 })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("val-edge")).toBeVisible();
}

/** navigator.clipboard as a recorder (`window.__copied`), so a copy never depends on the browser's permissions;
 *  `failFirst` makes the first copy reject, as a blocked clipboard does. */
async function stubClipboard(page: Page, { failFirst = false } = {}) {
  await page.addInitScript((fail: boolean) => {
    const copied: string[] = [];
    let refuse = fail;
    (window as unknown as { __copied: string[] }).__copied = copied;
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: async (text: string) => {
          if (refuse) {
            refuse = false;
            throw new DOMException("Write permission denied.", "NotAllowedError");
          }
          copied.push(text);
        },
      },
    });
  }, failFirst);
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
});

/* ------------------------------------------------------------------ validation.spec.ts: the overview */
test("validation: edge, sources, calibration, honest 'collecting' states", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  await open(page);
  await expect(page.getByTestId("val-edge")).toContainText("exceptional recall"); // "Are we early?" first
  await expect(page.getByTestId("val-edge")).toContainText("collecting (3/5)");
  await expand(page, "val-measurement-d");
  await expect(page.getByTestId("val-measure")).toHaveCount(6); // known / collecting / partly known, per metric
  await expect(page.getByTestId("val-measurement")).toContainText("PARTLY KNOWN");
  await expect(page.getByTestId("val-data-issues")).toContainText("Vessra Robotics");
  await question(page, "Which sources work?");
  await expect(page.getByTestId("val-sources").locator("tbody tr")).toHaveCount(12);
  await expect(page.getByTestId("val-sources").locator("tbody tr").first()).toContainText("Northgate University spin-outs");
  await question(page, "Are we right?");
  await expect(page.getByTestId("val-calibration")).toContainText("your triage decisions");
  await expect(page.getByTestId("val-calibration")).toContainText("Smooth Operator calibration — human vs machine"); // a-class-ui: roles
  await expect(page.getByTestId("val-footer")).toContainText("Validation spends no model money");
  expect(api.reads()).toEqual(["GET /api/validation"]);
  w.expectClean();
});

test("an empty data folder is honestly NOT YET MEASURABLE", async ({ page }) => {
  const w = watch(page);
  await mockApi(page, { validation: load("validation_empty.json") });
  await open(page);
  await expand(page, "val-measurement-d");
  await expect(page.getByTestId("val-measure")).toHaveCount(6);
  await expect(page.getByTestId("val-measurement")).toContainText("NOT YET MEASURABLE");
  await expect(page.getByTestId("val-trends")).toHaveCount(0); // fewer than 3 snapshots: no line
  await question(page, "Are we right?");
  await expect(page.getByTestId("val-outcomes")).toContainText("No outcomes recorded yet.");
  w.expectClean();
});

/* ------------------------------------------------------------------ focus.spec.ts: one question at a time */
test("secondary areas as tabs: one area mounted at a time", async ({ page }) => {
  const w = watch(page);
  await mockApi(page);
  await open(page);
  const q = questions(page);
  await expect(q.getByRole("tab")).toHaveText(QUESTIONS);
  await expect(q.getByRole("tab", { name: "Are we early?" })).toHaveAttribute("aria-selected", "true");
  await expect(q.getByRole("tabpanel")).toHaveCount(1);
  await question(page, "Where do we miss?");
  await expect(q.getByRole("tab", { name: "Where do we miss?" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("val-misses")).toBeVisible();
  await expect(page.getByTestId("val-edge")).toHaveCount(0);
  await expect(q.getByRole("tabpanel")).toHaveCount(1);
  await expect(page).toHaveURL(/\/validation$/); // the question is local state, as before
  w.expectClean();
});

/* ------------------------------------------------------------------ navy.spec.ts: grounded sparklines */
test("grounded sparklines: only with 3+ real snapshots, and labelled as direction only", async ({ page }) => {
  const w = watch(page);
  await mockApi(page);
  await open(page);
  const t = page.getByTestId("val-trends");
  await expect(t).toContainText("not a significance claim");
  await expect(t).toHaveAttribute("data-signature", "data");
  const imgs = await t.getByRole("img").all();
  expect(imgs).toHaveLength(3); // pre-funding share has only 2 numbers: no line
  for (const img of imgs) expect(((await img.getAttribute("aria-label")) ?? "").split(",").length).toBeGreaterThanOrEqual(3);
  await expect(t.getByRole("img").first()).toHaveAttribute("aria-label", "first seen this month: 9, 10, 12, 13, 14");
  w.expectClean();
});

test("reduced motion: the sparklines are final at once", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page);
  await open(page);
  const lines = await page.locator("path.pz-trace").all();
  expect(lines.length).toBeGreaterThanOrEqual(3);
  for (const l of lines) expect(Number(await l.evaluate((el) => getComputedStyle(el).strokeDashoffset.replace("px", "")))).toBe(0);
  await question(page, "Are we right?");
  const long = await page.evaluate(() => document.getAnimations().filter((a) => Number(a.effect?.getComputedTiming().endTime ?? 0) > 50).length);
  expect(long).toBe(0);
});

/* ------------------------------------------------------------------ validation.spec.ts: the writes (027b) */
test("validation: record an outcome and a miss — exact POSTs, toasts and a refresh", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  const posted = recordPosts(page);
  await open(page);

  await page.getByTestId("record-outcome").click();
  await expect(page.getByTestId("outcome-save")).toBeDisabled();
  await page.getByTestId("outcome-company").fill("Kestrel Labs");
  await page.getByTestId("outcome-date").fill("2026-09-01");
  await expect(page.getByTestId("outcome-save")).toBeDisabled(); // a round needs its evidence URL
  await page.getByTestId("outcome-url").fill("https://news.example/kestrel-seed");
  await page.getByTestId("outcome-save").click();
  await expect(page.getByText("Outcome recorded")).toBeVisible();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await page.getByTestId("more-actions").locator("summary").click();
  await page.getByTestId("record-miss").click();
  await page.getByTestId("audit-company").fill("Tarnwick Robotics");
  await page.getByTestId("audit-save").click();
  await expect(page.getByText("Audit recorded")).toBeVisible();

  expect(posted).toEqual([
    {
      path: "/api/validation/outcome",
      body: { company: "Kestrel Labs", kind: "institutional_round", event_date: "2026-09-01", evidence_url: "https://news.example/kestrel-seed", benchmark_system: "", note: "" },
    },
    { path: "/api/validation/audit", body: { ...AUDIT, company: "Tarnwick Robotics", type: "miss" } },
  ]);
  await expect.poll(() => api.requested.filter((r) => r.method === "GET" && r.path === "/api/validation").length).toBeGreaterThanOrEqual(3); // refreshed after each write
  w.expectClean();
});

test("validation: a false positive, a refused one (400) and a retraction", async ({ page }) => {
  const w = watch(page, { expected: [400] });
  await mockApi(page, { refuse: { audit: "company required" } });
  const posted = recordPosts(page);
  const prompts: string[] = [];
  const answers = ["short", "wrong company recorded"];
  page.on("dialog", (d) => {
    prompts.push(d.message());
    void d.accept(answers.shift());
  });
  await open(page);

  await question(page, "Where do we miss?");
  await page.getByTestId("record-fp").click();
  await page.getByTestId("audit-company").fill("Graniteleaf Labs");
  await expect(page.getByTestId("audit-save")).toBeDisabled(); // a false positive needs a cause
  await page.getByRole("dialog").getByRole("checkbox", { name: "weak source", exact: true }).check();
  await page.getByTestId("audit-save").click();
  await expect(page.getByText("✕ Recording the audit failed — company required")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();

  await question(page, "Are we right?");
  const retract = page.getByTestId("val-outcome").filter({ hasText: "Aurelith Systems" }).getByRole("button", { name: "Retract" });
  await retract.click(); // too short: nothing is sent
  await retract.click();
  await expect(page.getByText("Retracted (kept in history)")).toBeVisible();
  expect(prompts).toEqual(["Why retract this outcome? (kept in history)", "Why retract this outcome? (kept in history)"]);

  expect(posted).toEqual([
    { path: "/api/validation/audit", body: { ...AUDIT, company: "Graniteleaf Labs", causes: ["weak_source"], type: "false_positive" } },
    { path: "/api/validation/retract", body: { id: "oc-3e4f5a6b7c", reason: "wrong company recorded" } },
  ]);
  w.expectClean();
});

test("validation: import a benchmark export (preview → import)", async ({ page }) => {
  const w = watch(page);
  await mockApi(page);
  const posted = recordPosts(page);
  await open(page);
  await question(page, "Which sources work?");
  const panel = page.getByTestId("val-benchmarks");
  await expect(panel).toContainText("No private database access is assumed");
  await panel.getByText("Import a benchmark export").click();
  await panel.getByPlaceholder("Dealroom").fill("Dealroom");
  await panel.locator("textarea").fill(CSV);
  await panel.getByRole("button", { name: "Preview" }).click();
  await expect(panel).toContainText("2 rows · 1 usable · 1 skipped");
  await panel.getByRole("button", { name: "Import 1 dates" }).click();
  await expect(page.getByText("1 benchmark date(s) imported")).toBeVisible();
  await expect(panel.getByRole("button", { name: /^Import \d+ dates$/ })).toHaveCount(0);
  expect(posted).toEqual([
    { path: "/api/validation/benchmark_import", body: { system: "Dealroom", csv: CSV } },
    { path: "/api/validation/benchmark_import", body: { system: "Dealroom", csv: CSV, confirm: true } },
  ]);
  w.expectClean();
});

test("validation: copy & log the Scout 00 handover — the mark carries the packet's Generated time and sha", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  const posted = recordPosts(page);
  await stubClipboard(page);
  await open(page);
  await question(page, "Where do we miss?");
  await page.getByTestId("scout-packet").click();
  await expect(page.getByTestId("scout-packet-text")).toContainText("PROJECT ZERO → CHIEF SCOUT 00");
  await expect(page.getByTestId("scout-packet-text")).toContainText("Orbelle Health"); // misses are fed back to the scouts
  await expect(page.getByTestId("scout-packet-text")).toContainText(`- not available: ${NEWS}`);
  await expect(page.getByTestId("scout-packet-deferred")).toContainText(NEWS);
  expect(posted).toEqual([]); // preparing is a read
  await page.getByTestId("scout-packet-copy").click();
  await expect(page.getByText("Packet copied — paste it into Chief Scout 00")).toBeVisible();
  await expect(page.getByText("✓ Preparing the Scout 00 packet — done")).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { __copied: string[] }).__copied)).toEqual([load("scout_packet.json").text]);
  expect(posted).toEqual([{ path: "/api/validation/scout_packet", body: { cycle: "c-2026-10-16", generated: "2026-11-12T09:15:00", sha: "5d1c0e9a7b3f2468" } }]);
  expect(api.reads()).toContain("GET /api/validation/scout_packet?cycle=c-2026-10-16");
  w.expectClean();
});

test("validation: a stale packet (409) is shown; a blocked clipboard logs nothing", async ({ page }) => {
  const w = watch(page, { expected: [409] });
  await mockApi(page, { refuse: { scout_packet: STALE } });
  const posted = recordPosts(page);
  await stubClipboard(page, { failFirst: true });
  await open(page);
  await question(page, "Where do we miss?");
  await page.getByTestId("scout-packet").click();
  await expect(page.getByTestId("scout-packet-text")).toBeVisible();
  await page.getByTestId("scout-packet-copy").click(); // the clipboard refuses
  await expect(page.getByText("Clipboard blocked — select the text and copy manually")).toBeVisible();
  await page.waitForTimeout(300);
  expect(posted).toEqual([]);
  await page.getByTestId("scout-packet-copy").click(); // copied, but the data changed since
  await expect(page.getByText(`✕ Preparing the Scout 00 packet failed — ${STALE}`)).toBeVisible();
  expect(posted).toEqual([{ path: "/api/validation/scout_packet", body: { cycle: "c-2026-10-16", generated: "2026-11-12T09:15:00", sha: "5d1c0e9a7b3f2468" } }]);
  w.expectClean();
});

test("validation: opening and cancelling every form writes nothing", async ({ page }) => {
  const w = watch(page);
  const api = await mockApi(page);
  page.on("dialog", (d) => void d.dismiss());
  await open(page);
  await page.getByTestId("record-outcome").click();
  await page.getByTestId("outcome-company").fill("Kestrel Labs");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByTestId("more-actions").locator("summary").click();
  await page.getByTestId("record-miss").click();
  await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
  await question(page, "Are we right?");
  await page.getByRole("button", { name: "Retract" }).first().click(); // the prompt is dismissed
  await question(page, "Where do we miss?");
  await page.getByTestId("record-fp").click();
  await page.keyboard.press("Escape");
  await question(page, "What does it cost?");
  await expect(page.getByTestId("val-native-bridge")).toContainText("Native search bridge — production pilot");
  await expect(page.getByTestId("val-native-bridge-deferred")).toContainText("Scout search bridge");
  await page.waitForTimeout(300);
  expect(api.writes()).toEqual([]);
  w.expectClean();
});

/* ------------------------------------------------------------------ layout: 150 %, 1366, 1920 and the phone */
async function everyQuestionFits(page: Page) {
  await expectNoHorizontalOverflow(page);
  await expand(page, "val-measurement-d");
  await expectNoHorizontalOverflow(page);
  for (const q of QUESTIONS) {
    await question(page, q);
    await expect(questions(page).getByRole("tab", { name: q })).toHaveAttribute("aria-selected", "true");
    await expectNoHorizontalOverflow(page);
  }
}

test("validation fits 150% zoom", async ({ page }) => {
  await zoom150(page);
  await mockApi(page);
  await open(page);
  await everyQuestionFits(page);
});

for (const [w, h] of [
  [1366, 768],
  [1920, 1080],
]) {
  test(`validation fits ${w}px`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await mockApi(page);
    await open(page);
    await everyQuestionFits(page);
  });
}

test("validation stays inside a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await open(page);
  await everyQuestionFits(page);
  // the measurement rows stack on a phone (badge above the text)
  const row = page.getByTestId("val-measure").first();
  const cols = await row.evaluate((el) => getComputedStyle(el).gridTemplateColumns.split(" ").length);
  expect(cols).toBe(1);
  // the forms fit too
  await page.getByTestId("record-outcome").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.keyboard.press("Escape");
  await question(page, "Where do we miss?");
  await page.getByTestId("record-fp").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expectNoHorizontalOverflow(page);
});
