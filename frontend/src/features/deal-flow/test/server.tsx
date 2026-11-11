/** A fake backend for the Deal Flow page tests: answers the GETs the page makes and records every request. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ScoutIntakeRedirect } from "@/app/redirects";
import { ToastProvider } from "@/components/Toast";
import DealFlowPage from "../DealFlowPage";
import type { TriagePayload } from "../model/triage";
import type { InboxPayload } from "../model/types";

export type Call = { method: string; path: string; body?: unknown };
type Answer = { status: number; body: unknown } | Promise<{ status: number; body: unknown }>;

export type Routes = {
  /** each inbox read (the first load and every refetch) */
  inbox: (n: number) => InboxPayload | Promise<InboxPayload>;
  triage?: () => TriagePayload | null;
  candidate?: (id: string, ns: string) => Answer;
  decide?: (id: string, body: Record<string, unknown>) => Answer;
};

export function fakeServer(routes: Routes) {
  const calls: Call[] = [];
  let inboxReads = 0;
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const path = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path, body });
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
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    posts: () => calls.filter((c) => c.method === "POST"),
    inboxReads: () => inboxReads,
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
