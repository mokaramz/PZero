/** A fake backend for the Ecosystems page tests: answers `GET ecosystems/coverage`, `GET ecosystems/registry` and
 *  `GET ecosystems/eco?city=` from payloads it keeps, applies the adoptions it accepts, records every call. A test can
 *  give its own answer for an adoption (a refusal). The ecosystems, cities, companies, people and institutions are
 *  invented; only the home city is the app's own default. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import EcosystemsPage from "../EcosystemsPage";
import type { CityPage, CityRegistry, Coverage, CovSource } from "../model/types";

export type Call = { method: string; path: string; body?: Record<string, unknown> };
export type Answer = { status: number; body: unknown };
type Body = Record<string, unknown>;

export type Routes = {
  /** an answer replaces the default adoption */
  adopt?: (body: Body) => Answer | undefined;
};

const src = (n: number, extra: Partial<CovSource> = {}): CovSource => ({
  id: `src-${n}`,
  name: `Watcher ${n}`,
  origin: "discovery",
  retrieved: true,
  productive: true,
  last_ok: "2026-11-10 08:00",
  failing: false,
  declared_by: "source metadata",
  ...extra,
});

/** Three ecosystems over three families:
 *  - Alderwick (Westmark · North): PARTIAL — founder formation GAP with two audit candidates, emerging companies
 *    HEALTHY with nine sources (one past the eight shown), spinouts UNKNOWN (never retrieved, one failing); audited GAP
 *  - Brightmoor (Eastland): HEALTHY, no spinouts family, never retrieved, no audit
 *  - Cobbleton (Westmark · South): GAP everywhere */
export function coverage(): Coverage {
  return {
    generated: "2026-11-12 07:00",
    families: [
      ["founder_formation", "Founder formation / talent exits"],
      ["emerging_companies", "Emerging companies / first funding"],
      ["spinouts", "Universities / research spinouts"],
    ],
    ecosystems: [
      {
        id: "eco-alderwick",
        city: "Alderwick",
        country: "XA",
        country_name: "Westmark",
        region: "North",
        overall: "PARTIAL",
        label: "12 FINDINGS — COVERAGE PARTIAL",
        families: {
          founder_formation: {
            state: "GAP",
            why: "no source configured",
            configured: 0,
            retrieved: 0,
            productive: 0,
            sources: [],
            candidates: [
              {
                id: "cand-aw-guild",
                name: "Alderwick Founder Guild",
                url: "https://guild.example.org/members",
                access_mode: "html",
                source_type: "community page",
                status: "CANDIDATE — not activated",
              },
              {
                id: "cand-aw-alumni",
                name: "Alderwick Alumni Board",
                url: "https://alumni.example.org/board",
                access_mode: "html",
                access_limitations: "rate limited",
                source_type: "alumni list",
              },
            ],
          },
          emerging_companies: {
            state: "HEALTHY",
            why: "2 fresh retrievals; 5 records in 120 days",
            configured: 9,
            retrieved: 2,
            productive: 1,
            sources: [src(1), src(2, { productive: false }), ...[3, 4, 5, 6, 7, 8, 9].map((n) => src(n))],
          },
          spinouts: {
            state: "UNKNOWN",
            why: "2 source(s) configured, none run yet",
            configured: 2,
            retrieved: 0,
            productive: 0,
            sources: [
              src(10, { name: "Spinout list", origin: "founder_radar", retrieved: false, productive: false, last_ok: "" }),
              src(11, { name: "Lab news", retrieved: false, productive: false, failing: true, declared_by: "coverage_sources.json" }),
            ],
          },
        },
        families_covered: ["emerging_companies"],
        families_missing: ["founder_formation", "spinouts"],
        last_successful_retrieval: "2026-11-10 08:00",
        audit: { status: "GAP", ecosystem: "Alderwick region", blind_spot: "student founders", source: "audit 2026-10" },
      },
      {
        id: "eco-brightmoor",
        city: "Brightmoor",
        country: "XB",
        country_name: "Eastland",
        region: "",
        overall: "HEALTHY",
        label: "40 FINDINGS — COVERAGE HEALTHY",
        families: {
          founder_formation: { state: "HEALTHY", why: "productive", configured: 3, retrieved: 3, productive: 2, sources: [] },
          emerging_companies: { state: "HEALTHY", why: "productive", configured: 4, retrieved: 4, productive: 4, sources: [] },
        },
        families_covered: ["founder_formation", "emerging_companies"],
        families_missing: [],
      },
      {
        id: "eco-cobbleton",
        city: "Cobbleton",
        country: "XA",
        country_name: "Westmark",
        region: "South",
        overall: "GAP",
        label: "0 FINDINGS — COVERAGE GAP",
        families: {
          founder_formation: { state: "GAP", why: "no source", configured: 0, retrieved: 0, productive: 0, sources: [] },
          emerging_companies: { state: "GAP", why: "no source", configured: 0, retrieved: 0, productive: 0, sources: [] },
          spinouts: { state: "GAP", why: "no source", configured: 0, retrieved: 0, productive: 0, sources: [] },
        },
        families_covered: [],
        families_missing: [],
      },
    ],
    counts: { HEALTHY: 1, PARTIAL: 1, GAP: 1 },
    sources_declared: 14,
    sources_with_override: 3,
    registry_size: 3,
    candidates: { total: 2, adopted: 0 },
    new_ecosystems: [
      { place: "Duneholm", country: "XC", signals: 5, kinds: ["startups", "events"], examples: ["Kestrel Labs", "Duneholm Robot Fair"], action: "add it to ecosystems.json" },
      { place: "Fernvale", signals: 2, kinds: ["people"], examples: ["a founder dinner"], action: "keep watching" },
    ],
    note: "Computed from configured sources and recorded runs.",
    labels: { new: "New ecosystems appearing in your data" },
  };
}

/** Three curated cities (the home city, Alderwick, Brightmoor) and one detected (Cobbleton). */
export function registry(): CityRegistry {
  return {
    cities: [
      {
        name: "Karlsruhe",
        curated: true,
        travel_hours: 0,
        coverage: { startups: 2, events: 2, people: 1, institutions: 2, last_refresh: "2026-11-01" },
        status: { startups: "yes", events: "yes", people: "yes", institutions: "verified" },
      },
      {
        name: "Alderwick",
        curated: true,
        travel_hours: 2.5,
        coverage: { startups: 1, events: 0, people: 0, institutions: 1, last_refresh: "" },
        status: { startups: "yes", events: "none", people: "none", institutions: "verified" },
      },
      {
        name: "Brightmoor",
        curated: true,
        coverage: { startups: 0, events: 0, people: 0, institutions: 0 },
        status: { startups: "none", events: "none", people: "none", institutions: "none" },
      },
      {
        name: "Cobbleton",
        curated: false,
        coverage: { startups: 3, events: 1, people: 0, institutions: 0 },
        status: { startups: "yes", events: "yes", people: "none", institutions: "none" },
      },
    ],
    curated_count: 3,
    detected_count: 1,
    note: "Built from ecosystems.json and your data.",
  };
}

/** The home city's page: two startups (one verified and sent), two events (one unscored), one person, two institutions. */
export function homePage(): CityPage {
  return {
    city: "Karlsruhe",
    travel_hours: 0,
    note: "Home base — relationships here pay off over time.",
    startups: [
      { slug: "kestrel-labs", company: "Kestrel Labs", one_liner: "Robot arms for small workshops", stage: "seed", sent: true, score: 81, verified: true },
      { slug: "otter mill", company: "Otter Mill", one_liner: "Vision QA for bakeries", stage: "pre-seed", score: 55 },
    ],
    events_upcoming: [
      { id: "ev-1", name: "Founder Breakfast", start: "2026-11-20T08:00:00", type_label: "meetup", score: 80 },
      { id: "ev 2", name: "Demo Night", start: "2026-12-03", type_label: "demo day", score: null },
    ],
    events_past: [],
    people: [{ id: "p-1", name: "Robin Example", role: "Founder", company: "Kestrel Labs", next_action: "Ask for the deck" }],
    orgs: [
      { name: "Alder Institute of Technology", kind: "university", city: "Karlsruhe", why: "Robotics faculty", url: "https://ait.example.edu" },
      { name: "Forge Hub", kind: "hub", city: "Karlsruhe", why: "Student founder community", url: "https://forge.example.org" },
    ],
  };
}

/** Any other city has nothing yet; Alderwick's note says it is two and a half hours out, Brightmoor's has no travel time. */
export function cityPage(city: string): CityPage {
  if (city === "Karlsruhe") return homePage();
  const empty: CityPage = { city, travel_hours: null, startups: [], events_upcoming: [], people: [], orgs: [] };
  if (city === "Alderwick") return { ...empty, travel_hours: 2.5, note: "A day trip by train." };
  if (city === "Brightmoor") return { ...empty, note: "No trip planned yet." };
  return empty;
}

export function fakeServer(routes: Routes = {}, initial: { coverage?: Coverage; registry?: CityRegistry } = {}) {
  const cov = structuredClone(initial.coverage ?? coverage());
  const reg = structuredClone(initial.registry ?? registry());
  const adopted = new Map<string, string>();
  const calls: Call[] = [];
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? (JSON.parse(String(init.body)) as Body) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    if (method === "GET" && url.pathname === "/api/ecosystems/coverage") return json(200, structuredClone(cov));
    if (method === "GET" && url.pathname === "/api/ecosystems/registry") return json(200, structuredClone(reg));
    if (method === "GET" && url.pathname === "/api/ecosystems/eco") return json(200, cityPage(url.searchParams.get("city") ?? ""));
    if (method === "POST" && url.pathname === "/api/ecosystems/coverage/adopt") {
      const own = routes.adopt?.(body ?? {});
      if (own) return json(own.status, own.body);
      const id = String(body?.id);
      const known = adopted.get(id);
      if (known) return json(200, { ok: true, already: true, source_id: known });
      const sid = `cov-${id.slice(5)}`;
      adopted.set(id, sid);
      cov.candidates = { ...cov.candidates, adopted: (cov.candidates?.adopted ?? 0) + 1 };
      return json(200, { ok: true, source_id: sid, note: "stays UNKNOWN until a scan retrieves it" });
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    adopts: () => calls.filter((c) => c.method === "POST" && c.path === "/api/ecosystems/coverage/adopt").map((c) => c.body),
    reads: (path: string) => calls.filter((c) => c.method === "GET" && c.path.split("?")[0] === `/api/${path}`).length,
  };
}

export function renderPage(path = "/ecosystems") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter([{ path: "/ecosystems", element: <EcosystemsPage /> }], { initialEntries: [path] });
  const view = render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { qc, router, ...view };
}
