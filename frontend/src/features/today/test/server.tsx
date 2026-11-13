/** A fake backend for the Today page tests: answers the two reads the page makes (`GET today`, `GET
 *  conviction/pipeline`) from the invented payloads in ./fixtures, records every call, and lets a test give its own
 *  answer (a payload, or `{status, body}`). Anything else is a 404. Today has no write. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import type { Pipeline } from "@/features/conviction/model/types";
import type { TodayView } from "../model/types";
import TodayPage from "../TodayPage";
import { pipeline, today } from "./fixtures";
import { Landed } from "./Landed";

export type Call = { method: string; path: string };
export type Answer = { status: number; body: unknown };

export type Routes = {
  today?: () => TodayView | Answer;
  pipeline?: () => Pipeline | Answer;
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
    if (method === "GET" && url.pathname === "/api/today") return reply(routes.today?.() ?? today());
    if (method === "GET" && url.pathname === "/api/conviction/pipeline") return reply(routes.pipeline?.() ?? pipeline());
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    gets: () => calls.filter((c) => c.method === "GET").map((c) => c.path),
    writes: () => calls.filter((c) => c.method !== "GET"),
  };
}

export function renderPage(path = "/today") {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: "/today", element: <TodayPage /> },
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
