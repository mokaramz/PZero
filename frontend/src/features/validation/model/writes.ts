/**
 * The Validation writes' pure logic (review 027b), ported from the old `RecordForms.tsx`, `Benchmarks.tsx` and
 * `ValidationPage.tsx`: the form shapes and the rules that enable Save, the bodies posted, the benchmark preview line,
 * the retraction rule, and the packet mark (decision f). Rendering stays in ../components; the endpoints in ../api.
 */
import type { Packet } from "./types";

/* ------------------------------------------------------------------ the outcome */

/** Real-world outcomes need an evidence URL (the old `REAL_WORLD`). */
export const REAL_WORLD = ["institutional_round", "commercial_milestone", "acquisition", "project_a_invested"];
export const needsEvidence = (kind: string) => REAL_WORLD.includes(kind);
const HTTP = /^https?:\/\//;

/** The old outcome form and so the old `validation_outcome` body: no `candidate_id`, `supersedes` or `outcome_date`
 *  (the server derives them). */
export type OutcomeFields = { company: string; kind: string; event_date: string; evidence_url: string; benchmark_system: string; note: string };
export const OUTCOME_FORM: OutcomeFields = { company: "", kind: "institutional_round", event_date: "", evidence_url: "", benchmark_system: "", note: "" };

/** Save needs a company and a date, and an http(s) evidence URL for a real-world outcome. */
export const outcomeReady = (f: OutcomeFields) => !!f.company && !!f.event_date && (!needsEvidence(f.kind) || HTTP.test(f.evidence_url));
/** "Which database" is asked only for an external-database listing. */
export const asksDatabase = (kind: string) => kind === "external_db_listing";

/* ------------------------------------------------------------------ the audits */

export type AuditType = "miss" | "false_positive";

/** The old audit form: one shape for both types (the old body sends every field, whichever type). */
export type AuditFields = {
  company: string;
  earliest_signal: string;
  earliest_signal_date: string;
  signal_source: string;
  should_have_found: string;
  why_missed: string;
  preventable: string;
  improvement: string;
  causes: string[];
  lesson: string;
  note: string;
};
export const AUDIT_FORM: AuditFields = {
  company: "",
  earliest_signal: "",
  earliest_signal_date: "",
  signal_source: "",
  should_have_found: "",
  why_missed: "source_not_covered",
  preventable: "unclear",
  improvement: "",
  causes: [],
  lesson: "",
  note: "",
};
export const PREVENTABLE = ["yes", "no", "unclear"] as const;

export const auditTitle = (type: AuditType) =>
  type === "miss" ? "Miss audit — a strong company we did not catch early" : "False-positive audit — prioritised but proved weak";
/** Save needs a company; a false positive also needs at least one cause. */
export const auditReady = (type: AuditType, f: AuditFields) => !!f.company && (type === "miss" || f.causes.length > 0);
/** The old `validation_audit` body: the whole form plus its type. */
export const auditBody = (type: AuditType, f: AuditFields) => ({ ...f, type });
/** Tick or untick one false-positive cause (ticking order kept). */
export const toggleCause = (causes: string[], c: string, on: boolean) => (on ? [...causes, c] : causes.filter((x) => x !== c));

/* ------------------------------------------------------------------ the retraction */

export const RETRACT_QUESTION = "Why retract this outcome? (kept in history)";
export const RETRACT_MIN = 8;
/** The reason to post, or null when the answer is too short (or the prompt was cancelled): nothing is sent then. As
 *  before, the length is checked on the trimmed answer and the answer is sent as typed. */
export function retractReason(answer: string | null): string | null {
  const reason = answer || "";
  return reason.trim().length >= RETRACT_MIN ? reason : null;
}

/* ------------------------------------------------------------------ the benchmark import */

export type BenchmarkFields = { system: string; csv: string };
/** The old benchmark summary (no `ok`): the preview, and the import with `imported: true`. */
export type BenchmarkSummary = {
  system: string;
  rows: number;
  usable: number;
  skipped: number;
  matched_to_pz: number;
  name_column: string;
  date_column: string;
  imported: boolean;
  file_sha?: string;
};
/** Preview needs a system name and some CSV text (the server's own minimum). */
export const benchmarkReady = (f: BenchmarkFields) => !!f.system && f.csv.length >= 10;
export const previewLine = (p: BenchmarkSummary) =>
  `${p.rows} rows · ${p.usable} usable · ${p.skipped} skipped (no / future date) · ${p.matched_to_pz} known to Project Zero · columns “${p.name_column}” / “${p.date_column}”`;
export const importLabel = (p: BenchmarkSummary) => `Import ${p.usable} dates`;
export const importedMessage = (r: BenchmarkSummary) => `${r.usable} benchmark date(s) imported`;

/* ------------------------------------------------------------------ the packet mark (decision f) */

/** The packet's `Generated` time as its second line prints it (the server's own pattern, the old naive
 *  `%Y-%m-%dT%H:%M:%S`). The packet answer has no separate field for it. */
const GENERATED = /^Generated (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}) · /m;
export function packetGenerated(text: string): string | null {
  return GENERATED.exec(text)?.[1] ?? null;
}

export type MarkBody = { cycle: string; generated: string; sha: string };
/** The mark of the packet the page showed: its cycle ("" for every cycle, as before), its `Generated` time and its sha
 *  — the server renders the packet at that time and logs the sha only when it is the same text. Null when the text
 *  carries no `Generated` time (nothing can be verified, so nothing is posted). */
export function markBody(p: Packet): MarkBody | null {
  const generated = packetGenerated(p.text);
  return generated ? { cycle: p.cycle === "all" ? "" : p.cycle, generated, sha: p.sha } : null;
}
export const PACKET_COPIED = "Packet copied — paste it into Chief Scout 00";
export const CLIPBOARD_BLOCKED = "Clipboard blocked — select the text and copy manually";
export const NO_GENERATED = "the packet has no Generated time — prepare it again";
