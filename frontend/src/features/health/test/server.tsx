/** A fake backend for the System health page tests: answers the two reads the page makes (`GET system_health`,
 *  `GET system_health_overview`) from the invented payloads in ./fixtures, records every call, and lets a test give its
 *  own answer (a payload, or `{status, body}`), or hold a read pending. Anything else is a 404. The page has no write. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { Landed } from "@/features/today/test/Landed";
import HealthPage from "../HealthPage";
import type { Health, Overview } from "../model/types";
import { health, overview } from "./fixtures";

export type Call = { method: string; path: string };
export type Answer = { status: number; body: unknown };

export type Routes = {
  health?: () => Health | Answer;
  overview?: () => Overview | Answer;
  /** keep the overview read pending (its loading state) */
  holdOverview?: boolean;
};

const isAnswer = (x: unknown): x is Answer => !!x && typeof x === "object" && "status" in x && "body" in x && Object.keys(x).length === 2;

export function fakeServer(routes: Routes = {}) {
  const calls: Call[] = [];
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const reply = (x: unknown) => (isAnswer(x) ? json(x.status, x.body) : json(200, x));
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    calls.push({ method, path: url.pathname + url.search });
    if (method === "GET" && url.pathname === "/api/system_health") return reply(routes.health?.() ?? health());
    if (method === "GET" && url.pathname === "/api/system_health_overview") {
      if (routes.holdOverview) return new Promise<Response>(() => {});
      return reply(routes.overview?.() ?? overview());
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    gets: () => calls.filter((c) => c.method === "GET").map((c) => c.path),
    writes: () => calls.filter((c) => c.method !== "GET"),
  };
}

export function renderPage(path = "/health") {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: "/health", element: <HealthPage /> },
      { path: "*", element: <Landed /> },
    ],
    { initialEntries: [path] },
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
