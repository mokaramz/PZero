/**
 * The Revisit list (review 018, decision 0004): rejected candidates whose re-report carried a material change dated
 * after the rejection. The server sets `revisit` (only on candidates whose stored status is `rejected`) and
 * `revisit_count`; nothing here ranks or decides. The list is its own small view in front of the protected
 * `buildList` — it never changes that function's input, order or counts. Reopening stays the existing status control
 * (Mohamed's decision only).
 */
import type { Candidate, InboxPayload, Revisit, RevisitKind } from "./types";

export const REVISIT_KIND: Record<RevisitKind, string> = {
  funding_round: "New funding round",
  registry_event: "Registry event",
  founder_or_key_hire: "New founder or key hire",
  independent_corroboration: "Independent corroboration",
};

/** The human label of a change kind (an unknown kind is shown as sent, never dropped). */
export const revisitLabel = (kind: string) => (Object.hasOwn(REVISIT_KIND, kind) ? REVISIT_KIND[kind as RevisitKind] : kind);

export const isFlagged = (c: Candidate): c is Candidate & { revisit: Revisit } => c.revisit != null;

/** Exactly the flagged candidates — across every workspace, theme and NA sub-filter (the count is the whole inbox's),
 *  newest flag first; equal flag times keep the payload order (a stable sort). */
export function revisitList(all: Candidate[]): Candidate[] {
  return all.filter(isFlagged).sort((a, b) => (b.revisit.flagged_at || "").localeCompare(a.revisit.flagged_at || ""));
}

/** The chip's count: the server's `revisit_count`, else the flags in the payload. */
export const revisitCount = (ib: Pick<InboxPayload, "candidates" | "revisit_count">) => ib.revisit_count ?? ib.candidates.filter(isFlagged).length;

/** "https://www.registry.example.org/x" → "registry.example.org" (the URL as sent if it does not parse). */
export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** "2026-11-10T08:15:00+00:00" → "2026-11-10": dates read as the rest of the detail's dates (ISO days). */
export const isoDay = (s: string | null | undefined) => (s ? s.slice(0, 10) : "");
