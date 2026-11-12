/** A fake backend for the Radar page tests: answers `GET conviction/radar` and `GET conviction/meta`, records every
 *  call. The companies are the Conviction fixtures' shape (`sig`), with invented names. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { meta, sig } from "@/features/conviction/test/fixtures";
import type { Radar, Signal } from "@/features/conviction/model/types";
import RadarPage from "../RadarPage";

/** A fully verified company: its verified score ranks it, nothing is missing. */
export const verified = (slug: string, score: number, extra: Partial<Signal> = {}): Signal => {
  const s = sig(slug, score + 5, extra);
  return { ...s, verified: { founders: true, traction: true, funding: true }, sc: { ...s.sc, verified: score, missing: [], fully_verified: true, verdict: "INVESTIGATE" } };
};

/** Two filled high-confidence slots, an empty emerging slot, a filled wildcard and one research-queue company; the
 *  conflict-gated list and the watchlist are empty. */
export function radar(): Radar {
  return {
    high: [
      verified("zentro", 82, {
        why_project_a: "Vertical agent for freight brokers",
        why_now_text: "EU customs rules change in 2027",
        founder_signal: "Second-time founder",
        discovery_tier: "manual",
        sources: ["https://www.tech.eu/zentro", "https://sifted.eu/zentro-raise"],
        verify_list: ["cap table", "pilot contracts"],
        twin: "",
        op: { status: "READY", action: "Contact the founder", why: "case prepared", tone: "green", source: "prepared case", score_band: "INVESTIGATE" },
      }),
      verified("lumora", 74, {
        next_action: "Book a call with Lumora",
        op: { status: "INVESTIGATE", action: "Score band says investigate", why: "", tone: "blue", source: "score band", score_band: "INVESTIGATE" },
      }),
    ],
    emerging: [],
    wildcard: [verified("quillo", 70, { archetype: 15 })],
    research_queue: [sig("brindle", 68, { why_project_a: "Strong niche" })],
    gated: [],
    watch: [],
  };
}

export function fakeServer(payload: Radar = radar()) {
  const calls: string[] = [];
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://x");
    calls.push(`${(init?.method ?? "GET").toUpperCase()} ${url.pathname}${url.search}`);
    if (url.pathname === "/api/conviction/radar") return json(200, structuredClone(payload));
    if (url.pathname === "/api/conviction/meta") return json(200, meta());
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls };
}

export function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/radar", element: <RadarPage /> },
      { path: "/conviction", element: <p>conviction page</p> },
    ],
    { initialEntries: ["/radar"] },
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
