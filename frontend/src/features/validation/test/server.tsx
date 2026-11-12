/** A fake backend for the Validation page tests: answers the two Validation reads (`GET validation`,
 *  `GET validation/scout_packet?cycle=`) from the invented payloads in ./fixtures and the five writes (027b) with the
 *  old success shapes, records every call, and lets a test give its own answer. Anything else is a 404. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import type { Packet, ValidationPayload } from "../model/types";
import ValidationPage from "../ValidationPage";
import { Elsewhere } from "./Elsewhere";
import { benchmarkSummary, packet, validation, WRITE_PATHS } from "./fixtures";

export type Call = { method: string; path: string; body?: Record<string, unknown> };
export type Answer = { status: number; body: unknown };

type Body = Record<string, unknown>;
export type Routes = {
  validation?: () => ValidationPayload | Answer;
  scoutPacket?: (cycle: string) => Packet | Answer;
  outcome?: (body: Body) => unknown;
  audit?: (body: Body) => unknown;
  retract?: (body: Body) => unknown;
  benchmarkImport?: (body: Body) => unknown;
  markPacket?: (body: Body) => unknown;
};

/** The written line as the server answers it (`{ok: true, entry}`). */
const written = (prefix: string, body: Body) => ({ ok: true, entry: { id: `${prefix}-0123456789`, recorded_at: "2026-11-12T10:00:00", ...body } });

const isAnswer = (x: unknown): x is Answer => !!x && typeof x === "object" && "status" in x && "body" in x && Object.keys(x).length === 2;

export function fakeServer(routes: Routes = {}) {
  const calls: Call[] = [];
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const reply = (x: unknown) => (isAnswer(x) ? json(x.status, x.body) : json(200, x));
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? (JSON.parse(String(init.body)) as Body) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    const p = url.pathname;
    if (method === "GET" && p === "/api/validation") return reply(routes.validation?.() ?? validation());
    if (method === "GET" && p === "/api/validation/scout_packet") {
      const cycle = url.searchParams.get("cycle") ?? "";
      return reply(routes.scoutPacket?.(cycle) ?? { ...packet(), cycle: cycle || "all" });
    }
    if (method === "POST") {
      const b = body ?? {};
      if (p === "/api/validation/outcome") return reply(routes.outcome?.(b) ?? written("oc", b));
      if (p === "/api/validation/audit") return reply(routes.audit?.(b) ?? written("au", b));
      if (p === "/api/validation/retract") return reply(routes.retract?.(b) ?? written("rx", { target: b.id, reason: b.reason }));
      if (p === "/api/validation/benchmark_import") return reply(routes.benchmarkImport?.(b) ?? { ...benchmarkSummary(), imported: !!b.confirm });
      if (p === "/api/validation/scout_packet") return reply(routes.markPacket?.(b) ?? { ...packet(), cycle: String(b.cycle) || "all" });
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    gets: () => calls.filter((c) => c.method === "GET").map((c) => c.path),
    posts: () => calls.filter((c) => c.method !== "GET"),
    /** the GETs of the page's data (a successful write refreshes it) */
    reads: () => calls.filter((c) => c.method === "GET" && c.path === "/api/validation").length,
    writes: () => calls.filter((c) => c.method !== "GET" || WRITE_PATHS.test(c.path)),
  };
}

export function renderPage(path = "/validation") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/validation", element: <ValidationPage /> },
      { path: "*", element: <Elsewhere /> },
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
