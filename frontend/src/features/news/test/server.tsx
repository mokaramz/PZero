/** A fake backend for the News page tests: answers the four News reads (`GET news`, `news/weekly`,
 *  `news/sources?window=`, `news/refresh_status`) from the invented payloads in ./fixtures and the three writes (028b:
 *  `POST news/outcome`, `news/audit_miss`, `news/backcast`) with the old success shapes, records every call, and lets a
 *  test give its own answer. Anything else — the 028c refresh included — is a 404. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import type { NewsPayload, RefreshStatus, SourcesPayload, Weekly, Window } from "../model/types";
import NewsPage from "../NewsPage";
import { news, refreshStatus, sources, weekly, writeAnswer, WRITE_PATHS, type WriteCase } from "./fixtures";

type Body = Record<string, unknown>;
export type Call = { method: string; path: string; body?: Body };
export type Answer = { status: number; body: unknown };

export type Routes = {
  news?: () => NewsPayload | Answer;
  weekly?: () => Weekly | Answer;
  sources?: (window: string) => SourcesPayload | Answer;
  refreshStatus?: () => RefreshStatus | Answer;
  outcome?: (body: Body) => unknown;
  auditMiss?: (body: Body) => unknown;
  backcast?: (body: Body) => unknown;
};

const isAnswer = (x: unknown): x is Answer => !!x && typeof x === "object" && "status" in x && "body" in x && Object.keys(x).length === 2;
const WINDOWS = ["30", "90", "180", "all"];

export function fakeServer(routes: Routes = {}) {
  const calls: Call[] = [];
  const json = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  const reply = (x: unknown) => (isAnswer(x) ? json(x.status, x.body) : json(200, x));
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? (JSON.parse(String(init.body)) as Body) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    const p = url.pathname;
    if (method === "GET" && p === "/api/news") return reply(routes.news?.() ?? news());
    if (method === "GET" && p === "/api/news/weekly") return reply(routes.weekly?.() ?? weekly());
    if (method === "GET" && p === "/api/news/sources") {
      const w = url.searchParams.get("window") ?? "90";
      return reply(routes.sources?.(w) ?? sources((WINDOWS.includes(w) ? w : "90") as Window));
    }
    if (method === "GET" && p === "/api/news/refresh_status") return reply(routes.refreshStatus?.() ?? refreshStatus());
    if (method === "POST") {
      const b = body ?? {};
      if (p === "/api/news/outcome")
        return reply(
          routes.outcome?.(b) ?? {
            ...writeAnswer(String(b.decision) as WriteCase),
            event_id: b.event_id,
          },
        );
      if (p === "/api/news/audit_miss") return reply(routes.auditMiss?.(b) ?? writeAnswer("audit_miss"));
      if (p === "/api/news/backcast") return reply(routes.backcast?.(b) ?? writeAnswer("backcast"));
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    gets: () => calls.filter((c) => c.method === "GET").map((c) => c.path),
    posts: () => calls.filter((c) => c.method !== "GET"),
    /** how often the stories were read (a successful write reads them again) */
    reads: () => calls.filter((c) => c.method === "GET" && c.path === "/api/news").length,
    /** every request that is not a GET, and every GET of a write or bridge path */
    writes: () => calls.filter((c) => c.method !== "GET" || WRITE_PATHS.test(c.path)),
  };
}

export function renderPage(path = "/news") {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
  const router = createMemoryRouter([{ path: "/news", element: <NewsPage /> }], { initialEntries: [path] });
  const view = render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { qc, router, ...view };
}
