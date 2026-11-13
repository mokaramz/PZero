/** The catch-up banner (review 032c): ported from the old `app/CatchUpBanner.tsx`, with its "Project Zero runs on your
 *  computer" sentence reworded for the new app. It polls `GET catchup` every 2.5 s while a run is going and every 60 s
 *  otherwise (fake timers), shows the run while it goes, refreshes every cached view when it ends, and renders nothing
 *  when idle, disabled or when the server has no such endpoint. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POLL_IDLE_MS, POLL_RUNNING_MS, type CatchUp } from "./api";
import { BUDGET_NOTE, CatchUpBanner, WHERE_JOBS_RUN } from "./CatchUpBanner";
import { catchupDisabled, catchupDone, catchupIdle, catchupRunning } from "./test/fixtures";

type Reply = CatchUp | { status: number; body: unknown };

/** Answers `GET /api/catchup` from `next()`; counts the reads. */
function server(next: () => Reply) {
  const reads: string[] = [];
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://x");
      if ((init?.method ?? "GET") === "GET" && url.pathname === "/api/catchup") {
        reads.push(url.pathname);
        const r = next();
        return "status" in r && "body" in r ? json(r.status, r.body) : json(200, r);
      }
      return json(404, { ok: false, error: "not found" });
    }),
  );
  return { reads };
}

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } });
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  render(
    <QueryClientProvider client={qc}>
      <CatchUpBanner />
    </QueryClientProvider>,
  );
  return { qc, invalidate };
}

/** Let the timers run `ms`, then let the reads it started settle (their bodies resolve over a few turns; 5 ms of fake
 *  time, far below the 2.5 s pace). */
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
    for (let i = 0; i < 5; i++) await vi.advanceTimersByTimeAsync(1); // the response bodies, React Query's batched notifications
  });
const banner = () => screen.queryByTestId("catchup-banner");

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("CatchUpBanner", () => {
  it("while running: the count, the job running now, what is left, and the reworded sentence", async () => {
    server(catchupRunning);
    mount();
    await advance(0);
    const b = banner()!;
    expect(b).toHaveAttribute("role", "status");
    expect(b.querySelector("b")).toHaveTextContent(/^Catching up on 4 overdue checks…$/);
    expect(b).toHaveTextContent("Now: Validation snapshot.");
    expect(b).toHaveTextContent("3 left.");
    expect(b).toHaveTextContent(`${WHERE_JOBS_RUN} ${BUDGET_NOTE}`);
    expect(b.textContent).toBe(`Catching up on 4 overdue checks… Now: Validation snapshot. 3 left. ${WHERE_JOBS_RUN} ${BUDGET_NOTE}`);
  });

  it("the reworded sentence: the catch-up and the new Windows task; never the old wording, never Scout", async () => {
    expect(WHERE_JOBS_RUN).toContain("catch-up when the app opens");
    expect(WHERE_JOBS_RUN).toContain("“Project Zero v2 - background jobs”");
    expect(WHERE_JOBS_RUN).toContain("registered disabled until the cutover");
    expect(BUDGET_NOTE).toBe("Budget caps apply; nothing is sent to anyone.");
    server(catchupRunning);
    mount();
    await advance(0);
    const t = banner()!.textContent ?? "";
    expect(t).not.toContain("Project Zero runs on your computer");
    expect(t).not.toContain("happens when it is open");
    expect(t).not.toContain("WATCH checks");
    expect(t).not.toMatch(/scout|bridge|grok/i);
  });

  it("one job, nothing done yet: singular, 'Starting.'", async () => {
    server(() => ({ ...catchupRunning(), queue: ["News refresh"], current: null, done: [] }));
    mount();
    await advance(0);
    expect(banner()).toHaveTextContent(/^Catching up on 1 overdue check… Starting\. 1 left\./);
  });

  it("the last job running: no 'left' count", async () => {
    const r = catchupDone();
    server(() => ({ ...r, running: true, current: "Weekly learning review" }));
    mount();
    await advance(0);
    expect(banner()).toHaveTextContent("Now: Weekly learning review.");
    expect(banner()).not.toHaveTextContent("left.");
  });

  it("polls every 2.5 s while running", async () => {
    const { reads } = server(catchupRunning);
    mount();
    await advance(0);
    expect(reads).toHaveLength(1);
    await advance(POLL_RUNNING_MS - 100);
    expect(reads).toHaveLength(1);
    await advance(200);
    expect(reads).toHaveLength(2);
    await advance(POLL_RUNNING_MS * 3);
    expect(reads).toHaveLength(5);
  });

  it("idle: renders nothing and polls every 60 s", async () => {
    const { reads } = server(catchupIdle);
    mount();
    await advance(0);
    expect(banner()).toBeNull();
    expect(reads).toHaveLength(1);
    await advance(POLL_RUNNING_MS * 4);
    expect(reads).toHaveLength(1);
    await advance(POLL_IDLE_MS - POLL_RUNNING_MS * 4);
    expect(reads).toHaveLength(2);
    expect(banner()).toBeNull();
  });

  it("disabled (enabled: false) and idle: renders nothing, polls at the idle pace", async () => {
    const { reads } = server(catchupDisabled);
    mount();
    await advance(POLL_IDLE_MS);
    expect(banner()).toBeNull();
    expect(reads).toHaveLength(2);
  });

  it("running, then done: the banner goes, every cached view is refreshed once, and the pace returns to 60 s", async () => {
    let n = 0;
    const { reads } = server(() => (n++ < 2 ? catchupRunning() : catchupDone()));
    const { invalidate } = mount();
    await advance(0);
    expect(banner()).not.toBeNull();
    expect(invalidate).not.toHaveBeenCalled();
    await advance(POLL_RUNNING_MS);
    expect(banner()).not.toBeNull();
    await advance(POLL_RUNNING_MS);
    expect(banner()).toBeNull();
    expect(invalidate).toHaveBeenCalledTimes(1);
    expect(invalidate).toHaveBeenCalledWith(); // every query, as the old banner did
    expect(reads).toHaveLength(4); // the third read said done; the refresh of every view read it once more
    await advance(POLL_RUNNING_MS * 4);
    expect(reads).toHaveLength(4); // back to the idle pace
    await advance(POLL_IDLE_MS);
    expect(reads).toHaveLength(5);
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it("idle from the start: no refresh of the other views", async () => {
    server(catchupDone);
    const { invalidate } = mount();
    await advance(POLL_IDLE_MS);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("no /api/catchup on the server (404): renders nothing and stops polling", async () => {
    const { reads } = server(() => ({ status: 404, body: { ok: false, error: "not found" } }));
    mount();
    await advance(POLL_IDLE_MS * 3);
    expect(banner()).toBeNull();
    expect(reads).toHaveLength(1);
  });
});
