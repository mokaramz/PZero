/** A fake backend for the Events page tests: answers the reads (and the people slice), the five writes and the source
 *  scan, records every call. A write answers `{ok:true}` (save: `{ok:true, id}`) unless the test gives its own answer;
 *  the scan has no default (a test that scans gives its answer, which may be a promise to hold the scan open). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import EventsPage from "../EventsPage";
import type { EventsPayload } from "../model/types";
import { eventsPayload, health, missions, wsig } from "./fixtures";

export type Call = { method: string; path: string; body?: Record<string, unknown> };
export type Answer = { status: number; body: unknown };
type Body = Record<string, unknown>;

export type Routes = {
  save?: (body: Body) => Answer | undefined;
  verify?: (body: Body) => Answer | undefined;
  lead?: (body: Body) => Answer | undefined;
  debrief?: (body: Body) => Answer | undefined;
  scout?: (body: Body) => Answer | undefined;
  find?: (body: Body) => Answer | Promise<Answer>;
};

export const ok = (body: unknown = { ok: true }): Answer => ({ status: 200, body });

export function fakeServer(routes: Routes = {}, payload: EventsPayload = eventsPayload()) {
  const calls: Call[] = [];
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? (JSON.parse(String(init.body)) as Body) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    if (method === "POST") {
      const name = url.pathname.replace("/api/events/", "") as keyof Routes;
      if (name === "find") {
        const a = await (routes.find?.(body ?? {}) ?? { status: 500, body: { ok: false, error: "no scan answer in this test" } });
        return json(a.status, a.body);
      }
      if (!["save", "verify", "lead", "debrief", "scout"].includes(name)) return json(404, { ok: false, error: "not found" });
      const a = routes[name]?.(body ?? {}) ?? (name === "save" ? ok({ ok: true, id: String(body?.id ?? "new-event-id") }) : ok());
      return json(a.status, a.body);
    }
    if (url.pathname === "/api/events") return json(200, structuredClone(payload));
    if (url.pathname === "/api/events/health") return json(200, health());
    if (url.pathname === "/api/events/wsig") return json(200, wsig(url.searchParams.get("days") ?? "14"));
    if (url.pathname === "/api/events/weekend") return json(200, missions());
    if (url.pathname === "/api/events/suggest") return json(200, { parts: { founder_density: 15, network_value: 10 } });
    if (url.pathname === "/api/network/people")
      return json(200, { people: [{ id: "p-rhea", name: "Rhea Testperson", role: "Founder", location: "Berlin, Germany" }], strengths: {}, potential: {} });
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    writes: () => calls.filter((c) => c.method !== "GET"),
    posts: (name: string) => calls.filter((c) => c.method === "POST" && c.path === `/api/events/${name}`).map((c) => c.body),
    reads: (prefix: string) => calls.filter((c) => c.method === "GET" && c.path.startsWith(prefix)).map((c) => c.path),
  };
}

export function renderEvents(url = "/events") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/events", element: <EventsPage /> },
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
