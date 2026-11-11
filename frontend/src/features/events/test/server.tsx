/** A fake backend for the Events page tests: answers the four reads (and the people slice), records every call. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import EventsPage from "../EventsPage";
import type { EventsPayload } from "../model/types";
import { eventsPayload, health, missions, wsig } from "./fixtures";

export type Call = { method: string; path: string; body?: unknown };

export function fakeServer(payload: EventsPayload = eventsPayload()) {
  const calls: Call[] = [];
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    calls.push({ method, path: url.pathname + url.search, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (method !== "GET") return json(404, { ok: false, error: "not found" });
    if (url.pathname === "/api/events") return json(200, structuredClone(payload));
    if (url.pathname === "/api/events/health") return json(200, health());
    if (url.pathname === "/api/events/wsig") return json(200, wsig(url.searchParams.get("days") ?? "14"));
    if (url.pathname === "/api/events/weekend") return json(200, missions());
    if (url.pathname === "/api/network/people")
      return json(200, { people: [{ id: "p-rhea", name: "Rhea Testperson", role: "Founder", location: "Berlin, Germany" }], strengths: {}, potential: {} });
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    writes: () => calls.filter((c) => c.method !== "GET"),
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
