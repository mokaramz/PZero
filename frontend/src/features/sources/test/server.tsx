/** A fake backend for the Sources page tests: answers `GET sources` from a payload it keeps, applies the toggles it
 *  accepts, records every call. A test can give its own answer for a toggle (a refusal, or one it holds back to watch
 *  the optimistic flip). The sources, lists and report rows are invented. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import type { Source, SourcesPayload } from "../model/types";
import SourcesPage from "../SourcesPage";

export type Call = { method: string; path: string; body?: Record<string, unknown> };
export type Answer = { status: number; body: unknown };
type Body = Record<string, unknown>;

export type Routes = {
  /** an answer replaces the default; a promise holds the toggle back until it settles (undefined → the default) */
  toggle?: (body: Body) => Answer | Promise<Answer | undefined> | undefined;
};

/** Five sources, one per health state, across Europe (DACH, NORD, UK) and North America (US, CA):
 *  - Alpine Grant Board (DACH): healthy, feedback active (+2)
 *  - Fjord Accelerator Feed: one recent failure (warn), feedback not yet active
 *  - Harbor Lab Spinouts (US): three failures in a row (failed), notes say it is partial
 *  - Maple Seed Registry (CA): never scanned (warn)
 *  - Quiet Ridge Watcher (UK): disabled */
export function sources(): Source[] {
  return [
    {
      id: "s-alpine",
      name: "Alpine Grant Board (DACH)",
      url: "https://grants.example.org/alpine/awards",
      kind: "api",
      parser: "json_awards",
      geo: ["DACH", "EU"],
      sectors: ["ai", "robotics", "energy"],
      stage: "pre_company",
      reliability: "high",
      freshness: "weekly",
      enabled: true,
      last_scan: "2026-11-11 07:30",
      last_ok: "2026-11-11 07:30",
      last_result_count: 14,
      failures_in_row: 0,
      yield: { kept: 3, research: 5, rejected: 6 },
      geo_scope: "country",
      notes: "Public award list of a regional deep-tech grant.",
      quality: { candidates_found: 20, attention_queue: 8, researched: 6, kept: 3, radar: 2, sent_to_omar: 2, omar_positive: 1, omar_negative: 1 },
      feedback: { adjustment: 2, reviewed: 7, active: true, label: "Feedback", reason: "4 kept of 7 reviewed" },
    },
    {
      id: "s-fjord",
      name: "Fjord Accelerator Feed",
      url: "https://fjord-accel.example.net/feed.xml",
      kind: "rss",
      geo: ["NORD"],
      sectors: ["climate"],
      reliability: "medium",
      enabled: true,
      last_ok: "2026-11-09 18:05",
      last_result_count: 4,
      failures_in_row: 1,
      quality: { candidates_found: 5, kept: 1 },
      feedback: { adjustment: 0, reviewed: 2, active: false, reason: "2 of 5 reviewed" },
    },
    {
      id: "s-harbor",
      name: "Harbor Lab Spinouts",
      url: "http://harbor-lab.example.com/spinouts",
      kind: "watcher",
      geo: ["US"],
      sectors: ["bio"],
      reliability: "low",
      enabled: true,
      last_ok: "2026-10-30 09:00",
      failures_in_row: 3,
      notes: "Lists only a partial cohort; older entries load lazily.",
    },
    { id: "s-maple", name: "Maple Seed Registry", kind: "dataset", geo: ["CA"], sectors: ["ai"], reliability: "high", enabled: true, last_ok: null },
    { id: "s-ridge", name: "Quiet Ridge Watcher", kind: "watcher", geo: ["UK"], sectors: ["fintech"], enabled: false, last_ok: "2026-09-01 10:00" },
  ];
}

export function payload(list: Source[] = sources()): SourcesPayload {
  return {
    sources: list,
    geos: ["DACH", "NORD", "UK", "US", "CA"],
    geo_label: { DACH: "DACH", NORD: "Nordics", UK: "United Kingdom", US: "United States", CA: "Canada" },
    sectors: ["ai", "robotics"],
    sector_label: { ai: "AI", robotics: "Robotics" },
    // DACH: strong AI, weak robotics with more potential; NORD: ok AI, none robotics (potential only); UK: none at all;
    // US: ok-boundary 2.0 / strong-boundary 4.0; CA: weak 0.5
    verified: { DACH: { ai: 4.5, robotics: 1 }, NORD: { ai: 2.5, robotics: 0 }, US: { ai: 2, robotics: 4 }, CA: { ai: 0.5 } },
    potential: { DACH: { ai: 4.5, robotics: 3 }, NORD: { ai: 2.5, robotics: 1.5 }, US: { ai: 2, robotics: 4 }, CA: { ai: 0.5 } },
    cells: {},
    feedback_label: "Feedback-adjusted sourcing priority",
    feedback_min_reviewed: 5,
    feedback_cap: 3,
    ws_geos: { eu: ["DACH", "NORD", "UK", "EU"], na: ["US", "CA"], un: [] },
    report: [
      { source: "Alpine Grant Board — award list", status: "ok", note: "14 rows parsed", geo: ["DACH"] },
      { source: "Fjord Accelerator Feed", status: "fail", note: "feed timed out" },
      { source: "Harbor Lab Spinouts (watcher)", status: "skipped", note: "page unchanged" },
    ],
    manual_sources: [
      { name: "Lakeside founder dinners", url: "https://dinners.example.org", how: "Ask two hosts each month who is leaving to build." },
      { name: "Workshop alumni list", url: "https://alumni.example.org", how: "Read the new alumni bios after each cohort." },
    ],
    pages: [{ name: "Cedar Institute ventures page", url: "https://cedar.example.edu/ventures", archetypes: [3, 7] }],
    feeds: [{ name: "Northwind funding news", url: "https://northwind.example.com/rss" }],
  };
}

export function fakeServer(routes: Routes = {}, initial: SourcesPayload = payload()) {
  const data = structuredClone(initial);
  const calls: Call[] = [];
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? (JSON.parse(String(init.body)) as Body) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    if (method === "GET" && url.pathname === "/api/sources") return json(200, structuredClone(data));
    if (method === "POST" && url.pathname === "/api/sources/toggle") {
      const own = await routes.toggle?.(body ?? {});
      if (own) return json(own.status, own.body);
      data.sources = data.sources.map((s) => (s.id === body?.id ? { ...s, enabled: Boolean(body?.enabled) } : s));
      return json(200, { ok: true });
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    toggles: () => calls.filter((c) => c.method === "POST" && c.path === "/api/sources/toggle").map((c) => c.body),
    reads: () => calls.filter((c) => c.method === "GET" && c.path === "/api/sources").length,
    /** what the server holds now (what the next read returns) */
    stored: () => structuredClone(data),
  };
}

export function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter([{ path: "/sources", element: <SourcesPage /> }], { initialEntries: ["/sources"] });
  const view = render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { qc, router, ...view };
}
