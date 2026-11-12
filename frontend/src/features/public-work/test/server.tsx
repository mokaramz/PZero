/** A fake backend for the Public work page tests: answers `GET content` from a list it keeps, applies the saves and
 *  deletes it accepts, records every call. A test can give its own answer for a write (a refusal). The items are
 *  invented. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import type { Item } from "../model/item";
import PublicWorkPage from "../PublicWorkPage";

export type Call = { method: string; path: string; body?: Record<string, unknown> };
export type Answer = { status: number; body: unknown };
type Body = Record<string, unknown>;

export type Routes = {
  save?: (body: Body) => Answer | undefined;
  delete?: (body: Body) => Answer | undefined;
};

/** Three items: a published one with a url and inbound, a draft with only notes, and one with an unknown platform and
 *  kind. */
export function items(): Item[] {
  return [
    {
      id: "w-1",
      title: "What a gearbox line taught me about agents",
      platform: "linkedin",
      kind: "published",
      url: "https://example.com/posts/gearbox-agents",
      inbound: "Two DMs from plant engineers",
      notes: "repost in spring",
      created: "2026-10-02",
    },
    { id: "w-2", title: "Vision QA on the paint shop", platform: "blog", kind: "draft", notes: "needs a diagram", created: "2026-10-20" },
    { id: "w-3", title: "Predictive maintenance myths", platform: "mastodon", kind: "someday", created: "2026-11-01" },
  ];
}

export function fakeServer(routes: Routes = {}, initial: Item[] = items()) {
  let list = structuredClone(initial);
  let seq = 0;
  const calls: Call[] = [];
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? (JSON.parse(String(init.body)) as Body) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    if (method === "GET" && url.pathname === "/api/content") return json(200, { items: structuredClone(list), updated: "2026-11-12" });
    if (method === "POST" && url.pathname === "/api/content/save") {
      const own = routes.save?.(body ?? {});
      if (own) return json(own.status, own.body);
      const b = (body ?? {}) as Partial<Item>;
      const id = b.id ?? `w-new-${++seq}`;
      const prev = list.find((x) => x.id === id);
      const next = { ...prev, ...b, id } as Item;
      list = prev ? list.map((x) => (x.id === id ? next : x)) : [...list, { ...next, created: "2026-11-12" }];
      return json(200, { ok: true, id });
    }
    if (method === "POST" && url.pathname === "/api/content/delete") {
      const own = routes.delete?.(body ?? {});
      if (own) return json(own.status, own.body);
      list = list.filter((x) => x.id !== body?.id);
      return json(200, { ok: true });
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    posts: (name: "save" | "delete") => calls.filter((c) => c.method === "POST" && c.path === `/api/content/${name}`).map((c) => c.body),
    reads: () => calls.filter((c) => c.method === "GET" && c.path === "/api/content").length,
    /** what the server holds now (what the next read returns) */
    stored: () => structuredClone(list),
  };
}

export function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter([{ path: "/public-work", element: <PublicWorkPage /> }], { initialEntries: ["/public-work"] });
  const view = render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return { qc, router, ...view };
}
