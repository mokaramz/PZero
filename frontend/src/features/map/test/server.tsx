/** A fake backend for the Map page tests: answers the five Map endpoints and the four side reads (Events, `wsig`,
 *  Network people, the Conviction pipeline) from the invented payloads in ./fixtures, records every call, and lets a
 *  test give its own answer for any of them. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import MapPage from "../MapPage";
import type { GeoDetail, GeoIntel, GeoSearch, MapData } from "../model/types";
import { Elsewhere } from "./Elsewhere";
import { intel, munich, pins, plan } from "./fixtures";

export type Call = { method: string; path: string; body?: Record<string, unknown> };
export type Answer = { status: number; body: unknown };
type Body = Record<string, unknown>;

export type Routes = {
  pins?: () => MapData | Answer;
  intel?: () => GeoIntel | Answer;
  ecosystem?: (city: string) => GeoDetail | Answer | undefined;
  search?: (q: string) => GeoSearch | Answer;
  sourcingDay?: (body: Body) => Answer | undefined;
};

export const EVENT_TYPES = {
  demo_day: "Demo day",
  accelerator: "Accelerator event",
  hackathon: "Hackathon",
  university: "University entrepreneurship",
  founder_meetup: "Founder meetup / pitch night",
  UNKNOWN: "Type not evidenced",
};

const isAnswer = (x: unknown): x is Answer => !!x && typeof x === "object" && "status" in x && "body" in x && Object.keys(x).length === 2;

/** The server's own search: "torvane" (a Deal Flow candidate) belongs to Munich; anything else finds nothing. */
function defaultSearch(q: string): GeoSearch {
  return q.toLowerCase().startsWith("torvane") ? { results: [{ kind: "company", label: "Torvane Systems", city: "Munich", link: "/deal-flow?candidate=cand-torvane" }] } : { results: [] };
}

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
    if (method === "GET" && p === "/api/map/pins") return reply(routes.pins?.() ?? pins());
    if (method === "GET" && p === "/api/map/intel") return reply(routes.intel?.() ?? intel());
    if (method === "GET" && p === "/api/map/ecosystem") {
      const city = url.searchParams.get("city") ?? "";
      const own = routes.ecosystem?.(city);
      if (own) return reply(own);
      if (city.toLowerCase() === "munich") return json(200, munich());
      return json(404, { ok: false, error: `unknown or unplaced ecosystem: ${city}` });
    }
    if (method === "GET" && p === "/api/map/search") return reply((routes.search ?? defaultSearch)(url.searchParams.get("q") ?? ""));
    if (method === "POST" && p === "/api/map/sourcing_day") {
      const own = routes.sourcingDay?.(body ?? {});
      if (own) return reply(own);
      if (body?.city !== "Munich") return json(400, { ok: false, error: `unknown or unplaced ecosystem: ${String(body?.city)}` });
      return json(200, plan(String(body.date)));
    }
    if (method === "GET" && p === "/api/events") return json(200, { events: [], leads: [], types: EVENT_TYPES, dims: {}, dim_order: [] });
    if (method === "GET" && p === "/api/events/wsig") {
      return json(200, { ranked: [{ id: "forge-demo-day", name: "Forge Demo Day & Pitch Night", city: "Karlsruhe", event_score: 82, rank: 1 }] });
    }
    if (method === "GET" && p === "/api/network/people") {
      return json(200, {
        people: [
          { id: "p-mara-lindqvist", name: "Mara Lindqvist", next_action: "Coffee to hear the spin-out plan" },
          { id: "p-ines-halvorsen", name: "Ines Halvorsen", due: true, next_action: "SUGGESTED: follow up within 48h while the conversation is warm" },
        ],
      });
    }
    if (method === "GET" && p === "/api/conviction/pipeline") {
      return json(200, { signals: [{ slug: "fernhollow-materials", company: "Fernhollow Materials", next_action: "Book founder call" }] });
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    gets: () => calls.filter((c) => c.method === "GET").map((c) => c.path),
    posts: () => calls.filter((c) => c.method === "POST"),
    reads: (path: string) => calls.filter((c) => c.method === "GET" && c.path.split("?")[0] === `/api/${path}`).length,
  };
}

export function renderPage(path = "/map") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/map", element: <MapPage /> },
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
