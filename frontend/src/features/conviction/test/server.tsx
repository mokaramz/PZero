/** A fake backend for the Conviction page tests: answers the reads, keeps the writes it accepts, records every call. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import ConvictionPage from "../ConvictionPage";
import type { CaseView } from "../model/case";
import type { Pipeline, SaveBody } from "../model/types";
import { meta, pipeline, sig } from "./fixtures";

export type Call = { method: string; path: string; body?: Record<string, unknown> };
type Answer = { status: number; body: unknown };

export type Routes = {
  /** the case of a slug; undefined → 404 (the endpoint or the case does not exist yet) */
  case?: (slug: string) => CaseView | undefined;
  save?: (body: SaveBody, db: Pipeline) => Answer | undefined;
  /** the Scout memo / outreach email of a slug; the default is a short text for every listed slug, undefined → 404 */
  memo?: (slug: string) => string | undefined;
  email?: (slug: string) => string | undefined;
  weekly?: (body: Record<string, unknown>) => Answer;
  /** `GET radar.html`; the default is the Radar HTML as a `weekly_memo.html` attachment */
  radarHtml?: () => Response;
};

export const RADAR_HTML = "<!doctype html><title>Radar</title><h1>PROJECT A RADAR — TOP 10</h1>";

const slugOf = (name: string) =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");

/** The default save: an edit merges the body into its entry (the checklist re-scores verified by 10 per tick), a new
 *  name is added, an existing name is a 409 duplicate. */
function defaultSave(body: SaveBody, db: Pipeline): Answer {
  if (body.slug) {
    const e = db.signals.find((x) => x.slug === body.slug);
    if (!e) return { status: 404, body: { ok: false, error: "unknown company" } };
    const before = Object.values(e.verified ?? {}).filter(Boolean).length;
    Object.assign(e, body);
    const after = Object.values(e.verified ?? {}).filter(Boolean).length;
    e.sc = { ...e.sc, verified: e.sc.verified + (after - before) * 10 };
    return { status: 200, body: { ok: true, slug: e.slug } };
  }
  const slug = slugOf(String(body.company ?? ""));
  if (db.signals.some((x) => x.slug === slug))
    return { status: 409, body: { ok: false, duplicate: true, slug, error: "a company with this name already exists — open it in Conviction to edit it" } };
  db.signals.push({ ...sig(slug, 50), ...body, slug, company: String(body.company) } as Pipeline["signals"][number]);
  return { status: 200, body: { ok: true, slug } };
}

export function fakeServer(routes: Routes = {}) {
  const db = pipeline();
  const calls: Call[] = [];
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    if (method === "GET" && url.pathname === "/api/conviction/pipeline") return json(200, structuredClone(db));
    if (method === "GET" && url.pathname === "/api/conviction/meta") return json(200, meta());
    if (method === "GET" && url.pathname === "/api/conviction/case") {
      const c = routes.case?.(url.searchParams.get("slug") ?? "");
      return c ? json(200, c) : json(404, { ok: false, error: "not found" });
    }
    if (method === "GET" && (url.pathname === "/api/conviction/memo" || url.pathname === "/api/conviction/email")) {
      const slug = url.searchParams.get("c") ?? "";
      const e = db.signals.find((x) => x.slug === slug);
      const kind = url.pathname.endsWith("memo") ? "memo" : "email";
      const fallback = e && (kind === "memo" ? `Scout memo — ${e.company}` : `Outreach email to ${e.company}`);
      const answer = routes[kind];
      const text = answer ? answer(slug) : fallback;
      return text === undefined ? json(404, { error: "not found" }) : json(200, { text });
    }
    if (method === "GET" && url.pathname === "/api/conviction/radar.html") {
      return (
        routes.radarHtml?.() ??
        new Response(RADAR_HTML, {
          status: 200,
          headers: { "Content-Type": "text/html; charset=utf-8", "Content-Disposition": 'attachment; filename="weekly_memo.html"' },
        })
      );
    }
    if (method === "POST" && url.pathname === "/api/conviction/weekly") {
      const a = routes.weekly?.(body ?? {}) ?? { status: 200, body: { text: `Weekly Sourcing Update\nInsight: ${String(body?.insight ?? "")}` } };
      return json(a.status, a.body);
    }
    if (method === "POST" && url.pathname === "/api/conviction/save") {
      const a = routes.save?.(body as SaveBody, db) ?? defaultSave(body as SaveBody, db);
      return json(a.status, a.body);
    }
    if (method === "POST" && url.pathname === "/api/conviction/status") {
      const e = db.signals.find((x) => x.slug === body?.slug);
      if (!e) return json(404, { ok: false, error: "unknown company — nothing was changed" });
      e.status = String(body?.status);
      return json(200, { ok: true });
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    db,
    calls,
    posts: () => calls.filter((c) => c.method === "POST"),
    reads: (path: string) => calls.filter((c) => c.method === "GET" && c.path === path).length,
  };
}

export function renderPage(url = "/conviction") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/conviction", element: <ConvictionPage /> },
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
