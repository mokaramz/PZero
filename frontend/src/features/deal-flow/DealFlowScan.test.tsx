/**
 * The Deal Flow scan on the page (review 034a): Find New Candidates (the feed window, `POST deal-flow/find {days}`, the
 * running label and progress), the 1.2 s polling of `find_status` (fake timers), a scan started elsewhere, the finish
 * and stopped toasts with the declared refusal, the declared triage line (no triage read or refresh), the per-source
 * report (the workspace's geographies, the failed sources, the refused rows, the ledger), the lazy scan history and
 * `?find=1`. Invented names only (`test/scan/*.json`).
 */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POLL_MS, TRIAGE_LATER } from "./model/scan";
import type { InboxPayload } from "./model/types";
import { afterScan, findAnswer, findStatus, scanHistory, scanInbox, triage, type FindCase } from "./test/fixtures";
import { fakeServer, renderPage, type Routes } from "./test/server";

const STATUS = "/api/deal-flow/find_status";
const DONE_TOAST = "2 genuinely new (1 pre-company) · 4 baseline · 1 noise · 9 already known · 1 existing pipeline · 1 refused by the intake";

const findBtn = () => screen.getByTestId("find-btn");
const fold = () => screen.getByTestId("scan-fold") as HTMLDetailsElement;
const toasts = () => screen.getAllByRole("status").map((s) => s.textContent ?? "").join(" | ");

/** Open a <details> as a click on its summary would (jsdom does not toggle it). */
function openDetails(d: HTMLElement) {
  (d as HTMLDetailsElement).open = true;
  fireEvent(d, new Event("toggle"));
}

/**
 * A server whose scan starts on `POST find` and then answers `find_status` from `script` (the last answer stays);
 * before the start it answers `before`. The inbox is the scanned one, and the fresh one once the scan is done.
 */
function scanServer({ before = "idle", script = ["running", "done"], over = {} }: { before?: FindCase; script?: FindCase[]; over?: Partial<Routes> } = {}) {
  const state = { started: before !== "idle", queue: [...script], last: before as FindCase };
  const server = fakeServer({
    inbox: () => (state.last === "done" ? afterScan() : scanInbox()),
    triage: () => triage(),
    findStatus: () => {
      if (state.started) state.last = state.queue.length > 1 ? state.queue.shift()! : state.queue[0];
      return findStatus(state.last);
    },
    find: () => {
      state.started = true;
      return { status: 200, body: findAnswer("started") };
    },
    scanHistory: () => scanHistory(),
    ...over,
  });
  return { ...server, state };
}

const settle = async () => {
  for (let i = 0; i < 6; i++) await vi.advanceTimersByTimeAsync(1);
};
/** Let the fake clock run `ms`, then let the reads it started settle (their bodies resolve over a few turns). */
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
    await settle();
  });

/**
 * Step the fake clock 56 ms at a time (50 ms plus the 6 ms that let the reads settle) until the scan is over (at most `ms`), noting when each `find_status` read
 * happened and the button's label after it.
 */
async function pollUntilIdle(server: ReturnType<typeof scanServer>, ms = 15_000) {
  const at: number[] = [];
  const labels: string[] = [];
  const t0 = Date.now();
  for (let reads = server.statusReads(); Date.now() - t0 < ms && findBtn().textContent !== "Find New Candidates"; ) {
    await advance(50);
    if (server.statusReads() === reads) continue;
    reads = server.statusReads();
    at.push(Date.now());
    labels.push(findBtn().textContent ?? "");
  }
  return { gaps: at.slice(1).map((t, i) => t - at[i]), labels };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
beforeEach(() => localStorage.clear());

describe("Find New Candidates", () => {
  it("the feed window defaults to 7 days; a click posts find {days} and the bar shows the scan running", async () => {
    const server = scanServer({ script: ["running"] });
    renderPage();
    await waitFor(() => expect(findBtn()).toHaveTextContent("Find New Candidates"));
    const window = screen.getByLabelText("Feed window") as HTMLSelectElement;
    expect(window.value).toBe("7");
    expect(window).toBeEnabled();
    expect(Array.from(window.options).map((o) => o.textContent)).toEqual(["last 7 days", "last 14 days", "last 30 days"]);
    expect(findBtn()).not.toHaveAttribute("aria-disabled");
    fireEvent.change(window, { target: { value: "14" } });
    fireEvent.click(findBtn());
    await waitFor(() => expect(findBtn()).toHaveTextContent("Scanning 2 / 7…"));
    expect(server.posts()).toEqual([{ method: "POST", path: "/api/deal-flow/find", body: { days: "14" } }]);
    expect(findBtn()).toBeDisabled();
    expect(fold().open).toBe(true);
    expect(within(fold()).getByText(/^scanning 2 \/ 7$/)).toBeInTheDocument();
    expect(screen.getByTestId("find-status")).toHaveTextContent("Scanning 2 / 7 — sources run concurrently; slow ones cannot block the rest.");
    const progress = screen.getByTestId("scan-progress");
    expect(progress).toHaveTextContent("✓ Isarwerk Venture Lab 2 new lines");
    expect(progress).toHaveTextContent("✕ Halden Feed HTTP Error 503: Service Unavailable");
    // while running: no report, no triage line
    expect(screen.queryByTestId("scan-report")).toBeNull();
    expect(screen.queryByTestId("scan-triage")).toBeNull();
    expect(toasts()).toContain("Scanning sources — started; it runs in the background (see Background activity)");
  });

  it("polls find_status every 1.2 s while running; when done: the toast with the refusal, the refreshes, no triage", async () => {
    vi.useFakeTimers();
    const server = scanServer({ script: ["running", "running", "running", "running_more", "running_more", "done"] });
    const { qc } = renderPage();
    await advance(0);
    expect(findBtn()).toHaveTextContent("Find New Candidates");
    await advance(5 * POLL_MS);
    expect(server.statusReads()).toBe(1); // idle: read once, never polled
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    const triageReads = server.gets("/api/deal-flow/triage");
    const inboxReads = server.inboxReads();
    fireEvent.click(findBtn());
    await advance(0);
    expect(findBtn()).toHaveTextContent(/^Scanning \d \/ 7…$/);

    const { gaps, labels } = await pollUntilIdle(server);
    expect(gaps.length).toBeGreaterThan(1);
    for (const g of gaps) expect(Math.abs(g - POLL_MS) <= 56, `a read ${g} ms after the last`).toBe(true); // every 1.2 s
    expect(labels).toContain("Scanning 5 / 7…");
    expect(labels.at(-1)).toBe("Find New Candidates");
    expect(toasts()).toContain(DONE_TOAST);

    // the views a scan changes are read again; the triage never
    const keys = invalidate.mock.calls.map((c) => (c[0] as { queryKey?: unknown[] } | undefined)?.queryKey?.[0]);
    for (const k of ["deal-flow/inbox", "sources", "deal-flow/scan_history", "system_health", "catchup"]) expect(keys).toContain(k);
    expect(keys.some((k) => typeof k === "string" && k.includes("triage"))).toBe(false);
    await advance(0);
    expect(server.inboxReads()).toBeGreaterThan(inboxReads);
    expect(server.gets("/api/deal-flow/triage")).toBe(triageReads);
    expect(server.calls.some((c) => c.path.includes("triage_auto"))).toBe(false);

    // the fresh inbox: the new run's ledger, the triage line; polling has stopped
    expect(screen.getByTestId("find-status")).toHaveTextContent("Last run 2026-11-13 09:30 — 2 genuinely new");
    expect(screen.getByTestId("scan-ledger")).toHaveTextContent("Scan ledger 2026-11-13 09:30");
    expect(screen.getByTestId("scan-triage")).toHaveTextContent(TRIAGE_LATER);
    const reads = server.statusReads();
    await advance(5 * POLL_MS);
    expect(server.statusReads()).toBe(reads);
    expect(server.posts().map((p) => p.path)).toEqual(["/api/deal-flow/find"]);
  });

  it("a scan started elsewhere is picked up on load: its progress, the polling, then the finish toast — nothing posted", async () => {
    vi.useFakeTimers();
    const server = scanServer({ before: "running", script: ["running", "running_more", "done"] });
    renderPage();
    await advance(0);
    expect(findBtn()).toHaveTextContent("Scanning 2 / 7…");
    expect(findBtn()).toBeDisabled();
    expect(fold().open).toBe(true);
    expect(screen.getByTestId("scan-progress")).toHaveTextContent("✓ Isarwerk Venture Lab");
    const { gaps, labels } = await pollUntilIdle(server);
    for (const g of gaps) expect(Math.abs(g - POLL_MS) <= 56, `a read ${g} ms after the last`).toBe(true);
    expect(labels).toEqual(expect.arrayContaining(["Scanning 5 / 7…", "Find New Candidates"]));
    expect(toasts()).toContain(DONE_TOAST);
    expect(server.posts()).toEqual([]);
  });

  it("a stopped scan: the old error toast, and the views are read again", async () => {
    vi.useFakeTimers();
    const server = scanServer({ script: ["running", "stopped"] });
    renderPage();
    await advance(0);
    const inboxReads = server.inboxReads();
    fireEvent.click(findBtn());
    await advance(0);
    await pollUntilIdle(server);
    expect(findBtn()).toHaveTextContent("Find New Candidates");
    expect(toasts()).toContain("Scan stopped: the source registry could not be read — nothing was half-saved; start it again when ready");
    expect(toasts()).not.toContain("genuinely new (");
    await advance(0);
    expect(server.inboxReads()).toBeGreaterThan(inboxReads);
  });

  it("no refusal: the finish toast is exactly the old one", async () => {
    vi.useFakeTimers();
    const done = findStatus("done");
    done.result!.refused = 0;
    let n = 0;
    scanServer({ before: "running", over: { findStatus: () => (++n < 2 ? findStatus("running") : done) } });
    renderPage();
    await advance(0);
    await advance(POLL_MS);
    expect(toasts()).toContain("2 genuinely new (1 pre-company) · 4 baseline · 1 noise · 9 already known · 1 existing pipeline");
    expect(toasts()).not.toContain("refused");
  });

  it("a scan already running when Find is clicked: the old note, then its progress", async () => {
    // the start answers "already running" (the old `start_scan` answer for a second scan)
    const routes: ReturnType<typeof scanServer> = scanServer({
      script: ["running"],
      over: {
        find: () => {
          routes.state.started = true;
          return { status: 200, body: findAnswer("running") };
        },
      },
    });
    renderPage();
    await waitFor(() => expect(findBtn()).toHaveTextContent("Find New Candidates"));
    fireEvent.click(findBtn());
    await waitFor(() => expect(findBtn()).toHaveTextContent("Scanning 2 / 7…"));
    expect(toasts()).toContain("Scan already running — showing progress");
    expect(routes.posts()).toHaveLength(1);
  });

  it("a server without find_status: Find stays usable, nothing polls, the page shows no error", async () => {
    vi.useFakeTimers();
    const server = fakeServer({ inbox: () => scanInbox(), triage: () => triage() });
    renderPage();
    await advance(0);
    await advance(5 * POLL_MS);
    expect(server.gets(STATUS)).toBe(1);
    expect(findBtn()).toHaveTextContent("Find New Candidates");
    expect(findBtn()).toBeEnabled();
    expect(screen.getByTestId("scan-report")).toBeInTheDocument();
  });

  it("never run: the old first-run note, no report, no triage line", async () => {
    const ib: InboxPayload = { ...scanInbox(), last_run: null, last_summary: {}, report: [] };
    fakeServer({ inbox: () => ib, triage: () => triage(), findStatus: () => findStatus("idle") });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("find-status")).toHaveTextContent(/^Never run\. First run only saves a baseline/));
    expect(within(fold()).getByText(/never run/)).toBeInTheDocument();
    expect(screen.queryByTestId("scan-report")).toBeNull();
    expect(screen.queryByTestId("scan-triage")).toBeNull();
  });
});

describe("the scan report", () => {
  async function report() {
    fakeServer({ inbox: () => scanInbox(), triage: () => triage(), findStatus: () => findStatus("idle") });
    renderPage();
    return waitFor(() => screen.getByTestId("scan-report"));
  }
  const repRows = (scope: HTMLElement) => within(scope).queryAllByTestId("scan-rep-row").map((r) => r.getAttribute("data-source"));

  it("the header, the workspace's geographies and the other geographies folded", async () => {
    const rep = await report();
    expect(rep).toHaveTextContent("7 sources · 5 healthy · 1 failed · 1 disabled");
    expect(rep).toHaveTextContent("showing Europe (5)");
    const details = within(rep).getByText("Show source details").closest("details")!;
    const more = within(details).getByText("Show all 7 rows (other geographies)").closest("details")!;
    const mine = repRows(details).filter((s) => !repRows(more).includes(s));
    expect(mine).toEqual(["Isarwerk Venture Lab", "Lindqvist Grants", "Halden Feed", "Global Deep Tech Wire", "Brightwater Registry"]);
    expect(repRows(more)).toEqual(["Prairie SBIR awards", "Maplewood Accelerator"]);
    expect(within(details).getAllByTestId("scan-rep-row")[0]).toHaveTextContent("Isarwerk Venture Lab WATCHER 3 new lines · raw 12 · records 3");

    fireEvent.click(document.querySelector('[data-ws="na"]')!);
    await waitFor(() => expect(screen.getByTestId("scan-report")).toHaveTextContent("showing North America (3)"));
    const na = screen.getByTestId("scan-report");
    const naMore = within(na).getByText("Show all 7 rows (other geographies)").closest("details")!;
    expect(repRows(naMore)).toEqual(["Isarwerk Venture Lab", "Lindqvist Grants", "Halden Feed", "Brightwater Registry"]);
    fireEvent.click(document.querySelector('[data-ws="all"]')!);
    await waitFor(() => expect(screen.getByTestId("scan-report")).toHaveTextContent("showing all geographies (7)"));
    expect(within(screen.getByTestId("scan-report")).queryByText(/other geographies/)).toBeNull();
  });

  it("the failed sources in plain words", async () => {
    const rep = await report();
    expect(within(rep).getByTestId("scan-outcome")).toHaveTextContent(
      "⚠ Scan partially complete — 5 sources successful, 1 unavailable: Halden Feed — the publisher's server had an error. No companies from the successful sources were lost; failing sources are retried at the next scan (System health shows why and what to do).",
    );
    const halden = within(rep).getAllByTestId("scan-rep-row").find((r) => r.getAttribute("data-source") === "Halden Feed")!;
    expect(halden).toHaveTextContent("Halden Feed FEED the publisher's server had an error (HTTP Error 503: Service Unavailable)");
  });

  it("a row with refusals says so after its counts, with the reason in its note; the others say nothing", async () => {
    const rep = await report();
    const rows = within(rep).getAllByTestId("scan-rep-row");
    const bw = rows.find((r) => r.getAttribute("data-source") === "Brightwater Registry")!;
    expect(bw).toHaveTextContent(
      "Brightwater Registry STRUCTURED 1 item(s) refused by the intake: the name is not a company name · raw 5 · records 4 · 1 refused by the intake",
    );
    expect(within(bw).getByTestId("scan-rep-refused")).toHaveTextContent(/^· 1 refused by the intake$/);
    expect(within(rep).getAllByTestId("scan-rep-refused")).toHaveLength(1);
  });

  it("the summary line, the ledger and the triage line", async () => {
    const rep = await report();
    expect(screen.getByTestId("find-status")).toHaveTextContent(
      "Last run 2026-11-12 22:15 — 3 genuinely new (1 from pre-company channels) · 0 baseline · 1 noise auto-rejected · 11 already known (skipped) · 3 merged · 2 existing pipeline — not discovered in this scan",
    );
    expect(within(fold()).getByText(/last run 2026-11-12 22:15 · 3 new/)).toBeInTheDocument();
    const led = within(rep).getByTestId("scan-ledger");
    expect(led).toHaveTextContent(
      "Scan ledger 2026-11-12 22:15 (started 2026-11-12 22:15:02, finished 2026-11-12 22:18:40) · sources attempted 6: 5 successful / 1 failed / 1 disabled · raw records retrieved 61 · genuinely new 3 · already known skipped 11 · duplicates merged 3 (1 cross-source, 2 into existing) · baseline 0 · Existing pipeline — not discovered in this scan: 2 (Varnholt Systems, Ellery Foods)",
    );
    expect(led).toHaveTextContent("New this scan: Quillon Robotics (Isarwerk Venture Lab · source date 2026-11-10 · first seen 2026-11-12 22:16)");
    expect(led).toHaveTextContent("Tamberlane Optics (Prairie SBIR awards · source date UNKNOWN · first seen 2026-11-12 22:16)");
    expect(within(led).getByRole("link", { name: "Fennmoor Grid" })).toHaveAttribute("href", "https://grants.example.org/fennmoor");
    expect(screen.getByTestId("scan-triage")).toHaveTextContent(/^Machine triage arrives with the triage port\.$/);
  });
});

describe("the scan history", () => {
  it("loads nothing until opened, then the old table, latest first", async () => {
    const server = scanServer();
    renderPage();
    const h = await waitFor(() => screen.getByTestId("scan-history"));
    expect((h as HTMLDetailsElement).open).toBe(false);
    expect(h).not.toHaveAttribute("aria-disabled");
    expect(server.calls.some((c) => c.path.includes("scan_history"))).toBe(false);
    openDetails(h);
    const table = await within(h).findByTestId("scan-history-table");
    expect(server.calls.filter((c) => c.path.includes("scan_history")).map((c) => c.path)).toEqual(["/api/deal-flow/scan_history?n=10"]);
    expect(within(table).getAllByRole("columnheader").map((c) => c.textContent)).toEqual([
      "Scan",
      "Sources ok / failed / off",
      "Raw",
      "New",
      "Already known",
      "Merged",
      "Baseline",
      "Existing pipeline — not discovered in this scan",
    ]);
    const body = within(table).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell").map((c) => c.textContent));
    expect(body).toEqual([
      ["2026-11-12 22:15", "5 / 1 / 1", "61", "3", "11", "3", "0", "2"],
      ["2026-11-05 22:10", "6 / 0 / 1", "70", "5", "8", "1", "2", "1"],
    ]);
    expect(h).toHaveTextContent("14 scans recorded in total · showing the latest 2.");
    expect(server.posts()).toEqual([]);
  });

  it("no scans recorded yet", async () => {
    scanServer({ over: { scanHistory: () => ({ scans: [], total: 0, pipeline_label: "Existing pipeline" }) } });
    renderPage();
    const h = await waitFor(() => screen.getByTestId("scan-history"));
    openDetails(h);
    expect(await within(h).findByText("No scans recorded yet.")).toBeInTheDocument();
  });
});

describe("?find=1", () => {
  it("focuses the live Find control and never starts a scan", async () => {
    const server = scanServer();
    const { router } = renderPage("/deal-flow?find=1");
    await waitFor(() => expect(document.activeElement).toBe(findBtn()));
    expect(findBtn()).not.toHaveAttribute("aria-disabled");
    expect(findBtn()).toBeEnabled();
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(server.posts()).toEqual([]);
  });
});
