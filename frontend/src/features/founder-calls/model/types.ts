/** The Founder Calls payloads (review 023) — the old `/api/calls`, `/api/call_memo` and `call_*` POST bodies, unchanged,
 *  under new paths (see ../api). */

export type Answer = { a: string; unknown: boolean; followups: Record<string, string> };
export type NextAction = { text: string; owner: string; due: string; done?: boolean; done_on?: string };

export type Call = {
  id: string;
  created: string;
  updated: string;
  founder_id: string;
  company_id: string;
  call_type: string;
  call_type_label: string;
  date: string;
  time: string;
  channel: string;
  objective: string;
  observations: string;
  discovery_origin: string;
  intro_path: string;
  participants: string[];
  answers: Record<string, Answer>;
  claims: Array<{ text: string; label?: string }>;
  risks: string[];
  open_questions: string[];
  next_action: NextAction;
  assessment: Record<string, string>;
  label: string;
  founder_name: string;
  company_name: string;
  linked_person_id: string;
  /** "overdue" | "due" | "upcoming" | "open" | "done" | "scheduled" | "" */
  due_state: string;
  summary: string;
  summary_label: string;
};

export type Founder = {
  id: string;
  name: string;
  company_id: string;
  linked_person_id: string;
  external: boolean;
  calls: Call[];
  last_call?: string;
};

export type Company = {
  id: string;
  name: string;
  linked_pipeline_slug: string;
  linked_radar_key: string;
  external: boolean;
  founders: Founder[];
  call_count: number;
};

export type Section = { id: string; q: string; followups: string[] };
export type Template = { label: string; sections: Section[] };

export type CallsWorkspace = {
  label: string;
  summary_label: string;
  companies: Company[];
  orphan_founders?: unknown[];
  calls: Call[];
  due: Call[];
  templates: Record<string, Template>;
  call_types: Record<string, string>;
  channels: string[];
  recommendations: string[];
  confidence: string[];
  owners: string[];
  assessment_fields: Array<[string, string]>;
  people: Array<{ id: string; name: string; company: string; role: string }>;
  pipeline: Array<{ slug: string; company: string; founders: string[] }>;
  today: string;
  counts: { companies: number; founders: number; calls: number; due: number };
};

/** Context other views pass when they open the call form (v1 `openCallFor(ctx)`). */
export type CallCtx = {
  external?: boolean;
  call_id?: string;
  founder_id?: string;
  company_id?: string;
  name?: string;
  company?: string;
  person_id?: string;
  pipeline_slug?: string;
  radar_key?: string;
  discovery_origin?: string;
  call_type?: string;
};

/** `POST save` → the old `call_save` body; `pipeline_slug` when the call's company is linked to Conviction. */
export type SaveResult = { ok: boolean; changed: boolean; call: Call; founder_id?: string; company_id?: string; pipeline_slug?: string };
export type FollowupResult = { ok: boolean; call: Call };
/** `POST link` → `{ok, founder_id}` or `{ok, company_id}`; an unknown founder / company is `ok: false` with a null id. */
export type LinkResult = { ok: boolean; founder_id?: string | null; company_id?: string | null };
/** `GET memo?id=` and `POST briefing` → private Markdown, never stored, never sent. */
export type MarkdownDoc = { markdown: string; label: string };

/** The `POST save` body — v1's `saveCall()` body, field for field. */
export type SaveBody = {
  id: string;
  founder: string;
  company: string;
  founder_id: string;
  company_id: string;
  person_id: string;
  pipeline_slug: string;
  radar_key: string;
  call_type: string;
  date: string;
  time: string;
  channel: string;
  participants: string;
  discovery_origin: string;
  intro_path: string;
  objective: string;
  answers: Record<string, Answer>;
  claims: string;
  observations: string;
  risks: string;
  open_questions: string;
  next_action: { text: string; owner: string; due: string };
  assessment: Record<string, string>;
};
