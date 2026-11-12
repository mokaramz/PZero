/**
 * The questions each Founder Radar write asks, and the exact POST bodies it sends — the old `useFrActions` wording and
 * bodies, line for line, as pure data so the bodies can be tested without a page.
 */
import { sv, type AskSpec, type Values } from "./ask";
import type { Person } from "./types";

/* ------------------------------------------------------------------ one-line notes (dismiss, links, opportunity, intro path) */

/** The single-field questions: the action, the dialog and the body key the answer goes to. */
export const NOTE_ASKS = {
  dismiss: { action: "dismiss", title: "Dismiss", label: "Why dismiss? (kept on record)", key: "note" },
  linkCompany: { action: "link_company", title: "Link to company", label: "Company / project name", key: "company" },
  linkEvent: { action: "link_event", title: "Link to event", label: "Event name", key: "event" },
  opportunity: { action: "opportunity", title: "Create pre-company opportunity", label: "Pre-company opportunity name", key: "name" },
  introPath: { action: "intro_path", title: "Record introduction path", label: "Introduction path (who → whom)", key: "route" },
} as const;

export type NoteAsk = (typeof NOTE_ASKS)[keyof typeof NOTE_ASKS];

export const noteSpec = (n: NoteAsk): AskSpec => ({ title: n.title, fields: [{ name: "x", label: n.label, placeholder: "" }] });
export const noteExtra = (n: NoteAsk, v: Values): Record<string, unknown> => ({ [n.key]: sv(v, "x") });

/* ------------------------------------------------------------------ LinkedIn, manual verification */

export const LINKEDIN_VERIFIED: AskSpec = {
  title: "Mark verified manually",
  intro: "Provenance is recorded as operator action; nothing automated.",
  fields: [
    { name: "fact", label: "Verified fact from the profile", required: true },
    { name: "founder", label: "The profile confirmed founder / co-founder status", type: "checkbox" },
  ],
  confirm: (x) => "Confirm manual verification: " + sv(x, "fact"),
};

export function linkedinVerifiedExtra(url: string, v: Values): Record<string, unknown> {
  const fact = sv(v, "fact");
  return { url, verified: true, founder: !!v.founder, fact, note: fact, confirm: true };
}

/* ------------------------------------------------------------------ public evidence on a person */

export const PERSON_EVIDENCE: AskSpec = {
  title: "Add public evidence (URL + claim)",
  fields: [
    { name: "url", label: "Public source URL", required: true, hint: "GitHub profile, official company/team/accelerator/university/grant page — not LinkedIn, not a search result" },
    { name: "label", label: "Source label" },
    { name: "claim", label: "Supported claim", type: "textarea" },
    { name: "kind", label: "Evidence category", type: "select", initial: "entrepreneurial", options: ["entrepreneurial", "builder", "technical", "trajectory", "project_a", "identity"] },
    {
      name: "activity_date",
      label: "Activity date of this evidence (YYYY-MM-DD) — the date the activity happened, not today",
      type: "date",
      when: { field: "kind", equals: "trajectory" },
    },
  ],
};

export function personEvidenceExtra(v: Values): Record<string, unknown> {
  const kind = sv(v, "kind") || "operator";
  return { url: sv(v, "url"), label: sv(v, "label"), claim: sv(v, "claim"), kind, activity_date: kind === "trajectory" ? sv(v, "activity_date") : undefined };
}

/* ------------------------------------------------------------------ identity */

const identityFact = (x: Values) => sv(x, "fact") || `${sv(x, "name")} (${sv(x, "handle")}) is co-founder of ${sv(x, "company")}`;

export function confirmIdentitySpec(p: Person): AskSpec {
  const pi = p.proposed_identity ?? { name: "" };
  return {
    title: "Confirm identity with evidence",
    fields: [
      { name: "name", label: "Human name", initial: pi.name || "", required: true },
      { name: "handle", label: "Stable handle / id (e.g. GitHub login)", initial: (p.aliases ?? [])[0] || "" },
      { name: "company", label: "Relevant company", initial: p.company || "" },
      { name: "url", label: "Public evidence URL that connects name, handle and company", initial: pi.url || "" },
      { name: "label", label: "Source label", initial: pi.source || "" },
      { name: "fact", label: "Verified fact (must mention the name, the handle and the company)", type: "textarea" },
    ],
    confirm: (x) => `Confirm: ${identityFact(x)}\nSource: ${sv(x, "label")} ${sv(x, "url")}`,
  };
}

export const confirmIdentityExtra = (v: Values): Record<string, unknown> => ({
  name: sv(v, "name"),
  handle: sv(v, "handle"),
  company: sv(v, "company"),
  url: sv(v, "url"),
  label: sv(v, "label"),
  fact: identityFact(v),
  confirm: true,
});

export const VERIFY_IDENTITY: AskSpec = {
  title: "Mark identity verified (evidence required)",
  fields: [
    { name: "url", label: "Public source URL that verifies this identity", required: true },
    { name: "label", label: "Source label" },
    { name: "fact", label: "Verified fact", type: "textarea" },
  ],
  confirm: (x) => "Confirm verification: " + sv(x, "fact"),
};

export const verifyIdentityExtra = (v: Values): Record<string, unknown> => ({ url: sv(v, "url"), label: sv(v, "label"), fact: sv(v, "fact"), confirm: true });

/* ------------------------------------------------------------------ merge */

export const MERGE: AskSpec = {
  title: "Merge duplicate…",
  fields: [{ name: "other", label: "ID of the duplicate person record to merge into this one (from its card)", required: true }],
};

export const MERGE_CONFIRM: AskSpec = { title: "Merge duplicate…", fields: [], submitLabel: "Merge", confirm: () => "Identity evidence supports a merge. Confirm?" };

/* ------------------------------------------------------------------ company evidence and sourced facts */

export const COMPANY_EVIDENCE: AskSpec = {
  title: "Add public evidence",
  fields: [
    { name: "url", label: "Public source URL", required: true, hint: "official company/team/accelerator/university page or GitHub — not LinkedIn, not a search result" },
    { name: "label", label: 'Source label (e.g. "company About page")' },
    { name: "claim", label: "Supported claim (what the page says)", type: "textarea" },
  ],
};

export const companyEvidenceBody = (key: string, v: Values) => ({ key, evidence: { url: sv(v, "url"), label: sv(v, "label"), claim: sv(v, "claim") } });

export const COMPANY_FACT: AskSpec = {
  title: "Add sourced company fact",
  fields: [
    { name: "field", label: "Which fact?", type: "select", required: true, options: ["founded", "status", "stage", "funding", "project_a_fit", "recent_activity", "early_stage_signal"] },
    { name: "value", label: "Value (for early_stage_signal: yes or no)", required: true },
    {
      name: "url",
      label: "Public source URL that states this fact",
      required: true,
      hint: "official company/team/accelerator/university/grant/portfolio page or GitHub — not LinkedIn, not a search result",
    },
    { name: "label", label: "Source label" },
    { name: "claim", label: "Exact supported claim as the page states it", type: "textarea" },
    { name: "activity_date", label: "Activity date (YYYY-MM-DD) — when the activity happened, not today", type: "date", when: { field: "field", equals: "recent_activity" } },
  ],
  confirm: (x) =>
    `Confirm sourced fact:\n${sv(x, "field")} = ${sv(x, "value")}${sv(x, "field") === "recent_activity" && sv(x, "activity_date") ? " · activity date " + sv(x, "activity_date") : ""}\n"${sv(x, "claim")}"\n${sv(x, "label")} · ${sv(x, "url")}`,
};

export function companyFactBody(key: string, v: Values) {
  const field = sv(v, "field");
  return {
    key,
    fact: {
      field,
      value: sv(v, "value"),
      url: sv(v, "url"),
      label: sv(v, "label"),
      claim: sv(v, "claim"),
      confirm: true,
      activity_date: field === "recent_activity" ? sv(v, "activity_date") : undefined,
    },
  };
}

/* ------------------------------------------------------------------ pairing */

/** The explicit pairing confirmation (review drawer): the proposed name and the chosen record with its aliases. */
export function pairSpec(name: string, personId: string, rec: Pick<Person, "name" | "aliases"> | undefined): AskSpec {
  const aliases = rec?.aliases ?? [];
  return {
    title: "Confirm pairing",
    fields: [],
    submitLabel: "Pair",
    confirm: () =>
      `Pair proposed human name\n  ${name}\nwith record\n  ${rec?.name || personId} (${personId}${aliases.length ? " · aliases: " + aliases.join(", ") : ""})\n\nThis records the pairing with your provenance; identity is confirmed only when you then press Confirm selected.`,
  };
}
