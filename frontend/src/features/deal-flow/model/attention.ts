/**
 * The client attention score and its explanation (protected; old `logic.ts`, from v1 `dashboard.py`).
 * The wording is operator-facing and encodes product rules — keep it verbatim.
 *
 * Known quirk kept on purpose (review 009, deviation b): the default queue ORDERS by `att()` computed here, while the
 * row badge SHOWS the server's `attention_v2.score`.
 */
import type { Candidate } from "./types";

const DAY_MS = 864e5;

/** A real source date only: a published / award date, never the detection date. */
export function srcDate(c: Candidate): string | null {
  if (c.source_date) return c.source_date;
  if ((c.date_kind === "published" || c.date_kind === "award") && /^\d{4}-\d{2}-\d{2}/.test(c.date || "")) return (c.date || "").slice(0, 10);
  return null;
}

export function recScore(c: Candidate, now = Date.now()): number {
  const d = srcDate(c);
  if (!d) return 0;
  const age = (now - new Date(d).getTime()) / DAY_MS;
  return age <= 7 ? 3 : age <= 30 ? 2 : age <= 90 ? 1 : 0;
}

export const fbAdj = (c: Candidate) => c.feedback?.adjustment || 0;

export function fbTxt(c: Candidate): string {
  const a = fbAdj(c);
  return `${c.feedback?.label || "Feedback-adjusted sourcing priority"} ${a > 0 ? "+" : ""}${a}`;
}

export const earliness = (c: Candidate) => (c.discovery_tier === "pre_company" ? 3 : c.discovery_tier === "grant" ? 2 : 1);
export const fitScore = (c: Candidate) => Math.min((c.archetype_hits || []).length, 2) * 2 + ((c.twins || []).length ? 1 : 0);
export const crossScore = (c: Candidate) => Math.min((c.also_seen || []).length * 2, 4);
export const srcQuality = (c: Candidate) => (c.src_quality != null ? c.src_quality : 1);

export function attBase(c: Candidate): number {
  return recScore(c) * 2 + earliness(c) + fitScore(c) + srcQuality(c) + crossScore(c);
}
export const att = (c: Candidate) => attBase(c) + fbAdj(c);

export function attWhy(c: Candidate): string {
  const d = srcDate(c);
  const reason = c.feedback?.reason;
  return `attention ${att(c)} = freshness ${recScore(c) * 2} (${d ? `source date ${d}` : "source date UNKNOWN"}) + earliness ${earliness(c)} + Project A fit ${fitScore(c)} + source quality ${srcQuality(c)} + cross-source confirmation ${crossScore(c)} + ${fbTxt(c)}${reason ? ` (${reason})` : ""}`;
}

/** v1 lensRank: the Investment Manager lens ranks by attention v2 final (+feedback), then attention. */
export function lensRank(a: Candidate, b: Candidate, im: boolean): number {
  if (!im) return att(b) - att(a);
  const fa = (a.attention_v2?.final || 0) + fbAdj(a);
  const fb = (b.attention_v2?.final || 0) + fbAdj(b);
  return fb - fa || att(b) - att(a);
}

export const gateOk = (c: Candidate) => !c.attention_v2?.gated;

export function scoreTxt(c: Candidate, im: boolean): string {
  const a = c.attention_v2 || {};
  if (a.final == null) return `att ${att(c)}`;
  return im ? `A ${a.score} · L ${(a.lens ?? 0) >= 0 ? "+" : ""}${a.lens} · F ${a.final}` : `att ${a.score}`;
}

export function thesis(c: Candidate): string {
  const t = c.attention_v2?.explain || c.description || "";
  return t.length > 130 ? `${t.slice(0, 127)}…` : t;
}

export const tierLbl = (c: Candidate) => (c.discovery_tier === "pre_company" ? "PRE-COMPANY" : c.discovery_tier === "grant" ? "GRANT" : "ANNOUNCEMENT");

/** A machine analysis that started more than 10 minutes ago (or never) is stale. */
export function aiStale(c: Candidate): boolean {
  if (!c.analysis_started_at) return true;
  const t = new Date(c.analysis_started_at.replace(" ", "T"));
  return Date.now() - t.getTime() > 600_000;
}
