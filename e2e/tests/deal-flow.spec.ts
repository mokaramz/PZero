/**
 * Deal Flow — the core cases of the old `e2e/tests/deal-flow.spec.ts`, against the new app on a preview database
 * (the real snapshot in a scratch schema; decisions write only there). Review 009, Codex #2.
 *
 * Kept: workspaces, counts, filters, candidate detail, the IM / theme lenses, Reject → Rejected → Undo, the deep links,
 * and no horizontal overflow at 1366x768 and 150 % zoom. Changed on purpose: the decision body is the new
 * `{status, expected_status}`; scan / analysis / Keep are not ported, so the test asserts they are disabled and silent.
 */
import { expect, test } from "@playwright/test";

import { expand, expectNoHorizontalOverflow, filterChip, imLens, openDealFlow, recordPosts, rows, watch, zoom150 } from "./helpers";

const decisions = (posted: ReturnType<typeof recordPosts>) => posted.filter((p) => p.path.endsWith("/decision"));

test.describe("Deal Flow — new app, preview database", () => {
  test("workspaces, counts, filters and candidate detail", async ({ page }) => {
    const w = watch(page);
    await openDealFlow(page);
    await expect(page.getByRole("heading", { name: "Deal Flow" })).toBeVisible();
    await expect(page.getByText("Opportunities worth your attention")).toBeVisible();
    await expect(page.getByTestId("ws-label")).toHaveText("Core Project A sourcing — Europe is the main market and the default workspace.");
    expect(await rows(page).count()).toBeLessThanOrEqual(15);
    await expect(page.getByText(/Attention queue shows the top 15 by signal/)).toContainText(/\d+ more undecided under All to decide/);
    await expect(page.getByTestId("ib-count")).toContainText(/\d+ to decide · \d+ researching · \d+ watching · \d+ kept · \d+ rejected · \d+ baseline/);
    await expect(page.getByTestId("find-status")).toContainText(/Last run .* genuinely new/);

    for (const [ws, label] of [["na", "Exceptional opportunity hunting"], ["unk", "nothing here defaults to Europe"], ["all", "All geographies mixed"]] as const) {
      await page.locator(`[data-ws="${ws}"]`).click();
      await expect(page.getByTestId("ws-label")).toContainText(label);
      if (ws === "na") {
        await expect(page.getByRole("button", { name: "USA + Canada" })).toBeVisible();
        await page.getByRole("button", { name: "Canada", exact: true }).click();
      }
    }
    await page.locator('[data-ws="eu"]').click();

    await filterChip(page, "All to decide").click();
    await expect(page.getByText(/Showing 50 of \d+/)).toBeVisible();
    await page.getByRole("button", { name: /Show \d+ more/ }).click();
    expect(await rows(page).count()).toBeGreaterThan(50);
    const second = rows(page).nth(1);
    const name = (await second.locator('[class*="candName"]').innerText()).trim();
    await second.click();
    const det = page.getByTestId("cand-detail");
    await expect(det.getByRole("heading", { level: 2 })).toHaveText(name);
    await expand(det, "cand-evidence");
    await expect(det).toContainText("Machine-tagged only. Founders, market, timing: not judged — your job.");
    await expand(det, "cand-audit");
    await expect(det.getByTestId("cand-evidence")).not.toHaveAttribute("open", "");
    await expect(det).toContainText(/Feedback-adjusted sourcing priority [+-]?\d/);
    await expect(det).toContainText("No model is trained");
    await expect(det).toContainText("first seen by PZ");

    await filterChip(page, "Attention queue").click();
    await imLens(page);
    await expect(rows(page).first().locator('[class*="score"]')).toContainText(/A -?\d+ · L [+-]\d+ · F -?\d+/);
    await imLens(page);
    if (!(await page.getByLabel("Project A theme").isVisible())) await page.getByTestId("more-filters").click();
    await page.getByLabel("Project A theme").selectOption("defence");
    await page.getByLabel("Project A theme").selectOption("");
    w.expectClean();
  });

  test("Reject → Rejected view → Undo (new body, checked against a fresh read)", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    await openDealFlow(page);
    await filterChip(page, "All to decide").click();
    const first = rows(page).first();
    const id = await first.getAttribute("data-id");
    expect(id).toBeTruthy();
    await first.click();
    await page.getByTestId("cand-detail").getByRole("button", { name: "Reject" }).click();
    await expect.poll(() => decisions(posted)[0]?.body).toEqual({ status: "rejected", expected_status: "new" });
    expect(decisions(posted)[0].path).toBe(`/api/deal-flow/candidates/${id}/decision`);
    await expect(page.locator(`[data-id="${id}"]`)).toHaveCount(0);
    await filterChip(page, "Rejected").click();
    await page.locator(`[data-id="${id}"]`).click();
    await expect(page.getByTestId("cand-detail")).toContainText("decision: rejected");
    await page.getByTestId("cand-detail").getByRole("button", { name: "Undo" }).click();
    await expect.poll(() => decisions(posted).at(-1)?.body).toEqual({ status: "new", expected_status: "rejected" });
    await expect(page.locator(`[data-id="${id}"]`)).toHaveCount(0);
    const fresh = await page.request.get("/api/deal-flow/inbox").then((r) => r.json());
    expect(fresh.candidates.find((c: { id: string }) => c.id === id)).toMatchObject({ decision: "new", pz_status: "new" });
    w.expectClean();
  });

  test("deferred controls are disabled, explain why, and send nothing", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    await openDealFlow(page, "/deal-flow?find=1");
    await expect(page.getByTestId("find-btn")).toBeFocused();
    await expect(page.getByTestId("cand-detail").first()).toBeVisible();
    await page.waitForLoadState("networkidle"); // count only once the detail and its triage panel have loaded
    const deferred = page.locator('[aria-disabled="true"]');
    const n = await deferred.count();
    expect(n).toBeGreaterThan(3);
    for (let i = 0; i < n; i++) {
      const el = deferred.nth(i);
      if (!(await el.isVisible())) continue;
      await expect(el).toHaveAttribute("title", /.+/);
      await el.click({ force: true });
      await el.press("Enter").catch(() => undefined);
    }
    await page.waitForTimeout(500);
    expect(posted).toEqual([]);
    w.expectClean();
  });

  test("deep links: a current id, an old Scout Intake item, and ?review= send no POST", async ({ page }) => {
    const w = watch(page);
    const posted = recordPosts(page);
    const ib = await page.request.get("/api/deal-flow/inbox").then((r) => r.json());
    const scout = ib.candidates.find((c: { source?: string }) => /legacy_scout00/.test(c.source ?? ""));
    expect(scout, "a candidate that came from Scout Intake").toBeTruthy();
    const detail = await page.request.get(`/api/deal-flow/candidates/${scout.id}`).then((r) => r.json());
    const item = detail.known_ids.find((a: { namespace: string }) => a.namespace === "scout_intake")?.alias_id;
    expect(item, "its old Scout Intake item id").toBeTruthy();

    await openDealFlow(page, `/scout-intake?item=${encodeURIComponent(item)}`);
    await expect(page).toHaveURL(/\/deal-flow$/);
    await expect(page.getByTestId("cand-detail").locator('[class*="dname"]')).toHaveText(scout.name);

    const other = ib.candidates.find((c: { decision: string; id: string }) => c.decision === "watch" && c.id !== scout.id);
    await openDealFlow(page, `/deal-flow?candidate=${other.id}`);
    await expect(page.getByTestId("cand-detail").locator('[class*="dname"]')).toHaveText(other.name);
    await openDealFlow(page, `/deal-flow?review=${other.id}`);
    await expect(page.getByTestId("cand-detail").locator('[class*="dname"]')).toHaveText(other.name);
    expect(posted).toEqual([]);
    w.expectClean();
  });

  test("1366x768 and 150% zoom: no horizontal overflow", async ({ page }) => {
    const w = watch(page);
    await page.setViewportSize({ width: 1366, height: 768 });
    await openDealFlow(page);
    await expectNoHorizontalOverflow(page);
    await zoom150(page);
    await page.waitForTimeout(300);
    await expectNoHorizontalOverflow(page);
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(300);
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });
});

test.describe("Deal Flow Revisit (decision 0004, review 018)", () => {
  test("a re-report with a material change after the rejection is listed under Revisit, with its evidence", async ({ page }) => {
    const w = watch(page);
    const word = () => Math.random().toString(36).replace(/[^a-z]/g, "").slice(0, 8);
    const tag = `${word()}${word()}`;
    const name = `Revisit ${tag} Robotics`;
    const evidence = `https://news.example.com/${tag}`;
    const origin = new URL(process.env.PZ_BASE_URL ?? "http://localhost:5173").origin;
    const headers = { Origin: origin };
    const entity = { kind: "company", name, key_fact: `${name} raised a pre-seed round`, website: `https://${tag}.test`, evidence: [{ url: evidence }] }; // its own registrable domain
    const deliver = async (e: object, ref: string) =>
      (await page.request.post("/api/intake/submissions", {
        data: { contract_version: "1.0", origin: "manual", external_ref: ref, submitted_at: "2026-11-12T09:00:00+01:00", entities: [e] },
        headers,
      })).json();
    const first = await deliver(entity, `e2e-${tag}-1`);
    expect(first.resolution, JSON.stringify(first)).toBeTruthy();
    const cid = first.resolution[0].candidate_id as string;
    const decided = await page.request.post(`/api/deal-flow/candidates/${cid}/decision`, { data: { status: "rejected", reason: "e2e" }, headers });
    expect(decided.ok()).toBe(true);
    const tomorrow = new Date(Date.now() + 2 * 86_400_000).toISOString().slice(0, 10); // a Berlin day after the rejection
    const change = { kind: "funding_round", evidence_url: evidence, since: tomorrow, note: "E2E new lead investor" };
    const second = await deliver({ ...entity, material_change: change }, `e2e-${tag}-2`);
    expect(second.resolution[0].result).toBe("re_reported_closed");
    await openDealFlow(page);
    const chip = page.getByRole("button", { name: /^Revisit \d+/ });
    await expect(chip).toBeVisible();
    await chip.click();
    const row = rows(page).filter({ hasText: name });
    await expect(row).toBeVisible();
    await row.click();
    const detail = page.getByTestId("cand-detail");
    await expect(detail).toContainText("Revisit suggested: New funding round");
    await expect(detail).toContainText("E2E new lead investor");
    await expect(detail.getByRole("link", { name: /evidence/ })).toHaveAttribute("href", evidence);
    // the Revisit chip and the callout fit at 1366, 150 % and 1920
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.waitForTimeout(300);
    await expectNoHorizontalOverflow(page);
    await zoom150(page);
    await page.waitForTimeout(300);
    await expectNoHorizontalOverflow(page);
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(300);
    await expectNoHorizontalOverflow(page);
    w.expectClean();
  });
});
