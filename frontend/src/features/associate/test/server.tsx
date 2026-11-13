/** A fake backend for the PZ Associate page tests: a small in-memory Associate store behind the nine `associate/*`
 *  routes, seeded from the invented payloads in ./fixtures. It records every call with its body, keeps what the page
 *  writes (an ask appends its turn unless the answer says `saved: false`; deletes remove; a draft needs
 *  `confirm: true`), and lets a test give its own answer (a payload, or `{status, body}`) or hold a read or the ask
 *  pending. Anything else is a 404. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { Landed } from "@/features/today/test/Landed";
import AssociatePage from "../AssociatePage";
import type { AskBody, AskRes, Conversation, ConvRow, Draft, Profile, Status } from "../model/types";
import { askOffline, conversation, conversations, drafts, profile, radarConversation, statusOffline } from "./fixtures";

export type Call = { method: string; path: string; body?: unknown };
export type Answer = { status: number; body: unknown };

export type Routes = {
  status?: () => Status | Answer;
  conversations?: () => { conversations: ConvRow[] } | Answer;
  /** the answer to an ask (default: the offline answer, in the asked conversation or a new one) */
  ask?: (body: AskBody) => AskRes | Answer;
  profile?: () => Profile | Answer;
  drafts?: () => { drafts: Draft[] } | Answer;
  holdAsk?: boolean;
  /** the ask waits for this before it answers (a delete while the answer is prepared) */
  askGate?: Promise<unknown>;
  holdConversations?: boolean;
  holdConversation?: boolean;
  holdProfile?: boolean;
  holdDrafts?: boolean;
};

const isAnswer = (x: unknown): x is Answer => !!x && typeof x === "object" && "status" in x && "body" in x && Object.keys(x).length === 2;
const NEW_ID = "c-5e6f7a8b9c0d";

export function fakeServer(routes: Routes = {}) {
  const calls: Call[] = [];
  const store = new Map<string, Conversation>([conversation(), radarConversation()].map((c) => [c.id, c]));
  let index: ConvRow[] = conversations().conversations;
  let draftList: Draft[] = drafts().drafts;
  let prof: Profile = profile();
  let asks = 0;

  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const reply = (x: unknown) => (isAnswer(x) ? json(x.status, x.body) : json(200, x));
  const hold = () => new Promise<Response>(() => {});

  function ask(body: AskBody): AskRes | Answer {
    if (routes.ask) {
      const r = routes.ask(body);
      if (!isAnswer(r)) keep(body, r);
      return r;
    }
    const r = askOffline();
    const id = body.conversation_id || (asks === 0 ? NEW_ID : `c-5e6f7a8b9c${String(asks).padStart(2, "0")}`);
    r.conversation = { id, title: store.get(id)?.title ?? body.message.slice(0, 60) };
    keep(body, r);
    return r;
  }

  /** Phase 3 of the server: append the turn and update the index — unless the answer was not saved. */
  function keep(body: AskBody, r: AskRes) {
    asks++;
    if (r.saved === false || !r.conversation) return;
    const { id, title } = r.conversation;
    const c = store.get(id) ?? { id, title, messages: [] };
    c.messages = [...c.messages, { role: "user", at: "2026-11-13T08:30:00Z", text: body.message, context: body.context ?? null }, r.message];
    c.updated = r.message.at;
    store.set(id, c);
    index = [{ id, title: c.title, updated: c.updated }, ...index.filter((x) => x.id !== id)];
  }

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path: url.pathname + url.search, ...(method === "POST" ? { body } : {}) });
    const route = `${method} ${url.pathname}`;
    switch (route) {
      case "GET /api/associate/status":
        return reply(routes.status?.() ?? statusOffline());
      case "GET /api/associate/conversations":
        if (routes.holdConversations) return hold();
        return reply(routes.conversations?.() ?? { conversations: index });
      case "GET /api/associate/conversation": {
        if (routes.holdConversation) return hold();
        const c = store.get(url.searchParams.get("id") ?? "");
        return c ? json(200, c) : json(404, { ok: false, error: "conversation not found" });
      }
      case "POST /api/associate/ask":
        if (routes.holdAsk) return hold();
        if (routes.askGate) await routes.askGate;
        return reply(ask(body));
      case "POST /api/associate/conversation_delete": {
        const existed = store.delete(body.id);
        index = index.filter((x) => x.id !== body.id);
        return json(200, { ok: existed });
      }
      case "GET /api/associate/profile":
        if (routes.holdProfile) return hold();
        return reply(routes.profile?.() ?? prof);
      case "POST /api/associate/profile": {
        const saved = Object.fromEntries(prof.fields.map((f) => [f.key, String(body[f.key] ?? "").trim()]));
        prof = { ...prof, profile: { ...saved, updated: "2026-11-13T08:45:00Z" } };
        return json(200, { profile: prof.profile });
      }
      case "GET /api/associate/drafts":
        if (routes.holdDrafts) return hold();
        return reply(routes.drafts?.() ?? { drafts: draftList });
      case "POST /api/associate/draft": {
        if (body.confirm !== true) return json(400, { ok: false, error: "saving a draft needs your explicit confirmation (confirm: true)" });
        const d: Draft = { id: "d-1a2b3c4d5e", title: body.title, body: body.body, created: "2026-11-13T08:50:00Z" };
        draftList = [d, ...draftList];
        return json(200, { draft: d });
      }
      case "POST /api/associate/draft_delete": {
        const before = draftList.length;
        draftList = draftList.filter((d) => d.id !== body.id);
        return json(200, { ok: draftList.length !== before });
      }
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    gets: () => calls.filter((c) => c.method === "GET").map((c) => c.path),
    posts: () => calls.filter((c) => c.method === "POST").map((c) => ({ path: c.path, body: c.body })),
    writes: () => calls.filter((c) => c.method !== "GET"),
    reads: (path: string) => calls.filter((c) => c.method === "GET" && c.path === path).length,
    /** what the server holds now */
    index: () => index,
    /** delete a conversation behind the page's back (another tab, or eviction) */
    drop: (id: string) => {
      store.delete(id);
      index = index.filter((x) => x.id !== id);
    },
  };
}

export function renderPage(path = "/associate") {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: "/associate", element: <AssociatePage /> },
      { path: "*", element: <Landed /> },
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
  /** the page's current URL (path + query) */
  const at = () => router.state.location.pathname + router.state.location.search;
  return { qc, router, at, ...view };
}
