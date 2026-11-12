/** The Active Evaluator's pure view rules (review 024), ported from the old page: badge tones, the counts line, the
 *  `?start=1` entry, the start subject, the existing-evidence line and the derived lists. */
import type { Tone } from "@/components/ui";
import type { Claim, Context, EvaluationsWorkspace, Panel, Question, Session, SessionRow, StagedEvidence, StartSubject } from "./types";

/** The judgment-input groups of the right column, in the old order. */
export const GROUPS: Array<[string, string]> = [
  ["founder", "Founder"],
  ["market", "Market"],
  ["why_now", "Why now"],
  ["product", "Product"],
  ["traction", "Traction"],
  ["timing", "Timing"],
  ["conflict", "Conflict"],
];

/** The trigger kinds of the evaluator's why-now form, in the old order. */
export const IMQ_KINDS = ["trigger", "founder_formation", "fundraising", "incorporation", "window"];

/** The URL keys of the entry from Conviction: `/evaluator?start=1&slug=…&name=…&founder=…`. */
const START_KEYS = ["start", "slug", "name", "founder"];

export function stateTone(st: string): Tone {
  if (st === "PUBLIC SOURCED FACT" || st === "OPERATOR VERIFIED") return "green";
  if (st === "CONTRADICTION") return "red";
  if (st === "UNKNOWN") return "neutral";
  return "amber";
}

export function questionTone(kind: string): Tone {
  return kind === "challenge" ? "amber" : kind === "unknown" ? "neutral" : "blue";
}

export function supportsTone(supports: string): Tone {
  return supports === "yes" ? "green" : supports === "no" ? "red" : "neutral";
}

/** "3 evaluations · 2 live · 1 ended". */
export function countsLine(ss: SessionRow[]): string {
  const ended = ss.filter((x) => x.status === "ended").length;
  return `${ss.length} evaluation${ss.length === 1 ? "" : "s"} · ${ss.length - ended} live · ${ended} ended`;
}

/** The strip row's second line (the ledger-item breakdown); contradictions are added in red by the strip. */
export function rowLine(s: SessionRow): string {
  return `${s.subject.founder || ""} · ${s.answers ?? 0} answers · ${s.ledger_items ?? s.claims} ledger items (${s.founder_reported ?? 0} founder-reported · ${s.deck_claims ?? 0} deck${s.unknowns ? ` · ${s.unknowns} UNKNOWN` : ""})`;
}

export type StartPre = { slug?: string; name?: string; founder?: string };

/** The prefill of the start dialog from `?start=1` (null without it). A slug links the session to Conviction. */
export function startFromParams(p: URLSearchParams): StartPre | null {
  if (p.get("start") !== "1") return null;
  const pre = { slug: p.get("slug") ?? "", name: p.get("name") ?? "", founder: p.get("founder") ?? "" };
  return pre.slug ? pre : { name: pre.name, founder: pre.founder };
}

export function withoutStart(p: URLSearchParams): URLSearchParams {
  const q = new URLSearchParams(p);
  for (const k of START_KEYS) q.delete(k);
  return q;
}

/** The `POST evaluator/start` subject: a Conviction company when the entry carried a slug, an external meeting otherwise. */
export function startSubject(pre: StartPre, v: { name: string; founder: string }): StartSubject {
  return pre.slug ? { kind: "company", slug: pre.slug, name: v.name, founder: v.founder } : { kind: "external", name: v.name, founder: v.founder };
}

export const familyLabel = (w: EvaluationsWorkspace, f: string) => w.families.find((x) => x.id === f)?.label || f;

/** An answer that records an UNKNOWN (the old regex). */
export const isUnknownAnswer = (text: string | null | undefined) => /^\s*(unknown|don'?t know)/i.test(text || "");

/** "Existing Project Zero evidence": the linked Conviction record's scores, flags and conflict. */
export function existingEvidence(ctx: Context): string {
  if (!ctx.slug) return "not linked to a Conviction company";
  const v = ctx.verified;
  return `Provisional ${ctx.provisional ?? "—"} · Verified ${ctx.verified_score ?? "—"} · verified flags: founders ${!!v?.founders}, traction ${!!v?.traction}, funding ${!!v?.funding} · conflict: ${ctx.conflict || "none"}`;
}

export function researchFacts(ctx: Context): string {
  return Object.entries(ctx.research_facts ?? {})
    .map(([k, v]) => `${k} — ${(v.claim || "").slice(0, 60)}`)
    .join("; ");
}

export const newestFirst = <T>(xs: T[] | undefined): T[] => (xs ?? []).slice().reverse();

/** The answered questions (UNKNOWN answers included). */
export const askedQuestions = (s: Session): Question[] => (s.questions || []).filter((x) => x.answer != null);

export const openContradictions = (ledger: Claim[]): Claim[] => ledger.filter((x) => x.state === "CONTRADICTION" && !x.resolved);

/** Scout 00 evidence still awaiting the operator. */
export const awaitingStaged = (s: Session): StagedEvidence[] => (s.staged_evidence || []).filter((x) => x.state === "awaiting operator");

/** A ledger claim's own actions: attach a source / verify (deck and founder claims), resolve (an open contradiction). */
export function claimActions(cl: Claim, ended: boolean): "verify" | "resolve" | "resolved" | null {
  if (cl.state === "DECK CLAIM" || cl.state === "FOUNDER-REPORTED") return "verify";
  if (cl.state === "CONTRADICTION" && !cl.resolved && !ended) return "resolve";
  if (cl.resolved && cl.resolution) return "resolved";
  return null;
}

/** One provisional-movement line: "founder (15 ✓): up". */
export function movementLine(m: Panel["provisional_movement"][number]): string {
  const flag = m.verified_flag === true ? " ✓" : m.verified_flag === false ? " unverified" : "";
  return `${m.dimension} (${m.current ?? "—"}${flag}): ${m.provisional_direction}`;
}

/** The judgment-input group of a dimension (an empty one when the panel has none). */
export function groupOf(p: Panel, k: string) {
  const x = p.groups?.[k] || { claims: 0, states: {}, covered: false };
  return { ...x, states: Object.entries(x.states || {}).filter(([, n]) => n) };
}

export const callLink = (id: string) => `/founder-calls?call=${encodeURIComponent(id)}`;
