/**
 * System health (review 032a) — the new app on a preview database (the real snapshot in a scratch schema). The page
 * renders from the two real reads (`GET /api/system_health`, `/api/system_health_overview`) and matches them: the
 * verdict and sentence as sent, the jobs from the imported snapshot, the deferred reasons where their data was, the
 * retired Scout parts gone. The old `health.spec.ts` checks are ported (the plain-words verdict, the drill-down, the
 * phone layout); its backup / restore-test clicks and its check of a model key's value are not (032b; dropped).
 * Revision 2: the headline and every job item's guidance say the runner is not ported, no text promises a retry, a
 * catch-up or an immediate run, and "Run overdue now" is disabled with its visible reason.
 * Review 032c: each check follows the payload's runner. With the DEFERRED lock (the 032a server) the checks above
 * stand; with the REAL lock, "Run overdue now" is enabled (never clicked here), the snapshot line is gone, the runner
 * line shows the lock, every job with `ported: false` says "not ported yet", and no text near those jobs promises a run.
 * This spec only READS: every request it sees must be a GET. health-mocked.spec.ts covers every branch on invented
 * payloads.
 */
import { expect, test, type Locator, type Page } from "@playwright/test";

import { expand, expectNoHorizontalOverflow, watch as watchErrors, zoom150 } from "./helpers";

type Issue = { level: string; what: string; do: string; group?: string };
type Health = {
  status?: { key: string; label: string; sentence: string };
  issues: Issue[];
  overdue: number;
  jobs: Array<{ id: string; label: string; overdue?: boolean; ported?: boolean; availability?: string }>;
  build?: unknown;
  selfcheck?: unknown;
  watch: { failing_checks: unknown };
  job_runner?: { lock: unknown };
  [k: string]: unknown;
};
type Overview = { backups: unknown; integrity: unknown; releases: unknown; [k: string]: unknown };

const RUNNER = "The background-job runner is not ported yet.";
const SNAPSHOT = "Background jobs are not ported yet: job state and history are the imported snapshot.";
const RUNNER_NOT_PORTED = /runner is not ported|until the runner is ported/;
const FORBIDDEN = ["retries automatically", "kept for retry", "run again when due", "starts them immediately", "next background trigger", "let catch-up run it", "asleep"];
const DIAGNOSTICS = ["health-glance", "health-sources", "health-jobs", "health-ai", "health-news", "health-hardening", "health-build-d"];

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

const read = async <T>(page: Page, path: string): Promise<T> => (await (await page.request.get(`/api/${path}`)).json()) as T;
const deferredReason = (x: unknown): string | null =>
  x && typeof x === "object" && !Array.isArray(x) && Object.keys(x).length === 1 && typeof (x as { deferred?: unknown }).deferred === "string" ? (x as { deferred: string }).deferred : null;

/** The 032c runner is live when its lock is a real object (the page decides the same way). */
const runnerLive = (h: Health) => !!h.job_runner && h.job_runner.lock != null && !deferredReason(h.job_runner.lock);
const isPorted = (j: Health["jobs"][number]) => j.ported !== false && j.availability !== "not ported yet";
const unported = (h: Health) => h.jobs.filter((j) => !isPorted(j));
const portedOverdue = (h: Health) => h.jobs.filter((j) => j.overdue && isPorted(j)).map((j) => j.id);

async function open(page: Page) {
  const ov = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/system_health_overview" && r.request().method() === "GET", { timeout: 90_000 });
  await page.goto("/health");
  await expect(page.getByRole("heading", { level: 1, name: "System health" })).toBeVisible({ timeout: 60_000 });
  await ov;
  await expect(page.getByTestId("health-verdict")).toContainText(/Operational|Operational with limitations|Action required|Degraded|Status unknown/, { timeout: 30_000 });
}

async function expectNoPromise(page: Page) {
  const t = await page.locator("body").innerText();
  for (const p of FORBIDDEN) expect(t, p).not.toContain(p);
  expect(t).not.toMatch(/runs again automatically|kept for the next run|catch up when the app opens/);
}

async function expectDeferred(page: Page, btn: Locator, reason: string) {
  await expect(btn).toBeVisible();
  await expect(btn).toHaveAttribute("aria-disabled", "true");
  await expect(btn).toHaveAttribute("data-deferred", "");
  const note = page.locator(`[id="${await btn.getAttribute("aria-describedby")}"]`);
  await expect(note).toBeVisible();
  await expect(note).toHaveText(reason);
  await expect(btn).toHaveAccessibleDescription(reason);
  const requests: string[] = [];
  const on = (r: { url: () => string }) => r.url().includes("/api/") && requests.push(r.url());
  page.on("request", on);
  await btn.click({ force: true });
  await btn.focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Space");
  await page.waitForTimeout(400);
  page.off("request", on);
  await expect(page).toHaveURL((u) => u.pathname === "/health");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(requests).toEqual([]);
}

test.describe("System health — preview database", () => {
  test("answers 'is Project Zero healthy?' in plain words, as the server sent it", async ({ page }) => {
    const w = watch(page);
    const h = await read<Health>(page, "system_health");
    await open(page);
    if (h.status) {
      await expect(page.getByTestId("health-verdict")).toContainText(h.status.label);
      await expect(page.getByTestId("health-action")).toHaveText(h.status.sentence.replace(/\bMohamed\b/g, "Smooth Operator").replace(/\bOmar\b/g, "Manager"));
    }
    // "Action required" only when the Needs-your-action group is not empty — and the reverse
    const needEmpty = (await page.getByTestId("issues-need").getByText("Nothing needs you right now.").count()) > 0;
    if (needEmpty) await expect(page.getByTestId("health-verdict")).not.toContainText("Action required");
    else await expect(page.getByTestId("health-verdict")).toContainText(/Action required|Degraded/);
    await expect(page.getByTestId("health-issue")).toHaveCount(h.issues.length);
    await expect(page.getByTestId("health-kpi")).toHaveCount(5);
    await expand(page, "health-sources");
    await expect(page.getByTestId("health-sources")).toContainText("Health is about retrieval, not volume");
    await expand(page, "health-jobs");
    await expect(page.getByTestId("health-jobs")).toContainText("Deal Flow scan");
    await expect(page.getByTestId("health-job")).toHaveCount(h.jobs.length);
    await expand(page, "health-ai");
    await expect(page.getByTestId("health-ai")).toContainText("Caps stop paid calls automatically");
    await expect(page.getByTestId("health-jobs")).not.toHaveAttribute("open", ""); // one open at a time
    for (const id of DIAGNOSTICS) await expect(page.getByTestId(id)).toBeAttached();
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });

  test("the payloads: the retired keys are gone; the deferred keys are reasons, shown on the page", async ({ page }) => {
    const w = watch(page);
    const h = await read<Health>(page, "system_health");
    const o = await read<Overview>(page, "system_health_overview");
    for (const k of ["search_bridge", "scout00", "native"]) expect(o, k).not.toHaveProperty(k);
    expect((o.pipeline as Record<string, unknown>) ?? {}).not.toHaveProperty("intake");
    const srcs = (h.sources as { sources: Array<{ repair?: Record<string, unknown> }> }).sources;
    for (const s of srcs) expect(s.repair ?? {}).not.toHaveProperty("bridge_job");
    const live = runnerLive(h);
    for (const [k, v] of Object.entries({
      selfcheck: h.selfcheck,
      build: h.build,
      source_discovery: h.source_discovery,
      "watch.failing_checks": h.watch.failing_checks,
      ...(live ? {} : { "job_runner.lock": h.job_runner?.lock }),
    }))
      expect(deferredReason(v), k).toBeTruthy();
    if (live) expect(typeof (h.job_runner!.lock as { held?: unknown }).held, "job_runner.lock.held").toBe("boolean");
    for (const k of ["backups", "integrity", "releases"] as const) expect(deferredReason(o[k]), k).toBeTruthy();
    await open(page);
    await expect(page.getByTestId("health-backups-reason")).toHaveText(deferredReason(o.backups)!);
    await expect(page.getByTestId("health-integrity-reason")).toHaveText(deferredReason(o.integrity)!);
    await expect(page.getByTestId("health-releases-reason")).toHaveText(deferredReason(o.releases)!);
    await expect(page.getByTestId("health-release-reason")).toHaveText(deferredReason(o.releases)!);
    await expand(page, "health-build-d");
    await expect(page.getByTestId("health-build")).toHaveText(`Running build: ${deferredReason(h.build)}`);
    await expect(page.getByTestId("health-selfcheck")).toHaveText(`Startup self-check: ${deferredReason(h.selfcheck)}`);
    await expect(page.getByTestId("health-validation-data")).toContainText(deferredReason(h.watch.failing_checks)!);
    await expand(page, "health-jobs");
    if (live) {
      await expect(page.getByTestId("health-job-runner")).toContainText(/^Job runner: (idle|busy — )/);
      await expect(page.getByTestId("health-job-runner").locator("[data-reason]")).toHaveCount(0);
    } else await expect(page.getByTestId("health-job-runner")).toContainText(deferredReason(h.job_runner?.lock)!);
    w.expectClean();
  });

  test("no runner: the headline and every job item's guidance say so; nothing promises a run", async ({ page }) => {
    const w = watch(page);
    const h = await read<Health>(page, "system_health");
    test.skip(runnerLive(h), "the server runs the 032c runner: see the next test");
    await open(page);
    if (h.status && ["unknown", "action", "degraded"].includes(h.status.key)) await expect(page.getByTestId("health-action")).toContainText(RUNNER_NOT_PORTED);
    const jobItems = page.getByTestId("health-issue").filter({ hasText: /background job|external dependency/ });
    for (const item of await jobItems.all()) await expect(item.locator("span").last()).toContainText(RUNNER_NOT_PORTED);
    await expect(page.getByTestId("issues-auto").getByTestId("health-issue").filter({ hasText: /background job/ })).toHaveCount(0);
    await expect(page.getByTestId("health-action")).not.toContainText(/handled automatically/i);
    await expect(page.getByTestId("health-jobs-snapshot")).toHaveText(SNAPSHOT);
    await expectNoPromise(page);
    for (const id of DIAGNOSTICS) {
      await expand(page, id);
      await expectNoPromise(page);
    }
    w.expectClean();
  });

  test("the live runner: the unported jobs are labelled and nothing near them promises a run; the snapshot line is gone", async ({ page }) => {
    const w = watch(page);
    const h = await read<Health>(page, "system_health");
    test.skip(!runnerLive(h), "the server still sends the deferred runner: see the previous test");
    await open(page);
    await expect(page.getByTestId("health-jobs-snapshot")).toHaveCount(0);
    expect(await page.locator("body").innerText()).not.toContain(SNAPSHOT);
    await expand(page, "health-jobs");
    await expect(page.getByTestId("health-job-not-ported")).toHaveCount(unported(h).length);
    for (const r of await page.locator('[data-testid="health-job"][data-ported="false"]').all()) {
      const t = await r.innerText();
      for (const p of FORBIDDEN) expect(t, p).not.toContain(p);
    }
    for (const j of unported(h)) {
      for (const item of await page.getByTestId("health-issue").filter({ hasText: j.label.split(" (")[0] }).all()) {
        const t = await item.innerText();
        if (h.jobs.some((x) => isPorted(x) && t.includes(x.label.split(" (")[0]))) continue; // a line that also names a ported job
        for (const p of FORBIDDEN) expect(t, `${j.id}: ${p}`).not.toContain(p);
      }
    }
    w.expectClean();
  });

  test('"Run overdue now" follows the runner (deferred: disabled with its reason; live: enabled, not clicked); the 032b controls are disabled', async ({ page }) => {
    const w = watch(page);
    const h = await read<Health>(page, "system_health");
    await open(page);
    const run = page.getByRole("button", { name: "Run overdue now", exact: true });
    if (runnerLive(h)) {
      await expect(run).toHaveCount(h.overdue > 0 && portedOverdue(h).length > 0 ? 2 : 0);
      for (const b of await run.all()) {
        await expect(b).toBeEnabled();
        await expect(b).not.toHaveAttribute("aria-disabled", "true");
      }
    } else {
      await expect(run).toHaveCount(h.overdue > 0 ? 2 : 0);
      for (const b of await run.all()) await expectDeferred(page, b, RUNNER);
    }
    await expand(page, "health-hardening");
    for (const id of ["backup-now", "backup-test"]) await expectDeferred(page, page.getByTestId(id), "Backups, integrity checks and model provenance arrive with the hardening port.");
    await expand(page, "health-sources");
    await expectDeferred(page, page.getByTestId("source-network-run"), "The source network and its decisions arrive with the hardening port.");
    w.expectClean();
  });

  test("dashboard: the Deal Flow lane, no Scout part, every chart drills down", async ({ page }) => {
    const w = watch(page);
    const live = runnerLive(await read<Health>(page, "system_health"));
    await open(page);
    const pipe = page.getByTestId("health-pipeline");
    for (const id of ["df-scan", "df-triage", "df-queue", "df-you", "df-conviction"]) await expect(pipe.locator(`[data-node="${id}"]`)).toBeVisible();
    await expect(pipe.locator('[data-node^="s00"], [data-node^="nat"]')).toHaveCount(0);
    await expect(page.getByTestId("bridge-chart")).toHaveCount(0);
    await expect(page.getByTestId("pool-bridge")).toHaveCount(0);
    expect(await page.locator("body").innerText()).not.toMatch(/Scout 00|Native Scout|Grok|repair research|Scout Bridge/i);
    await pipe.locator('[data-node="df-you"]').click();
    await expect(page.getByRole("dialog", { name: "You: review" })).toContainText("Every Deal Flow decision is yours.");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("pool-general")).toContainText("General model budget");
    const jobs = page.getByTestId("health-job-history");
    for (const r of ["24h", "7d", "30d"]) {
      await jobs.getByRole("button", { name: r, exact: true }).click();
      await expect(jobs.getByRole("button", { name: r, exact: true })).toHaveAttribute("aria-pressed", "true");
    }
    const cell = jobs.locator("button[data-state]").first();
    if (await cell.count()) {
      await cell.click();
      await expect(page.getByTestId("health-detail")).toContainText("Runs in this period");
      if (!live) {
        await expect(page.getByTestId("health-detail")).toContainText(SNAPSHOT);
        await expectNoPromise(page);
      }
      await page.keyboard.press("Escape");
    } else await expect(jobs).toContainText("History unavailable");
    const problem = page.getByTestId("health-source-problem").first();
    if (await problem.count()) {
      await problem.click();
      await expect(page.getByTestId("health-detail")).toContainText("In plain words");
      await expect(page.getByRole("dialog").getByRole("button", { name: /repair research/i })).toHaveCount(0);
      await page.keyboard.press("Escape");
    }
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });

  test("Refresh re-reads the two GETs", async ({ page }) => {
    const w = watch(page);
    await open(page);
    const both = ["/api/system_health", "/api/system_health_overview"].map((p) =>
      page.waitForResponse((r) => new URL(r.url()).pathname === p && r.request().method() === "GET"),
    );
    await page.getByTestId("health-freshness").getByRole("button", { name: "Refresh", exact: true }).click();
    await Promise.all(both);
    w.expectClean();
  });

  test("dashboard on a phone: no horizontal scroll, pipeline and job rows stack", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await open(page);
    await expect(page.getByTestId("health-pipeline").locator("[data-node]").first()).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  for (const [name, size] of [
    ["1366", { width: 1366, height: 768 }],
    ["1920", { width: 1920, height: 1080 }],
  ] as const) {
    test(`no horizontal overflow at ${name}`, async ({ page }) => {
      await page.setViewportSize(size);
      await open(page);
      await expectNoHorizontalOverflow(page);
    });
  }

  test("no horizontal overflow at 150 % zoom", async ({ page }) => {
    await zoom150(page);
    await open(page);
    await expectNoHorizontalOverflow(page);
  });
});
