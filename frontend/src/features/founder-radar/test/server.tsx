/** A fake backend for the Founder Radar page tests: answers `GET founder-radar` and `POST founder-radar/proposals` from
 *  the fixtures, answers every write with the old answers (simplified, nothing is applied), and records every call. A
 *  test can give its own answer for any endpoint (a refusal, a 400). Every name is invented. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { Elsewhere } from "./Elsewhere";
import FounderRadarPage from "../FounderRadarPage";
import type { FounderRadar, Proposals } from "../model/types";
import { BOREALIS, KELPWISE, borealis, kelpwise, radar } from "./fixtures";

export type Req = { method: string; path: string; body?: Record<string, unknown> };
export type Answer = { status: number; body: unknown };
type Body = Record<string, unknown>;

export type Endpoint =
  | "action"
  | "import"
  | "company"
  | "promote"
  | "boardy_brief"
  | "proposals"
  | "pair"
  | "review"
  | "person_save"
  | "scan"
  | "research"
  | "research_queue";
/** an answer replaces the default handling of that endpoint; `radar_after_scan` is what `GET founder-radar` answers from
 *  the `after_scan_reads`-th read after a scan on (default: the first) */
export type Routes = Partial<Record<Endpoint, (body: Body) => Answer | undefined>> & {
  radar?: FounderRadar;
  proposals_of?: Record<string, Proposals>;
  radar_after_scan?: FounderRadar;
  after_scan_reads?: number;
};

const ok = (body: Body = {}): Answer => ({ status: 200, body: { ok: true, ...body } });
export const refuse = (error: string, extra: Body = {}): Answer => ({ status: 200, body: { ok: false, error, ...extra } });

export const IMPORT_NOTE =
  "imported as identity-unresolved records with import provenance (official LinkedIn Connections export) — nothing was scanned from LinkedIn, nothing was verified or promoted";
export const BRIEF = "Intro request for Oskar Lindqvist — public evidence only.";
export const NO_BOARDY_API = "No Boardy API — paste this into Boardy yourself.";
/** the scan time a synchronous scan answers */
export const SCANNED_AT = "2026-11-12 09:30";

export function fakeServer(routes: Routes = {}) {
  const data = routes.radar ?? radar();
  const proposals: Record<string, Proposals> = routes.proposals_of ?? { [KELPWISE]: kelpwise(), [BOREALIS]: borealis() };
  const calls: Req[] = [];
  let queueCalls = 0;
  let readsAfterScan = -1; // -1: no scan yet
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  /** The old answers. An unknown `state` is the new 400 (decision f); merge asks for confirmation first. */
  const defaults: Record<Endpoint, (b: Body) => Answer> = {
    action: (b) => {
      if (!data.people.some((p) => p.id === b.id)) return refuse("unknown person");
      if (b.action === "state" && !(data.states ?? []).includes(String(b.state)))
        return { status: 400, body: { ok: false, error: `state must be one of: ${(data.states ?? []).join(", ")}` } };
      if (b.action === "merge" && !b.confirm) return refuse("merge refused: identity evidence supports a merge — confirm it", { needs_confirmation: true });
      return ok({ person: {} });
    },
    import: () => ok({ format: "linkedin_connections", rows: 3, new: 3, merged: 0, skipped: [], note: IMPORT_NOTE }),
    company: () => ok(),
    promote: () => ok({ person: {}, error: null }),
    boardy_brief: () => ok({ brief: BRIEF, sent: false, note: NO_BOARDY_API }),
    proposals: (b) => ({ status: 200, body: proposals[String(b.key)] ?? { ok: true, groups: [], recommended: [], summary: {}, history: [] } }),
    pair: () => ok({ pairing: {} }),
    review: (b) =>
      ok({ facts: ["founded", "funding"], identity_bound: b.bindings && Object.keys(b.bindings as Body).length ? [{ name: "Mira Talvik" }] : [], still_pending: [], conflicts: [], refused: [] }),
    person_save: (b) => ok({ id: b.id }),
    scan: () => ({ status: 200, body: { ...data.health, scan_time: SCANNED_AT } }),
    research: (b) => ok({ researched: [{ key: String(b.key ?? ""), name: "Kelpwise GmbH", ok: true, pages: 5, proposals: 9, new: 0 }] }),
    research_queue: () =>
      ++queueCalls === 1
        ? ok({ processed: [{ name: "Kelpwise GmbH", ok: true, pages: 5, proposals: 9 }], done: 1, remaining: 1, failed: {}, skipped_no_domain: ["Grainline Labs"], in_progress: true, resume: true })
        : ok({
            processed: [{ name: "Quillstone AI", ok: false, error: "HTTP 404" }],
            done: 2,
            remaining: 0,
            failed: { "dom:quillstone.example": "HTTP 404" },
            skipped_no_domain: ["Grainline Labs"],
            in_progress: false,
            resume: false,
          }),
  };

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? (JSON.parse(String(init.body)) as Body) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    if (method === "GET" && url.pathname === "/api/founder-radar") {
      const after = routes.radar_after_scan && readsAfterScan >= 0 && ++readsAfterScan >= (routes.after_scan_reads ?? 1);
      return json(200, structuredClone(after ? routes.radar_after_scan : data));
    }
    const m = url.pathname.match(
      /^\/api\/(?:founder-radar\/(action|import|company|promote|boardy_brief|proposals|pair|review|scan|research|research_queue)|network\/(person_save))$/,
    );
    if (method === "POST" && m) {
      const name = (m[1] ?? m[2]) as Endpoint;
      if (name === "scan") readsAfterScan = 0;
      const b = body ?? {};
      const a = routes[name]?.(b) ?? defaults[name](b);
      return json(a.status, structuredClone(a.body));
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    data,
    calls,
    /** every write (the proposals read goes through POST too, so it is left out) */
    writes: () => calls.filter((c) => c.method === "POST" && c.path !== "/api/founder-radar/proposals"),
    posts: (endpoint: string) => calls.filter((c) => c.method === "POST" && c.path.endsWith(`/${endpoint}`)),
  };
}

export function renderPage(path = "/founder-radar") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/founder-radar", element: <FounderRadarPage /> },
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
