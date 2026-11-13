/** A fake backend for the Investment Desk tests: answers the five reads the page makes (`GET home`, `GET
 *  deal-flow/inbox`, `GET conviction/pipeline`, `GET today`, `GET sources`) and the weekly drawer's `POST
 *  conviction/weekly` from the invented payloads in ./fixtures, records every call, and lets a test give its own answer
 *  (a payload, or `{status, body}`). Anything else is a 404 — the deferred `review_queue` among them. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { Landed } from "@/features/today/test/Landed";
import HomePage from "../HomePage";
import type { HomePayload, Inbox, Pipeline, Sources, TodayView } from "../model/types";
import { home, inbox, pipeline, sources, today } from "./fixtures";

export type Call = { method: string; path: string };
export type Answer = { status: number; body: unknown };

export type Routes = {
  home?: () => HomePayload | Answer;
  inbox?: () => Inbox | Answer;
  pipeline?: () => Pipeline | Answer;
  today?: () => TodayView | Answer;
  sources?: () => Sources | Answer;
  /** hold the inbox until the test calls the returned release */
  holdInbox?: boolean;
};

const isAnswer = (x: unknown): x is Answer => !!x && typeof x === "object" && "status" in x && "body" in x && Object.keys(x).length === 2;

export function fakeServer(routes: Routes = {}) {
  const calls: Call[] = [];
  let release: () => void = () => {};
  const held = routes.holdInbox ? new Promise<void>((r) => (release = r)) : Promise.resolve();
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const reply = (x: unknown) => (isAnswer(x) ? json(x.status, x.body) : json(200, x));
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    calls.push({ method, path: url.pathname + url.search });
    if (method === "GET" && url.pathname === "/api/home") return reply(routes.home?.() ?? home());
    if (method === "GET" && url.pathname === "/api/deal-flow/inbox") {
      await held;
      return reply(routes.inbox?.() ?? inbox());
    }
    if (method === "GET" && url.pathname === "/api/conviction/pipeline") return reply(routes.pipeline?.() ?? pipeline());
    if (method === "GET" && url.pathname === "/api/today") return reply(routes.today?.() ?? today());
    if (method === "GET" && url.pathname === "/api/sources") return reply(routes.sources?.() ?? sources());
    if (method === "POST" && url.pathname === "/api/conviction/weekly") return json(200, { text: "Weekly Sourcing Update — invented week" });
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    release: () => release(),
    gets: () => calls.filter((c) => c.method === "GET").map((c) => c.path),
    writes: () => calls.filter((c) => c.method !== "GET"),
  };
}

export function renderPage(path = "/") {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: "/", element: <HomePage /> },
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
