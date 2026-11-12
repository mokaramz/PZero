/** Founder Calls — the pure parts of the old page: the context keys other views pass, the due box rows, the form's
 *  initial state and the `POST save` body (v1's `saveCall()`, field for field), the drawer file names and the picker
 *  rows. */
import type { Answer, Call, CallCtx, CallsWorkspace, SaveBody } from "./types";

/** The keys `/founder-calls?log=1` (or `new=1`) may carry — Conviction, Founder Radar and Network open the form with them. */
export const CTX_KEYS = ["name", "company", "person_id", "pipeline_slug", "radar_key", "discovery_origin", "call_type", "founder_id", "company_id"] as const;

/** The form context in the URL, or null when the URL does not open the form. */
export function ctxFromParams(params: URLSearchParams): CallCtx | null {
  if (params.get("log") !== "1" && params.get("new") !== "1") return null;
  const ctx: CallCtx = {};
  for (const k of CTX_KEYS) {
    const v = params.get(k);
    if (v) ctx[k] = v;
  }
  return ctx;
}

/** The URL once the form has taken its context: the entry keys are dropped (`?call=` and the rest stay). */
export function withoutCtx(params: URLSearchParams): URLSearchParams {
  const p = new URLSearchParams(params);
  for (const k of ["log", "new", ...CTX_KEYS]) p.delete(k);
  return p;
}

/** The due box: overdue, due today and due soon only (an open next action without a date is not shown), as before. */
export const DUE_SHOWN = ["overdue", "due", "upcoming"];
export const dueRows = (fc: CallsWorkspace): Call[] => fc.due.filter((r) => DUE_SHOWN.includes(r.due_state));

export function slugName(s: string | undefined, fallback: string): string {
  return (s || fallback).replace(/[^a-z0-9]+/gi, "-").toLowerCase();
}

export const memoFile = (c: Call | undefined) => `call-memo-${slugName(c?.founder_name, "founder")}-${c?.date ?? ""}.md`;
export const briefingFile = (name: string | undefined) => `omar-briefing-${slugName(name, "founder")}.md`;

export const findFounder = (fc: CallsWorkspace, id: string | undefined) => (id ? fc.companies.flatMap((x) => x.founders).find((f) => f.id === id) : undefined);

/* ------------------------------------------------------------------ the call form */

export type FormAnswers = Record<string, { a: string; unknown: boolean; followups: Record<number, string> }>;

export type FormFields = {
  founder: string;
  company: string;
  call_type: string;
  date: string;
  time: string;
  channel: string;
  participants: string;
  discovery_origin: string;
  intro_path: string;
  objective: string;
  claims: string;
  observations: string;
  risks: string;
  open_questions: string;
  na_text: string;
  na_owner: string;
  na_due: string;
};

/** What the form edits: the call being edited, or the founder / company the context names (read-only names). */
export function formTarget(fc: CallsWorkspace, ctx: CallCtx) {
  const call = ctx.call_id ? (fc.calls.find((x) => x.id === ctx.call_id) ?? null) : null;
  const founder = findFounder(fc, ctx.founder_id);
  const company = ctx.company_id ? fc.companies.find((x) => x.id === ctx.company_id) : undefined;
  return { call, founder, company };
}

export function initialFields(fc: CallsWorkspace, ctx: CallCtx, today = new Date().toISOString().slice(0, 10)): FormFields {
  const { call: c, founder: fdr, company: co } = formTarget(fc, ctx);
  const founderName = c ? c.founder_name : fdr ? fdr.name : ctx.name || "";
  const companyName = c ? c.company_name : co ? co.name : ctx.company || "";
  const na0 = c?.next_action;
  return {
    founder: founderName,
    company: companyName,
    call_type: c ? c.call_type : ctx.call_type || "first",
    date: c ? c.date : fc.today || today,
    time: c ? c.time : "",
    channel: c ? c.channel : "video",
    participants: (c ? c.participants : ["Mohamed", founderName]).filter(Boolean).join(", "),
    discovery_origin: c ? c.discovery_origin : ctx.discovery_origin || "",
    intro_path: c ? c.intro_path : "",
    objective: c ? c.objective : "",
    claims: (c ? c.claims : []).map((x) => x.text).join("\n"),
    observations: c ? c.observations : "",
    risks: (c ? c.risks : []).join("\n"),
    open_questions: (c ? c.open_questions : []).join("\n"),
    na_text: na0?.text || "",
    na_owner: na0?.owner || "Mohamed",
    na_due: na0?.due || "",
  };
}

export function initialAnswers(c: Call | null): FormAnswers {
  const out: FormAnswers = {};
  for (const [k, v] of Object.entries((c?.answers || {}) as Record<string, Answer>)) {
    const fu: Record<number, string> = {};
    for (const [j, t] of Object.entries(v.followups || {})) fu[Number(j)] = t;
    out[k] = { a: v.a || "", unknown: !!v.unknown && !v.a, followups: fu };
  }
  return out;
}

/** v1 `saveCall()`: the answers of the current template only, the assessment fields trimmed, the lists as typed. */
export function saveBody(
  fc: CallsWorkspace,
  ctx: CallCtx,
  f: FormFields,
  answers: FormAnswers,
  asm: Record<string, string>,
): SaveBody {
  const { call: c, founder: fdr, company: co } = formTarget(fc, ctx);
  const tmpl = fc.templates[f.call_type] ?? { sections: [] };
  const ans: Record<string, Answer> = {};
  for (const s of tmpl.sections) {
    const r = answers[s.id] || { a: "", unknown: false, followups: {} };
    const fu: Record<string, string> = {};
    s.followups.forEach((_, j) => {
      const x = (r.followups[j] || "").trim();
      if (x) fu[j] = x;
    });
    ans[s.id] = { a: r.a.trim(), unknown: !!r.unknown, followups: fu };
  }
  const assessment: Record<string, string> = {};
  for (const [k] of fc.assessment_fields) assessment[k] = (asm[k] || "").trim();
  assessment.recommendation = asm.recommendation || "";
  assessment.confidence = asm.confidence || "";
  assessment.next_action = (asm.next_action || "").trim();
  return {
    id: c ? c.id : "",
    founder: f.founder.trim(),
    company: f.company.trim(),
    founder_id: c ? c.founder_id : fdr ? fdr.id : "",
    company_id: c ? c.company_id : co ? co.id : "",
    person_id: ctx.person_id || "",
    pipeline_slug: ctx.pipeline_slug || "",
    radar_key: ctx.radar_key || "",
    call_type: f.call_type,
    date: f.date,
    time: f.time.trim(),
    channel: f.channel,
    participants: f.participants,
    discovery_origin: f.discovery_origin.trim(),
    intro_path: f.intro_path.trim(),
    objective: f.objective.trim(),
    answers: ans,
    claims: f.claims,
    observations: f.observations,
    risks: f.risks,
    open_questions: f.open_questions,
    next_action: { text: f.na_text.trim(), owner: f.na_owner, due: f.na_due },
    assessment,
  };
}

/* ------------------------------------------------------------------ the link pickers */

export type PickRow = { id: string; label: string; sub: string };

export const personRows = (fc: CallsWorkspace): PickRow[] =>
  fc.people.map((p) => ({ id: p.id, label: p.name, sub: [p.company, p.role].filter(Boolean).join(" · ") }));

export const pipelineRows = (fc: CallsWorkspace): PickRow[] => fc.pipeline.map((e) => ({ id: e.slug, label: e.company, sub: (e.founders || []).join(", ") }));

export const filterRows = (rows: PickRow[], q: string) => rows.filter((r) => `${r.label} ${r.sub}`.toLowerCase().includes(q.toLowerCase()));
