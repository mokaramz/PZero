/** A fake backend for the Founder Calls page tests: answers `GET founder-calls/calls` and `GET founder-calls/memo` from a
 *  workspace it keeps, applies the saves, follow-ups and links it accepts (the old bodies), answers the briefing, and
 *  records every call. A test can give its own answer for any write (a refusal). Every company, founder and person is
 *  invented. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import FounderCallsPage from "../FounderCallsPage";
import { initialFields } from "../model/calls";
import type { Call, CallsWorkspace, Company, Founder, NextAction, SaveBody } from "../model/types";

export type Req = { method: string; path: string; body?: Record<string, unknown> };
export type Answer = { status: number; body: unknown };
type Body = Record<string, unknown>;

export type Routes = {
  /** an answer replaces the default handling of that endpoint */
  save?: (body: Body) => Answer | undefined;
  followup?: (body: Body) => Answer | undefined;
  link?: (body: Body) => Answer | undefined;
  briefing?: (body: Body) => Answer | undefined;
  memo?: (id: string) => Answer | undefined;
  calls?: () => Answer | undefined;
};

export const TODAY = "2026-11-12";
const LABEL = "Founder-reported — unverified";
const SUMMARY_LABEL = `Machine-generated from your private notes — ${LABEL}`;
/** The operator: the form's default owner and first participant (factual call data — read from the form, so the name
 *  is written in one place). */
const OPERATOR = initialFields({ today: TODAY } as CallsWorkspace, {}).na_owner;
const CALL_TYPES: Record<string, string> = { first: "First scout call", followup: "Follow-up / diligence call" };

/** The old `due_state` (seven days count as "upcoming"). */
export function dueState(na: NextAction | undefined, today = TODAY): string {
  if (!na || (!na.text && !na.due)) return "";
  if (na.done) return "done";
  if (!na.due) return "open";
  if (na.due < today) return "overdue";
  if (na.due === today) return "due";
  const days = (Date.parse(na.due) - Date.parse(today)) / 86_400_000;
  return days <= 7 ? "upcoming" : "scheduled";
}

function call(id: string, founder: Founder, company: Company, extra: Partial<Call>): Call {
  const c: Call = {
    id,
    created: "2026-11-01 09:00",
    updated: "2026-11-01 09:00",
    founder_id: founder.id,
    company_id: company.id,
    call_type: "first",
    call_type_label: "",
    date: "2026-11-01",
    time: "",
    channel: "video",
    objective: "",
    observations: "",
    discovery_origin: "",
    intro_path: "",
    participants: [OPERATOR, founder.name],
    answers: {},
    claims: [],
    risks: [],
    open_questions: [],
    next_action: { text: "", owner: "", due: "" },
    assessment: {},
    label: LABEL,
    founder_name: founder.name,
    company_name: company.name,
    linked_person_id: founder.linked_person_id,
    due_state: "",
    summary: "",
    summary_label: SUMMARY_LABEL,
    ...extra,
  };
  return refresh(c);
}

function refresh(c: Call): Call {
  c.call_type_label = CALL_TYPES[c.call_type] ?? "";
  c.due_state = dueState(c.next_action);
  c.summary = `${c.founder_name} (${c.company_name}) — ${c.call_type_label} on ${c.date} via ${c.channel}.`;
  return c;
}

const founder = (id: string, name: string, company_id: string, linked_person_id = ""): Founder => ({
  id,
  name,
  company_id,
  linked_person_id,
  external: !linked_person_id,
  calls: [],
});

const company = (id: string, name: string, links: { pipeline?: string; radar?: string } = {}): Company => ({
  id,
  name,
  linked_pipeline_slug: links.pipeline ?? "",
  linked_radar_key: links.radar ?? "",
  external: !links.pipeline && !links.radar,
  founders: [],
  call_count: 0,
});

/** Three companies, four founders, five calls:
 *  - Kestrel Labs (linked to Conviction, `kestrel-labs`) → Ada Quill (linked person) → call-1 (OVERDUE, with answers,
 *    claims, risks and a judgment) and call-2 (follow-up call, DONE)
 *  - Otter Mill (external) → Ben Rook (external) → call-3 (DUE SOON); Cleo Marsh (external) → no calls
 *  - Pine Robotics (linked to the radar) → Dana Vale (linked) → call-4 (DUE TODAY) and call-5 (OPEN — no date) */
export function companies(): Company[] {
  const kestrel = company("co-kestrel", "Kestrel Labs", { pipeline: "kestrel-labs" });
  const otter = company("co-otter", "Otter Mill");
  const pine = company("co-pine", "Pine Robotics", { radar: "pine-robotics" });
  const ada = founder("f-ada", "Ada Quill", kestrel.id, "p-ada");
  const ben = founder("f-ben", "Ben Rook", otter.id);
  const cleo = founder("f-cleo", "Cleo Marsh", otter.id);
  const dana = founder("f-dana", "Dana Vale", pine.id, "p-dana");
  ada.calls = [
    call("call-1", ada, kestrel, {
      date: "2026-11-02",
      time: "10:30",
      objective: "Understand the robot arm pilot",
      discovery_origin: "scan",
      intro_path: "Robin → Ada",
      answers: {
        why: { a: "Small workshops cannot afford integrators.", unknown: false, followups: { "1": "Saw it at her father's shop." } },
        pull: { a: "", unknown: true, followups: {} },
      },
      claims: [{ text: "Three paid pilots", label: LABEL }],
      risks: ["Hardware margins"],
      open_questions: ["Who is the buyer?"],
      next_action: { text: "Send the deck to Robin", owner: OPERATOR, due: "2026-11-10" },
      assessment: { why_exceptional: "Builder from the shop floor", concerns: "", recommendation: "Follow up", confidence: "Medium", next_action: "" },
    }),
    call("call-2", ada, kestrel, {
      call_type: "followup",
      date: "2026-11-09",
      next_action: { text: "Ask for references", owner: "Founder", due: "2026-11-11", done: true, done_on: "2026-11-11" },
    }),
  ];
  ben.calls = [call("call-3", ben, otter, { date: "2026-11-11", next_action: { text: "Book a site visit", owner: OPERATOR, due: "2026-11-15" } })];
  dana.calls = [
    call("call-4", dana, pine, { date: "2026-11-05", next_action: { text: "Check the patent", owner: OPERATOR, due: TODAY } }),
    call("call-5", dana, pine, { date: "2026-11-08", next_action: { text: "Meet the CTO", owner: OPERATOR, due: "" } }),
  ];
  kestrel.founders = [ada];
  otter.founders = [ben, cleo];
  pine.founders = [dana];
  return [kestrel, otter, pine];
}

const ORDER: Record<string, number> = { overdue: 0, due: 1, upcoming: 2, open: 3 };

/** The old workspace body built from the companies: the flat calls, the due list (open included, as the server sends
 *  it), the counts (due = overdue + due today) and the static tables. */
export function workspace(cos: Company[]): CallsWorkspace {
  for (const co of cos) co.call_count = co.founders.reduce((n, f) => n + f.calls.length, 0);
  const calls = cos.flatMap((co) => co.founders.flatMap((f) => f.calls));
  const due = calls.filter((c) => c.due_state in ORDER).sort((a, b) => ORDER[a.due_state] - ORDER[b.due_state]);
  return {
    label: LABEL,
    summary_label: SUMMARY_LABEL,
    companies: cos,
    orphan_founders: [],
    calls,
    due,
    templates: {
      first: {
        label: CALL_TYPES.first,
        sections: [
          { id: "why", q: "Why this company, problem and timing?", followups: ["What changed recently?", "Why did you personally start this?"] },
          { id: "pull", q: "What customer pull, usage, pilots or revenue exists?", followups: [] },
        ],
      },
      followup: { label: CALL_TYPES.followup, sections: [{ id: "metrics", q: "Metrics", followups: ["Revenue / ARR, growth, burn, runway"] }] },
    },
    call_types: CALL_TYPES,
    channels: ["video", "phone", "in-person"],
    recommendations: ["Pass", "Monitor", "Follow up"],
    confidence: ["Low", "Medium", "High"],
    owners: [OPERATOR, "Founder", "Other"],
    assessment_fields: [
      ["why_exceptional", "Why exceptional"],
      ["concerns", "Main concerns"],
    ],
    people: [
      { id: "p-ben", name: "Benjamin Rook", company: "Otter Mill", role: "CEO" },
      { id: "p-gus", name: "Gus Fernley", company: "Fernley Tools", role: "" },
    ],
    pipeline: [
      { slug: "otter-mill", company: "Otter Mill GmbH", founders: ["Benjamin Rook", "Cleo Marsh"] },
      { slug: "kestrel-labs", company: "Kestrel Labs", founders: ["Ada Quill"] },
    ],
    today: TODAY,
    counts: {
      companies: cos.length,
      founders: cos.reduce((n, co) => n + co.founders.length, 0),
      calls: calls.length,
      due: calls.filter((c) => c.due_state === "overdue" || c.due_state === "due").length,
    },
  };
}

const lines = (s: unknown) =>
  String(s ?? "")
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

export function fakeServer(routes: Routes = {}, initial: Company[] = companies()) {
  const cos = structuredClone(initial);
  const calls: Req[] = [];
  let seq = 0;
  const founders = () => cos.flatMap((co) => co.founders);
  const allCalls = () => founders().flatMap((f) => f.calls);
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  function save(b: SaveBody): Answer {
    if (!b.founder || !b.company) return { status: 400, body: { error: "founder name and company are required" } };
    const fields = {
      call_type: b.call_type,
      date: b.date,
      time: b.time,
      channel: b.channel,
      objective: b.objective,
      observations: b.observations,
      discovery_origin: b.discovery_origin,
      intro_path: b.intro_path,
      participants: b.participants.split(",").map((x) => x.trim()).filter(Boolean),
      answers: b.answers,
      claims: lines(b.claims).map((text) => ({ text, label: LABEL })),
      risks: lines(b.risks),
      open_questions: lines(b.open_questions),
      next_action: { ...b.next_action },
      assessment: b.assessment,
    };
    const existing = b.id ? allCalls().find((c) => c.id === b.id) : undefined;
    if (b.id && !existing) return { status: 404, body: { error: "unknown call" } };
    let co: Company | undefined;
    let c: Call;
    let changed = true;
    if (existing) {
      co = cos.find((x) => x.id === existing.company_id);
      const was = { ...existing, next_action: { text: existing.next_action.text, owner: existing.next_action.owner, due: existing.next_action.due } };
      changed = (Object.keys(fields) as Array<keyof typeof fields>).some((k) => JSON.stringify(fields[k]) !== JSON.stringify(was[k]));
      if (changed) Object.assign(existing, fields, { updated: `${TODAY} 09:00`, next_action: { ...existing.next_action, ...fields.next_action } });
      c = refresh(existing);
    } else {
      co = cos.find((x) => x.id === b.company_id) ?? cos.find((x) => x.name === b.company);
      if (!co) {
        co = company(`co-${++seq}`, b.company, { pipeline: b.pipeline_slug || undefined, radar: b.radar_key || undefined });
        cos.push(co);
      }
      let f = co.founders.find((x) => x.id === b.founder_id) ?? co.founders.find((x) => x.name === b.founder);
      if (!f) {
        f = founder(`f-${++seq}`, b.founder, co.id, b.person_id);
        co.founders.push(f);
      }
      c = call(`call-new-${++seq}`, f, co, { ...fields, created: `${TODAY} 09:00`, updated: `${TODAY} 09:00` });
      f.calls.push(c);
    }
    const body: Record<string, unknown> = { ok: true, call: c, changed, founder_id: c.founder_id, company_id: c.company_id };
    if (co?.linked_pipeline_slug) body.pipeline_slug = co.linked_pipeline_slug;
    return { status: 200, body };
  }

  function followup(b: Body): Answer {
    const c = allCalls().find((x) => x.id === b.id);
    if (!c) return { status: 404, body: { error: "unknown call" } };
    c.next_action = b.done ? { ...c.next_action, done: true, done_on: TODAY } : { text: c.next_action.text, owner: c.next_action.owner, due: c.next_action.due };
    return { status: 200, body: { ok: true, call: refresh(c) } };
  }

  function link(b: Body): Answer {
    if (b.founder_id) {
      const p = workspace(cos).people.find((x) => x.id === b.person_id);
      if (!p) return { status: 404, body: { error: "unknown person" } };
      const f = founders().find((x) => x.id === b.founder_id);
      if (!f) return { status: 200, body: { ok: false, founder_id: null } };
      Object.assign(f, { linked_person_id: p.id, external: false });
      for (const c of f.calls) c.linked_person_id = p.id;
      return { status: 200, body: { ok: true, founder_id: f.id } };
    }
    if (b.company_id) {
      const e = workspace(cos).pipeline.find((x) => x.slug === b.pipeline_slug);
      if (!e) return { status: 404, body: { error: "unknown pipeline company" } };
      const co = cos.find((x) => x.id === b.company_id);
      if (!co) return { status: 200, body: { ok: false, company_id: null } };
      Object.assign(co, { linked_pipeline_slug: e.slug, external: false });
      return { status: 200, body: { ok: true, company_id: co.id } };
    }
    return { status: 400, body: { error: "founder_id or company_id required" } };
  }

  function briefing(b: Body): Answer {
    if (!b.confirm) return { status: 400, body: { error: "explicit confirmation required" } };
    const f = founders().find((x) => x.id === b.founder_id);
    if (!f?.calls.length) return { status: 404, body: { error: "no calls for this founder" } };
    return { status: 200, body: { markdown: `# Project A briefing — ${f.name}\n\n${f.calls.length} call(s). ${LABEL}`, label: LABEL } };
  }

  function memo(id: string): Answer {
    const c = allCalls().find((x) => x.id === id);
    if (!c) return { status: 404, body: { error: "unknown call" } };
    return { status: 200, body: { markdown: `# Call memo — ${c.founder_name}\n\n${c.summary}`, label: LABEL } };
  }

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const url = new URL(String(input), "http://x");
    const body = init?.body ? (JSON.parse(String(init.body)) as Body) : undefined;
    calls.push({ method, path: url.pathname + url.search, body });
    const answer = (a: Answer) => json(a.status, a.body);
    if (method === "GET" && url.pathname === "/api/founder-calls/calls") return answer(routes.calls?.() ?? { status: 200, body: workspace(structuredClone(cos)) });
    if (method === "GET" && url.pathname === "/api/founder-calls/memo") {
      const id = url.searchParams.get("id") ?? "";
      return answer(routes.memo?.(id) ?? memo(id));
    }
    const b = body ?? {};
    if (method === "POST" && url.pathname === "/api/founder-calls/save") return answer(routes.save?.(b) ?? save(b as SaveBody));
    if (method === "POST" && url.pathname === "/api/founder-calls/followup") return answer(routes.followup?.(b) ?? followup(b));
    if (method === "POST" && url.pathname === "/api/founder-calls/link") return answer(routes.link?.(b) ?? link(b));
    if (method === "POST" && url.pathname === "/api/founder-calls/briefing") return answer(routes.briefing?.(b) ?? briefing(b));
    return json(404, { ok: false, error: "not found" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    posts: () => calls.filter((c) => c.method === "POST"),
    reads: (path: string) => calls.filter((c) => c.method === "GET" && c.path.split("?")[0] === `/api/${path}`).length,
  };
}

export function renderPage(path = "/founder-calls") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  const router = createMemoryRouter(
    [
      { path: "/founder-calls", element: <FounderCallsPage /> },
      { path: "*", element: <p>elsewhere</p> },
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
