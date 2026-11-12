/** A fake backend for the Active Evaluator page tests: answers `GET evaluator/sessions` and `GET evaluator/session` from
 *  the sessions it keeps, applies the actions it accepts (the old bodies and answers, simplified), answers Conviction's
 *  `imq_trigger`, and records every call. A test can give its own answer for any write (a refusal). Every company,
 *  founder and source is invented. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import EvaluatorPage from "../EvaluatorPage";
import type { Claim, EvaluationsWorkspace, Panel, Question, Session, SessionRow } from "../model/types";

export type Req = { method: string; path: string; body?: Record<string, unknown> };
export type Answer = { status: number; body: unknown };
type Body = Record<string, unknown>;

export type Action = "start" | "deck" | "next" | "skip" | "answer" | "evidence" | "resolve" | "end";
/** an answer replaces the default handling of that endpoint */
export type Routes = Partial<Record<Action | "trigger", (body: Body) => Answer | undefined>> & { sessions?: () => Answer | undefined };

export const TODAY = "2026-11-12";
export const DECK_LABEL = "DECK CLAIM — UNVERIFIED";
export const FOUNDER_LABEL = "FOUNDER-REPORTED — unverified";
const STATES = ["DECK CLAIM", "FOUNDER-REPORTED", "PUBLIC SOURCED FACT", "OPERATOR VERIFIED", "CONTRADICTION", "UNKNOWN"];
export const FAMILIES = [
  { id: "founder_team", label: "Founder & team", dimension: "founder" },
  { id: "traction", label: "Traction", dimension: "insight" },
  { id: "why_now", label: "Why now", dimension: "why_now" },
  { id: "market", label: "Market", dimension: "venture_scale" },
];
const GROUPS: Record<string, string[]> = {
  founder: ["founder_team"],
  market: ["market"],
  why_now: ["why_now"],
  product: [],
  traction: ["traction"],
  timing: [],
  conflict: [],
};
const NO_TRIGGER = "no dated why-now trigger";

const claim = (id: string, family: string, text: string, state: string, extra: Partial<Claim> = {}): Claim => ({
  id,
  family,
  text,
  state,
  created: "2026-11-10 10:00",
  resolved: false,
  evidence: [],
  ...extra,
});

const question = (id: string, family: string, text: string, kind: string, extra: Partial<Question> = {}): Question => ({
  id,
  family,
  text,
  kind,
  reason: `${family} is not covered yet`,
  verification_hint: "—",
  answer: null,
  ...extra,
});

/** Three sessions:
 *  - ev-1 (LIVE, linked to the Conviction company `kestrel-labs`): Kestrel Labs / Ada Quill — a deck, five claims (a
 *    deck claim, a founder-reported one, an open and a resolved contradiction, a public fact), one answered question,
 *    an open challenge, four queued questions and two staged Scout 00 rows (one awaiting the operator);
 *  - ev-2 (ENDED, external): Otter Mill / Ben Rook — with its founder call `call-7`, tasks, follow-ups and memo deltas;
 *  - ev-3 (LIVE, external): Pine Robotics, founder unknown — nothing yet, an opening question. */
export function sessions(): Session[] {
  const ev1: Session = {
    id: "ev-1",
    created: "2026-11-10 10:00",
    updated: "2026-11-11 09:00",
    status: "live",
    subject: { kind: "company", slug: "kestrel-labs", name: "Kestrel Labs", founder: "Ada Quill" },
    context: {
      kind: "company",
      name: "Kestrel Labs",
      founder: "Ada Quill",
      slug: "kestrel-labs",
      provisional: 66,
      verified_score: 40,
      verified: { founders: true, traction: false, funding: false },
      conflict: "none",
      adjacent: [{ name: "Fernley Tools" }, { name: "Gantry AI" }],
      research_facts: { funding: { claim: "Pre-seed round led by a Berlin angel group in 2026" } },
    },
    deck: { text: "…", imported_at: "2026-11-10 10:05", claims: ["c-1"] },
    ledger: [
      claim("c-1", "traction", "Three paid pilots with machine shops", "DECK CLAIM", { label: DECK_LABEL, source: "pitch deck" }),
      claim("c-2", "founder_team", "Built robot arms for eight years", "FOUNDER-REPORTED", { label: FOUNDER_LABEL }),
      claim("c-3", "traction", "Deck says three pilots; the founder says five", "CONTRADICTION"),
      claim("c-4", "market", "Market is 2B; later 200M", "CONTRADICTION", { resolved: true, resolution: { note: "200M is the DACH share" } }),
      claim("c-5", "why_now", "Arm prices fell 40% since 2024", "PUBLIC SOURCED FACT", { evidence: [{ kind: "public", url: "https://tech.eu/arms", label: "tech.eu" }] }),
    ],
    questions: [
      question("q-1", "founder_team", "Why are you the one to build this?", "opening", { answer: "Eight years building arms", answered_at: "2026-11-10 10:10" }),
      question("q-2", "traction", "Which of the pilots pay, and how much?", "challenge", { verification_hint: "invoices or a customer call" }),
    ],
    queue: [
      { kind: "followup", text: "Who signs the pilot contracts?" },
      { kind: "challenge", text: "What happens when a pilot ends?" },
      { kind: "opening", text: "Why is now the moment for this?" },
      { kind: "opening", text: "How big is the first market?" },
    ],
    tasks: [],
    memo_deltas: [],
    ended: null,
    plan: [{ family: "why_now", label: "Why now", priority: 1 }],
    staged_evidence: [
      { claim_id: "c-1", url: "https://sifted.eu/kestrel-pilots", label: "Sifted on the pilots", note: "names two shops", supports: "yes", date: "2026-11-01", job_id: "job-9", state: "awaiting operator" },
      { claim_id: "c-2", url: "https://example.org/old", supports: "no", job_id: "job-8", state: "dismissed" },
    ],
  };
  const ev2: Session = {
    id: "ev-2",
    created: "2026-11-05 14:00",
    updated: "2026-11-05 15:00",
    status: "ended",
    subject: { kind: "external", name: "Otter Mill", founder: "Ben Rook" },
    context: { kind: "external", name: "Otter Mill", founder: "Ben Rook" },
    ledger: [claim("c-21", "traction", "Ten customers", "FOUNDER-REPORTED", { label: FOUNDER_LABEL })],
    questions: [question("q-21", "traction", "Who pays today?", "opening", { answer: "Ten customers" })],
    queue: [],
    tasks: [{ id: "t-1", text: "Verify: Ten customers", how: "public source or operator check", state: "open" }],
    memo_deltas: ["Traction: ten customers (founder-reported)"],
    ended: {
      on: "2026-11-05 15:00",
      call_id: "call-7",
      founder_reported: 1,
      deck_claims: 0,
      unknowns: 0,
      answers: 1,
      ledger_items: 1,
      canonical_answered: 1,
      canonical_sections: 6,
      contradictions: 0,
      tasks: 1,
      followups: ["Ask again: why now?"],
      imq: { state: "not linked to a Conviction company", blockers: [] },
    },
    plan: [],
  };
  const ev3: Session = {
    id: "ev-3",
    created: "2026-11-11 08:00",
    updated: "2026-11-11 08:00",
    status: "live",
    subject: { kind: "external", name: "Pine Robotics", founder: "" },
    context: { kind: "external", name: "Pine Robotics", founder: "" },
    ledger: [],
    questions: [question("q-31", "founder_team", "Why are you the one to build this?", "opening")],
    queue: [],
    tasks: [],
    memo_deltas: [],
    ended: null,
    plan: [{ family: "traction", label: "Traction", priority: 1 }],
  };
  return [ev1, ev2, ev3];
}

/** The old `session_row`. */
export function sessionRow(s: Session): SessionRow {
  const L = s.ledger;
  const n = (st: string) => L.filter((c) => c.state === st).length;
  return {
    id: s.id,
    created: s.created,
    status: s.status,
    subject: s.subject,
    claims: L.length,
    ledger_items: L.length,
    questions: s.questions.length,
    answers: s.questions.filter((q) => q.answer != null).length,
    founder_reported: n("FOUNDER-REPORTED"),
    deck_claims: n("DECK CLAIM"),
    unknowns: n("UNKNOWN"),
    contradictions: L.filter((c) => c.state === "CONTRADICTION" && !c.resolved).length,
  };
}

/** The old `workspace` body: rows newest first. */
export function workspace(ss: Session[]): EvaluationsWorkspace {
  return {
    sessions: [...ss].sort((a, b) => b.created.localeCompare(a.created)).map(sessionRow),
    states: STATES,
    families: FAMILIES,
    deck_label: DECK_LABEL,
    founder_label: FOUNDER_LABEL,
  };
}

/** A simplified old `panel`: groups by family, gaps, open contradictions, movement and the linked IMQ readiness. */
export function panel(s: Session, triggers: Set<string> = new Set()): Panel {
  const L = s.ledger;
  const groups = Object.fromEntries(
    Object.entries(GROUPS).map(([k, fids]) => {
      const rows = L.filter((c) => fids.includes(c.family));
      return [k, { claims: rows.length, states: Object.fromEntries(STATES.map((st) => [st, rows.filter((c) => c.state === st).length])), covered: false, latest: [] }];
    }),
  );
  const contras = L.filter((c) => c.state === "CONTRADICTION" && !c.resolved);
  const slug = s.context.slug;
  return {
    groups,
    evidence_gaps: FAMILIES.filter((f) => !L.some((c) => c.family === f.id && (c.state === "PUBLIC SOURCED FACT" || c.state === "OPERATOR VERIFIED"))).map((f) => f.label),
    contradictions: contras.map((c) => ({ id: c.id, text: c.text })),
    provisional_movement: [
      { dimension: "Founder", current: 15, verified_flag: true, provisional_direction: "→ founder-reported only (no score change)" },
      { dimension: "Why now", current: null, verified_flag: false, provisional_direction: "↑ evidence attached — re-score manually" },
      { dimension: "Taste", current: 10, verified_flag: null, provisional_direction: "→ no new input" },
    ],
    imq: slug
      ? { state: "NOT YET IMQ", blockers: [...(contras.length ? ["open contradictions"] : []), ...(triggers.has(slug) ? [] : [NO_TRIGGER]), "traction unverified"] }
      : { state: "not linked to a Conviction company", blockers: [] },
  };
}

const ok = (body: Body): Answer => ({ status: 200, body: { ok: true, ...body } });
const refuse = (error: string): Answer => ({ status: 200, body: { ok: false, error } });

export function fakeServer(routes: Routes = {}, initial: Session[] = sessions()) {
  const ss = structuredClone(initial);
  const triggers = new Set<string>();
  const calls: Req[] = [];
  let seq = 0;
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const nextOf = (s: Session) => (s.status === "ended" ? null : (s.questions.find((q) => q.answer == null && !(q as { skipped?: string }).skipped) ?? null));
  /** The old `next_question`: a queued question becomes the open one. */
  const advance = (s: Session) => {
    if (nextOf(s) || !s.queue.length) return;
    const f = s.queue.shift()!;
    s.questions.push(question(`q-new-${++seq}`, "why_now", f.text, f.kind));
  };
  const detail = (s: Session) => ({ session: s, panel: panel(s, triggers), next: nextOf(s) });
  const withRow = (s: Session, a: Answer): Answer => {
    const body = a.body as Body;
    return { status: a.status, body: { session: s, ...body, panel: panel(s, triggers), row: sessionRow(s) } };
  };

  function start(b: Body): Answer {
    const sub = (b.subject ?? {}) as { kind?: string; slug?: string; name?: string; founder?: string };
    const s: Session = {
      id: `ev-new-${++seq}`,
      created: `${TODAY} 09:00`,
      updated: `${TODAY} 09:00`,
      status: "live",
      subject: { kind: sub.kind ?? "external", name: sub.name ?? "", founder: sub.founder ?? "", ...(sub.slug ? { slug: sub.slug } : {}) },
      context: { kind: sub.kind, name: sub.name, founder: sub.founder, ...(sub.slug ? { slug: sub.slug } : {}) },
      ledger: [],
      questions: [question(`q-new-${++seq}`, "founder_team", "Why are you the one to build this?", "opening")],
      queue: [],
      tasks: [],
      memo_deltas: [],
      ended: null,
      plan: [],
    };
    ss.push(s);
    return { status: 200, body: { ok: true, id: s.id, ...detail(s) } };
  }

  function act(name: Action, s: Session, b: Body): Answer {
    if (name === "deck") {
      const lines = String(b.text ?? "")
        .split("\n")
        .map((x) => x.trim())
        .filter(Boolean);
      if (!lines.length) return refuse("paste the deck text first");
      const ids = lines.map((text) => {
        const c = claim(`c-new-${++seq}`, "traction", text, "DECK CLAIM", { label: DECK_LABEL, source: "pitch deck" });
        s.ledger.push(c);
        return c.id;
      });
      s.deck = { text: String(b.text), imported_at: `${TODAY} 09:00`, claims: [...(s.deck?.claims ?? []), ...ids] };
      return ok({ claims: ids.length, label: DECK_LABEL });
    }
    if (name === "next") {
      advance(s);
      return ok({ next: nextOf(s) });
    }
    const q = s.questions.find((x) => x.id === b.qid);
    if (name === "skip") {
      if (!q) return refuse("unknown question");
      if (q.answer != null) return refuse("already answered");
      Object.assign(q, { skipped: `${TODAY} 09:00` });
      advance(s);
      return ok({ next: nextOf(s) });
    }
    if (name === "answer") {
      if (!q) return refuse("unknown question");
      const text = String(b.text ?? "").trim();
      if (!text) return refuse("empty answer");
      const unknown = /^\s*(unknown|don'?t know)/i.test(text);
      Object.assign(q, { answer: text, answered_at: `${TODAY} 09:00` });
      s.ledger.push(claim(`c-new-${++seq}`, q.family, text, unknown ? "UNKNOWN" : "FOUNDER-REPORTED", { label: unknown ? "UNKNOWN" : FOUNDER_LABEL }));
      advance(s);
      return ok({ next: nextOf(s) });
    }
    const c = s.ledger.find((x) => x.id === b.claim_id);
    if (name === "evidence") {
      if (!c) return refuse("unknown claim");
      if (b.kind === "operator") {
        if (!b.confirm) return refuse("explicit confirmation required");
        c.state = "OPERATOR VERIFIED";
        c.evidence.push({ kind: "operator", note: String(b.note ?? ""), on: TODAY });
        return ok({ claim: c });
      }
      const url = String(b.url ?? "");
      if (!/^https?:\/\//.test(url) || /linkedin\.com/.test(url)) return refuse("a public source URL is required (not LinkedIn, not a search result)");
      c.state = "PUBLIC SOURCED FACT";
      c.evidence.push({ kind: "public", url, label: String(b.label ?? ""), note: String(b.note ?? ""), on: TODAY });
      return ok({ claim: c });
    }
    if (name === "resolve") {
      if (!c || c.state !== "CONTRADICTION") return refuse("not a contradiction");
      Object.assign(c, { resolved: true, resolution: { note: String(b.note ?? ""), on: TODAY } });
      return ok({ claim: c });
    }
    // end
    const answered = s.questions.filter((x) => x.answer != null).length;
    const unverified = s.ledger.filter((x) => x.state === "DECK CLAIM" || x.state === "FOUNDER-REPORTED");
    s.tasks = unverified.map((x, i) => ({ id: `t-${i + 1}`, text: `Verify: ${x.text}`, how: "public source or operator check", state: "open" }));
    s.memo_deltas = unverified.map((x) => `${x.family}: ${x.text} (unverified)`);
    const row = sessionRow(s);
    s.status = "ended";
    s.ended = {
      on: `${TODAY} 09:30`,
      ...(answered ? { call_id: `call-${s.id}` } : {}),
      founder_reported: row.founder_reported ?? 0,
      deck_claims: row.deck_claims ?? 0,
      unknowns: row.unknowns ?? 0,
      answers: answered,
      ledger_items: s.ledger.length,
      contradictions: row.contradictions ?? 0,
      tasks: s.tasks.length,
      followups: s.queue.map((f) => f.text),
      imq: panel(s, triggers).imq,
    };
    return ok({ ended: s.ended });
  }

  function trigger(b: Body): Answer {
    if (!b.confirm) return refuse("explicit confirmation required");
    if (!ss.some((s) => s.context.slug === b.slug)) return refuse("unknown company");
    if (String(b.date ?? "") > TODAY) return refuse("trigger date must be YYYY-MM-DD and not in the future");
    triggers.add(String(b.slug));
    return ok({ trigger: { kind: b.kind, date: b.date, url: b.url, fact: b.fact, by: "operator", recorded: `${TODAY} 09:00` } });
  }

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? (JSON.parse(String(init.body)) as Body) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    const answer = (a: Answer) => json(a.status, a.body);
    if (method === "GET" && url.pathname === "/api/evaluator/sessions") return answer(routes.sessions?.() ?? { status: 200, body: workspace(structuredClone(ss)) });
    if (method === "GET" && url.pathname === "/api/evaluator/session") {
      const s = ss.find((x) => x.id === url.searchParams.get("id"));
      return s ? json(200, structuredClone(detail(s))) : json(404, { error: "unknown session" });
    }
    const b = body ?? {};
    if (method === "POST" && url.pathname === "/api/conviction/imq_trigger") return answer(routes.trigger?.(b) ?? trigger(b));
    const m = url.pathname.match(/^\/api\/evaluator\/(start|deck|next|skip|answer|evidence|resolve|end)$/);
    if (method === "POST" && m) {
      const name = m[1] as Action;
      const own = routes[name]?.(b);
      if (own) return answer(own);
      if (name === "start") return answer(start(b));
      const s = ss.find((x) => x.id === b.id);
      if (!s) return answer(refuse("unknown session"));
      const a = act(name, s, b);
      if ((a.body as Body).ok) s.updated = `${TODAY} 09:00`;
      return answer(withRow(structuredClone(s), a));
    }
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    sessions: ss,
    calls,
    posts: () => calls.filter((c) => c.method === "POST"),
    reads: (path: string) => calls.filter((c) => c.method === "GET" && c.path.split("?")[0] === `/api/${path}`).length,
  };
}

export function renderPage(path = "/evaluator") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/evaluator", element: <EvaluatorPage /> },
      { path: "*", element: <p data-testid="elsewhere">elsewhere</p> },
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
