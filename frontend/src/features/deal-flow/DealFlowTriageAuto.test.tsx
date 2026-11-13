/**
 * Machine triage after a scan, on the page (review 035b): the old `AutoTriageStatus` line in the FindBar — nothing
 * before the first run, when switched off or on a server without the endpoint; the running wording and the 2 s polling;
 * the backend's sentence when done, partial (amber, Retry now (2)) or failed (red, Retry now (1)); Retry now's post, its
 * started toast and the two old refusals; the 60 s watch after a scan; a newly finished run announced once, with the
 * triage and Today read again — and the candidate detail's pending section. Invented names only (`test/triage_auto/`).
 */
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AUTO_FINISHED_INVALIDATES, RETRY_INVALIDATES } from "./hooks/useTriageAuto";
import { POLL_MS } from "./model/scan";
import { AUTO_POLL_MS, RETRY_STARTED, WATCH_MS, type AutoStatus } from "./model/triageAuto";
import { afterScan, autoStatus, autoTriageView, findAnswer, findStatus, retryAnswer, scanInbox, type AutoCase, type FindCase } from "./test/fixtures";
import { fakeServer, renderPage, type Routes } from "./test/server";

const AUTO = "/api/deal-flow/triage_auto";
const RETRY = "/api/deal-flow/triage_retry";
const HEAD = "Machine triage after scan (proposals only — the Attention score is separate):";
const DONE = "Machine triage complete — 3 processed (1 KEEP · 1 WATCH · 1 REJECT) · $0.0031.";
const PARTIAL =
  "Machine triage partially complete — 1 processed (1 KEEP); 2 preserved for automatic retry because the model provider did not answer in time (next try after 22:34) · $0.0012. No data was lost; these are proposals only.";
const FAILED =
  "Machine triage could not run — 0 processed; 1 need a manual retry (“Retry now”) — the model provider refused the request. No data was lost; these are proposals only.";
const RETRY_DONE = "Machine triage complete — 2 processed (1 KEEP · 1 RESEARCH) · $0.0020.";

const line = () => screen.queryByTestId("auto-triage-status");
const retryBtn = () => screen.queryByTestId("triage-retry-now");

/** Every toast shown, in order — also the ones already gone (a toast leaves after a few seconds). */
let shown: string[] = [];
let observer: MutationObserver | null = null;
function recordToasts() {
  shown = [];
  observer = new MutationObserver((ms) => {
    for (const m of ms)
      for (const n of Array.from(m.addedNodes))
        if (n instanceof HTMLElement && n.parentElement?.getAttribute("role") === "status") shown.push(n.textContent ?? "");
  });
  observer.observe(document.body, { childList: true, subtree: true });
}
const count = (text: string) => shown.filter((t) => t === text).length;

const settle = async () => {
  for (let i = 0; i < 6; i++) await vi.advanceTimersByTimeAsync(1);
};
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
    await settle();
  });

/**
 * The scan's world with `triage_auto` answering `script` (each read takes the next answer, the last one stays) — or,
 * once `POST triage_retry` started a run, `after`. Retry now answers `retry`.
 */
function serve({ script = ["done"], after = [], retry = "started", over = {} }: { script?: Array<AutoCase | AutoStatus>; after?: AutoCase[]; retry?: Parameters<typeof retryAnswer>[0]; over?: Partial<Routes> } = {}) {
  const queue = [...script];
  const next = (): AutoStatus => {
    const c = queue.length > 1 ? queue.shift()! : queue[0];
    return typeof c === "string" ? autoStatus(c) : structuredClone(c);
  };
  const server = fakeServer({
    inbox: () => scanInbox(),
    triage: () => autoTriageView(),
    findStatus: () => findStatus("idle"),
    triageAuto: () => next(),
    triageRetry: () => {
      const a = retryAnswer(retry);
      if (a.started && after.length) queue.splice(0, queue.length, ...after);
      return { status: 200, body: a };
    },
    ...over,
  });
  return { ...server, autoGets: () => server.gets(AUTO), retries: () => server.posts().filter((p) => p.path === RETRY) };
}

beforeEach(() => {
  localStorage.clear();
  recordToasts();
});
afterEach(() => {
  observer?.disconnect();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the post-scan machine-triage line", () => {
  it.each([
    ["no run yet", "none"],
    ["automatic triage switched off", "disabled"],
  ] as const)("%s: nothing shows, nothing polls", async (_name, c) => {
    vi.useFakeTimers();
    const server = serve({ script: [c] });
    renderPage();
    await advance(0);
    expect(screen.getByTestId("find-status")).toBeInTheDocument();
    expect(line()).toBeNull();
    await advance(10 * AUTO_POLL_MS);
    expect(server.autoGets()).toBe(1);
  });

  it("a server without the endpoint: nothing shows, it is never polled, the page has no error", async () => {
    vi.useFakeTimers();
    const server = serve({ over: { triageAuto: undefined } });
    renderPage();
    await advance(0);
    await advance(10 * AUTO_POLL_MS);
    expect(line()).toBeNull();
    expect(server.autoGets()).toBe(1);
    expect(screen.getByTestId("scan-report")).toBeInTheDocument();
  });

  it("done: the old heading and the backend's sentence; no warning, no Retry now, no polling, no toast on load", async () => {
    vi.useFakeTimers();
    const server = serve();
    const { qc } = renderPage();
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    await advance(0);
    expect(line()).toHaveTextContent(`${HEAD} ${DONE}`);
    expect(line()!.textContent!.startsWith("Machine triage after scan")).toBe(true);
    expect(line()).toHaveAttribute("data-state", "done");
    expect(retryBtn()).toBeNull();
    await advance(10 * AUTO_POLL_MS);
    expect(server.autoGets()).toBe(1);
    // the run already there when the page loaded is nothing new
    expect(shown).toEqual([]);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("running: the old wording, polled every 2 s; when it finishes: the toast once, the triage and Today read again, polling stops", async () => {
    vi.useFakeTimers();
    const server = serve({ script: ["running", "running", "running", "partial"] });
    const { qc } = renderPage();
    const invalidate = vi.spyOn(qc, "invalidateQueries");
    await advance(0);
    expect(line()).toHaveTextContent(`${HEAD} 3 new or changed candidate(s) — machine triage running…`);
    expect(line()).toHaveAttribute("data-state", "running");
    expect(retryBtn()).toBeNull();
    const triageReads = server.gets("/api/deal-flow/triage");
    const at = [Date.now()];
    for (let reads = 1; server.autoGets() < 4 && Date.now() - at[0] < 4 * AUTO_POLL_MS; ) {
      await advance(50);
      if (server.autoGets() !== reads) {
        reads = server.autoGets();
        at.push(Date.now());
      }
    }
    expect(server.autoGets()).toBe(4);
    for (const g of at.slice(1).map((t, i) => t - at[i])) expect(Math.abs(g - AUTO_POLL_MS) <= 60, `a read ${g} ms after the last`).toBe(true);
    // finished: partial — amber, Retry now (2)
    expect(line()).toHaveTextContent(`⚠ ${HEAD} ${PARTIAL}`);
    expect(line()).toHaveAttribute("data-state", "partial");
    expect(retryBtn()).toHaveTextContent(/^Retry now \(2\)$/);
    expect(count(PARTIAL)).toBe(1);
    const keys = invalidate.mock.calls.map((c) => (c[0] as { queryKey?: unknown[] } | undefined)?.queryKey?.[0]);
    expect(keys).toEqual([...AUTO_FINISHED_INVALIDATES]);
    expect([...AUTO_FINISHED_INVALIDATES]).toEqual(["deal-flow/triage", "today"]);
    await advance(0);
    expect(server.gets("/api/deal-flow/triage")).toBeGreaterThan(triageReads);
    // no longer running: no more polling, and the same run is never announced again
    await advance(10 * AUTO_POLL_MS);
    expect(server.autoGets()).toBe(4);
    expect(count(PARTIAL)).toBe(1);
    expect(server.posts()).toEqual([]);
  });

  it("failed: the warning, the backend's sentence and Retry now (1)", async () => {
    serve({ script: ["failed"] });
    renderPage();
    await waitFor(() => expect(line()).toHaveTextContent(`⚠ ${HEAD} ${FAILED}`));
    expect(line()).toHaveAttribute("data-state", "failed");
    expect(retryBtn()).toHaveTextContent(/^Retry now \(1\)$/);
  });

  it("hidden while a scan runs", async () => {
    serve({ script: ["partial"], over: { findStatus: () => findStatus("running") } });
    renderPage();
    await waitFor(() => expect(screen.getByTestId("scan-progress")).toBeInTheDocument());
    expect(line()).toBeNull();
    expect(retryBtn()).toBeNull();
  });
});

describe("Retry now", () => {
  it("nothing before the click; then the post, the old started toast, the run polled and announced once when done", async () => {
    vi.useFakeTimers();
    const server = serve({ script: ["partial"], after: ["retry_running", "retry_running", "retry_done"] });
    const { qc } = renderPage();
    await advance(0);
    expect(retryBtn()).toHaveTextContent("Retry now (2)");
    await advance(5 * AUTO_POLL_MS);
    expect(server.posts()).toEqual([]);
    expect(server.autoGets()).toBe(1);
    const invalidate = vi.spyOn(qc, "invalidateQueries");

    fireEvent.click(retryBtn()!);
    await advance(0);
    expect(server.retries()).toEqual([{ method: "POST", path: RETRY, body: {} }]);
    expect(count(RETRY_STARTED)).toBe(1);
    const keys = invalidate.mock.calls.map((c) => (c[0] as { queryKey?: unknown[] } | undefined)?.queryKey?.[0]);
    expect(keys).toEqual(expect.arrayContaining([...RETRY_INVALIDATES]));
    expect([...RETRY_INVALIDATES]).toEqual(["deal-flow/triage_auto"]);
    // the status read again: the retry run is going — the running wording, no button, polled every 2 s
    expect(server.autoGets()).toBe(2);
    expect(line()).toHaveTextContent(`${HEAD} 2 new or changed candidate(s) — machine triage running…`);
    expect(retryBtn()).toBeNull();
    await advance(AUTO_POLL_MS);
    expect(server.autoGets()).toBe(3);
    await advance(AUTO_POLL_MS);
    expect(server.autoGets()).toBe(4);
    expect(line()).toHaveTextContent(`${HEAD} ${RETRY_DONE}`);
    expect(line()).not.toHaveTextContent("⚠");
    expect(retryBtn()).toBeNull();
    expect(count(RETRY_DONE)).toBe(1);
    await advance(10 * AUTO_POLL_MS);
    expect(server.autoGets()).toBe(4);
    expect(count(RETRY_DONE)).toBe(1);
    expect(server.retries()).toHaveLength(1);
  });

  it.each([
    ["nothing_waiting", "Nothing is waiting for a retry."],
    ["in_progress", "A machine triage run is already in progress."],
  ] as const)("refused (%s): the server's reason as the toast, nothing else changes", async (answer, reason) => {
    const server = serve({ script: ["partial"], retry: answer });
    renderPage();
    await waitFor(() => expect(retryBtn()).toBeInTheDocument());
    fireEvent.click(retryBtn()!);
    await waitFor(() => expect(count(reason)).toBe(1));
    expect(shown).not.toContain(RETRY_STARTED);
    expect(server.retries()).toEqual([{ method: "POST", path: RETRY, body: {} }]);
    expect(line()).toHaveTextContent(PARTIAL);
    expect(retryBtn()).toHaveTextContent("Retry now (2)");
  });

  it("a failed post: the action's error toast, the line stays", async () => {
    serve({ script: ["partial"], over: { triageRetry: () => ({ status: 500, body: { ok: false, error: "the database is unavailable" } }) } });
    renderPage();
    await waitFor(() => expect(retryBtn()).toBeInTheDocument());
    fireEvent.click(retryBtn()!);
    await waitFor(() => expect(shown.some((t) => t.startsWith("✕ Retrying machine triage failed"))).toBe(true));
    expect(line()).toHaveTextContent(PARTIAL);
  });
});

describe("the 60 s watch after a scan", () => {
  /** The previous scan's run, finished before the page opened. */
  const previous = (): AutoStatus => {
    const d = autoStatus("done");
    return { ...d, last: { ...d.last!, scan_run_id: "2026-11-05 22:10", finished: "2026-11-05 22:13:40" } };
  };

  function scanThenTriage(script: Array<AutoCase | AutoStatus>) {
    const state = { started: false, scan: ["running", "done"] as FindCase[], last: "idle" as FindCase, auto: [previous()] as Array<AutoCase | AutoStatus>, run: false };
    const server = serve({
      over: {
        inbox: () => (state.last === "done" ? afterScan() : scanInbox()),
        findStatus: () => {
          if (state.started) state.last = state.scan.length > 1 ? state.scan.shift()! : state.scan[0];
          return findStatus(state.last);
        },
        find: () => {
          state.started = true;
          return { status: 200, body: findAnswer("started") };
        },
        triageAuto: () => {
          // the post-scan run appears once the scan is done
          if (state.last === "done" && !state.run) {
            state.run = true;
            state.auto = [...script];
          }
          const c = state.auto.length > 1 ? state.auto.shift()! : state.auto[0];
          return typeof c === "string" ? autoStatus(c) : structuredClone(c);
        },
      },
    });
    return { ...server, state };
  }

  /** Click Find and step the clock until the scan's finish toast shows. */
  async function findAndFinish() {
    fireEvent.click(screen.getByTestId("find-btn"));
    await advance(0);
    for (let i = 0; i < 20 && !shown.some((t) => t.includes("genuinely new (")); i++) await advance(POLL_MS);
    expect(shown.some((t) => t.includes("genuinely new ("))).toBe(true);
  }

  it("after Find the status is polled every 2 s for 60 s; the new run is announced once; then polling stops", async () => {
    vi.useFakeTimers();
    // the post-scan run: not started yet (the previous run), then running, then partial
    const server = scanThenTriage([previous(), previous(), "running", "running", "partial"]);
    const { qc } = renderPage();
    await advance(0);
    expect(line()).toHaveTextContent(DONE);
    await advance(5 * AUTO_POLL_MS);
    expect(server.autoGets()).toBe(1); // idle and not watching: read once
    const invalidate = vi.spyOn(qc, "invalidateQueries");

    await findAndFinish();
    const t0 = Date.now();
    const at: number[] = [];
    let reads = server.autoGets();
    while (Date.now() - t0 < WATCH_MS + 10 * AUTO_POLL_MS) {
      await advance(100);
      if (server.autoGets() !== reads) {
        reads = server.autoGets();
        at.push(Date.now() - t0);
      }
    }
    // every 2 s, for the 60 s, then nothing
    const gaps = at.slice(1).map((t, i) => t - at[i]);
    for (const g of gaps) expect(Math.abs(g - AUTO_POLL_MS) <= 110, `a read ${g} ms after the last`).toBe(true);
    expect(at.at(-1)!).toBeLessThanOrEqual(WATCH_MS + 110);
    expect(at.length).toBeGreaterThanOrEqual(WATCH_MS / AUTO_POLL_MS - 2);
    expect(line()).toHaveTextContent(`⚠ ${HEAD} ${PARTIAL}`);
    expect(count(PARTIAL)).toBe(1);
    const keys = invalidate.mock.calls.map((c) => (c[0] as { queryKey?: unknown[] } | undefined)?.queryKey?.[0]);
    expect(keys).toContain("deal-flow/triage_auto"); // the scan's finish
    for (const k of AUTO_FINISHED_INVALIDATES) expect(keys).toContain(k);
    expect(server.posts().map((p) => p.path)).toEqual(["/api/deal-flow/find"]);
  });

  it("no post-scan run within the 60 s: nothing is announced, and polling stops", async () => {
    vi.useFakeTimers();
    const server = scanThenTriage([previous()]);
    renderPage();
    await advance(0);
    await findAndFinish();
    await advance(WATCH_MS + AUTO_POLL_MS);
    const reads = server.autoGets();
    expect(reads).toBeGreaterThan(20);
    await advance(10 * AUTO_POLL_MS);
    expect(server.autoGets()).toBe(reads);
    expect(shown.filter((t) => t.startsWith("Machine triage"))).toEqual([]);
    expect(line()).toHaveTextContent(DONE);
  });
});

describe("the candidate detail's pending section", () => {
  it("a candidate kept for a retry and without a proposal: the amber Machine triage section with the reason", async () => {
    serve({ script: ["partial"] });
    renderPage("/deal-flow?candidate=s-0102");
    const sec = await screen.findByTestId("triage-pending");
    expect(within(screen.getByTestId("cand-detail")).getByRole("heading", { level: 2 })).toHaveTextContent("Fennmoor Grid");
    expect(within(sec).getByRole("heading", { level: 4 })).toHaveTextContent("Machine triage");
    expect(sec).toHaveTextContent("TRIAGE PENDING: the model provider did not answer in time — kept for an automatic retry after 22:34");
    expect(within(screen.getByTestId("cand-detail")).queryByTestId("triage-panel")).toBeNull();
  });

  it("a candidate with a proposal: its triage panel, no pending section", async () => {
    serve({ script: ["partial"] });
    renderPage("/deal-flow?candidate=s-0101");
    await waitFor(() => expect(within(screen.getByTestId("cand-detail")).getByRole("heading", { level: 2 })).toHaveTextContent("Quillon Robotics"));
    expect(await within(screen.getByTestId("cand-detail")).findByTestId("triage-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("triage-pending")).toBeNull();
  });
});
