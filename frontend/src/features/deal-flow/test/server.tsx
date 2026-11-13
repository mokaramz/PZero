/** A fake backend for the Deal Flow page tests: answers the GETs the page makes and records every request. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ScoutIntakeRedirect } from "@/app/redirects";
import { ToastProvider } from "@/components/Toast";
import { fakeWatch, type WatchRoutes } from "@/features/watchlist/test/fakeWatch";
import DealFlowPage from "../DealFlowPage";
import type { TriagePayload } from "../model/triage";
import type { AutoStatus } from "../model/triageAuto";
import type { FindStatus, InboxPayload, ScanHistory } from "../model/types";

export type Call = { method: string; path: string; body?: unknown };
type Answer = { status: number; body: unknown } | Promise<{ status: number; body: unknown }>;

export type Routes = {
  /** each inbox read (the first load and every refetch) */
  inbox: (n: number) => InboxPayload | Promise<InboxPayload>;
  triage?: () => TriagePayload | null;
  candidate?: (id: string, ns: string) => Answer;
  decide?: (id: string, body: Record<string, unknown>) => Answer;
  /** the Conviction scoring tables and save, for Keep (review 011) */
  meta?: () => unknown;
  save?: (body: Record<string, unknown>) => Answer;
  /** the scan (review 034a): each `find_status` read (n counts them), the start, and the history (its `n`) */
  findStatus?: (n: number) => FindStatus | Answer;
  find?: (body: Record<string, unknown>) => Answer;
  scanHistory?: (n: string | null) => ScanHistory | Answer;
  /** machine triage writes (review 035a): accept / override one proposal, and the batch preview / confirm */
  triageDecide?: (body: Record<string, unknown>) => Answer;
  batchReject?: (body: Record<string, unknown>) => Answer;
  /** machine triage after a scan (review 035b): each `triage_auto` read (n counts them), and Retry now */
  triageAuto?: (n: number) => AutoStatus | Answer;
  triageRetry?: (body: Record<string, unknown>) => Answer;
  /** the WATCH view and writes (review 037a); without it `GET /api/watch` is a 404 */
  watch?: WatchRoutes;
};

const isAnswer = (x: unknown): x is { status: number; body: unknown } => !!x && typeof x === "object" && "status" in x && "body" in x;

export function fakeServer(routes: Routes) {
  const calls: Call[] = [];
  let inboxReads = 0;
  let statusReads = 0;
  let autoReads = 0;
  const watch = routes.watch ? fakeWatch(routes.watch) : undefined;
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, body });
    const w = watch?.handle(method, path, body);
    if (w) return json(w.status, w.body);
    if (method === "GET" && path === "/api/deal-flow/inbox") return json(200, await routes.inbox(++inboxReads));
    if (method === "GET" && path === "/api/deal-flow/triage") {
      const t = routes.triage?.();
      return t ? json(200, t) : json(404, { ok: false, error: "not found" });
    }
    const one = /^\/api\/deal-flow\/candidates\/([^/?]+)(?:\?ns=(\w+))?$/.exec(path);
    if (method === "GET" && one && routes.candidate) {
      const a = await routes.candidate(decodeURIComponent(one[1]), one[2] ?? "candidate");
      return json(a.status, a.body);
    }
    const dec = /^\/api\/deal-flow\/candidates\/([^/]+)\/decision$/.exec(path);
    if (method === "POST" && dec && routes.decide) {
      const a = await routes.decide(decodeURIComponent(dec[1]), body);
      return json(a.status, a.body);
    }
    if (method === "GET" && path === "/api/deal-flow/find_status" && routes.findStatus) {
      const a = await routes.findStatus(++statusReads);
      return isAnswer(a) ? json(a.status, a.body) : json(200, a);
    }
    if (method === "POST" && path === "/api/deal-flow/find" && routes.find) {
      const a = await routes.find(body);
      return json(a.status, a.body);
    }
    const hist = /^\/api\/deal-flow\/scan_history(?:\?n=(\d+))?$/.exec(path);
    if (method === "GET" && hist && routes.scanHistory) {
      const a = await routes.scanHistory(hist[1] ?? null);
      return isAnswer(a) ? json(a.status, a.body) : json(200, a);
    }
    if (method === "POST" && path === "/api/deal-flow/triage/decide" && routes.triageDecide) {
      const a = await routes.triageDecide(body);
      return json(a.status, a.body);
    }
    if (method === "POST" && path === "/api/deal-flow/triage/batch_reject" && routes.batchReject) {
      const a = await routes.batchReject(body);
      return json(a.status, a.body);
    }
    if (method === "GET" && path === "/api/deal-flow/triage_auto" && routes.triageAuto) {
      const a = await routes.triageAuto(++autoReads);
      return isAnswer(a) ? json(a.status, a.body) : json(200, a);
    }
    if (method === "POST" && path === "/api/deal-flow/triage_retry" && routes.triageRetry) {
      const a = await routes.triageRetry(body);
      return json(a.status, a.body);
    }
    if (method === "GET" && path === "/api/conviction/meta" && routes.meta) return json(200, routes.meta());
    if (method === "POST" && path === "/api/conviction/save" && routes.save) {
      const a = await routes.save(body);
      return json(a.status, a.body);
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    posts: () => calls.filter((c) => c.method === "POST"),
    inboxReads: () => inboxReads,
    statusReads: () => statusReads,
    autoReads: () => autoReads,
    gets: (p: string) => calls.filter((c) => c.method === "GET" && c.path === p).length,
  };
}

export function renderPage(url = "/deal-flow") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/deal-flow", element: <DealFlowPage /> },
      { path: "/scout-intake", element: <ScoutIntakeRedirect /> },
      { path: "*", element: <p>elsewhere</p> },
    ],
    { initialEntries: [url] },
  );
  const view = render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { qc, router, ...view };
}

/** A promise the test resolves when it wants (to hold a refetch in flight). */
export function gate<T>() {
  let open!: (v: T) => void;
  const promise = new Promise<T>((resolve) => {
    open = resolve;
  });
  return { promise, open };
}
