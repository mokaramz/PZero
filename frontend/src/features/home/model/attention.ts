/** v1 client-side attention score (att / attWhy) — only used as the fallback metric and tooltip on the Desk. */
import type { Candidate } from "./types";

function srcDate(c: Candidate): string | null {
  if (c.source_date) return c.source_date;
  if ((c.date_kind === "published" || c.date_kind === "award") && /^\d{4}-\d{2}-\d{2}/.test(c.date ?? "")) return (c.date ?? "").slice(0, 10);
  return null;
}
function recScore(c: Candidate): number {
  const d = srcDate(c);
  if (!d) return 0;
  const age = (Date.now() - new Date(d).getTime()) / 864e5;
  return age <= 7 ? 3 : age <= 30 ? 2 : age <= 90 ? 1 : 0;
}
const fbAdj = (c: Candidate) => c.feedback?.adjustment ?? 0;
const tierPts = (c: Candidate) => (c.discovery_tier === "pre_company" ? 3 : c.discovery_tier === "grant" ? 2 : 1);
const fitPts = (c: Candidate) => Math.min((c.archetype_hits ?? []).length, 2) * 2 + ((c.twins ?? []).length ? 1 : 0);
const crossPts = (c: Candidate) => Math.min((c.also_seen ?? []).length * 2, 4);
const quality = (c: Candidate) => (c.src_quality != null ? c.src_quality : 1);

export function att(c: Candidate): number {
  return recScore(c) * 2 + tierPts(c) + fitPts(c) + quality(c) + crossPts(c) + fbAdj(c);
}

export function attWhy(c: Candidate): string {
  const d = srcDate(c);
  const a = fbAdj(c);
  const fb = `${c.feedback?.label || "Feedback-adjusted sourcing priority"} ${a > 0 ? "+" : ""}${a}`;
  return `attention ${att(c)} = freshness ${recScore(c) * 2} (${d ? `source date ${d}` : "source date UNKNOWN"}) + earliness ${tierPts(c)} + Project A fit ${fitPts(c)} + source quality ${quality(c)} + cross-source confirmation ${crossPts(c)} + ${fb}${c.feedback?.reason ? ` (${c.feedback.reason})` : ""}`;
}
