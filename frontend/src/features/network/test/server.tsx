/** A fake backend for the Network and Watchlist page tests: answers the reads, keeps the writes it accepts, records every call. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import WatchlistPage from "@/features/watchlist/WatchlistPage";
import NetworkPage from "../NetworkPage";
import type { GraphPayload, PeoplePayload, Person, PersonSaveBody, TalentedBody } from "../model/types";
import { graph, peoplePayload, PIPE, TODAY } from "./fixtures";

export type Call = { method: string; path: string; body?: Record<string, unknown> };
type Answer = { status: number; body: unknown };

export type Routes = {
  save?: (body: PersonSaveBody, db: PeoplePayload) => Answer | undefined;
  talented?: (body: TalentedBody) => Answer | undefined;
  /** replaces the people the server lists */
  people?: Person[];
  /** replaces the talent forest */
  graph?: GraphPayload;
  watchLog?: (body: { id: string; note: string }) => Answer | undefined;
};

const slugOf = (name: string) =>
  "p-" +
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");

/** The default save (review 013 decision a): an edit merges into its person (404 when unknown), an add whose generated
 *  id is taken is a 409 duplicate, any other add is created. */
function defaultSave(body: PersonSaveBody, db: PeoplePayload): Answer {
  if (body.id) {
    const p = db.people.find((x) => x.id === body.id);
    if (!p) return { status: 404, body: { ok: false, error: "unknown person — nothing was changed" } };
    Object.assign(p, body);
    return { status: 200, body: { ok: true, id: p.id } };
  }
  const id = slugOf(String(body.name ?? ""));
  if (db.people.some((x) => x.id === id))
    return { status: 409, body: { ok: false, duplicate: true, id, error: "a person with this name is already in your network — open them to edit" } };
  db.people.push({ ...(body as Partial<Person>), id, name: String(body.name) } as Person);
  return { status: 200, body: { ok: true, id } };
}

export function fakeServer(routes: Routes = {}) {
  const db = peoplePayload();
  if (routes.people) db.people = routes.people;
  const calls: Call[] = [];
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    if (method === "GET" && url.pathname === "/api/network/people") return json(200, structuredClone(db));
    if (method === "GET" && url.pathname === "/api/network/graph") return json(200, routes.graph ?? graph());
    if (method === "GET" && url.pathname === "/api/network/watchlist") return json(200, { people: structuredClone(db.people.filter((p) => p.watch)) });
    if (method === "GET" && url.pathname === "/api/conviction/pipeline") return json(200, PIPE);
    if (method === "POST" && url.pathname === "/api/network/person_save") {
      const a = routes.save?.(body as PersonSaveBody, db) ?? defaultSave(body as PersonSaveBody, db);
      return json(a.status, a.body);
    }
    if (method === "POST" && url.pathname === "/api/network/talented") {
      const b = body as TalentedBody;
      const a = routes.talented?.(b) ?? { status: 200, body: { ok: true, created: b.persons.map((x) => slugOf(x.name)) } };
      return json(a.status, a.body);
    }
    if (method === "POST" && url.pathname === "/api/network/watch_log") {
      const a = routes.watchLog?.(body as { id: string; note: string });
      if (a) return json(a.status, a.body);
      const p = db.people.find((x) => x.id === body?.id);
      if (!p) return json(404, { ok: false, error: "unknown person" });
      if (body?.note) p.notes = `${p.notes ?? ""}\n[${TODAY} signal] ${String(body.note)}`.trim();
      p.last_checked = TODAY;
      return json(200, { ok: true });
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    db,
    calls,
    posts: (path?: string) => calls.filter((c) => c.method === "POST" && (!path || c.path === `/api/network/${path}`)),
    reads: (path: string) => calls.filter((c) => c.method === "GET" && c.path === path).length,
  };
}

/** `matchMedia` for the layout switch: `wide` is whether "(min-width: 1240px)" matches. */
export function setWide(wide: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: wide && query.includes("min-width: 1240px"),
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })),
  );
}

function renderAt(url: string, element: ReactNode, path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path, element },
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

export const renderNetwork = (url = "/network") => renderAt(url, <NetworkPage />, "/network");
export const renderWatchlist = (url = "/watchlist") => renderAt(url, <WatchlistPage />, "/watchlist");
