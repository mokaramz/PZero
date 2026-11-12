/**
 * The "News sources" tab's pure logic, ported line for line from the old `features/news/NewsSources.tsx`: which source
 * is best FOR WHICH PURPOSE — measured, never one universal score.
 */
import type { Tone } from "@/components/ui";
import { NOT_PORTED } from "./deferred";
import type { Best, Rate, SourceRow, SourcesPayload, Window } from "./types";

/** The four windows; the default is 90 days (the server answers 90 for anything else). */
export const WINDOWS: Array<{ value: Window; label: string }> = [
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
  { value: "180", label: "180 days" },
  { value: "all", label: "All time" },
];
export const DEFAULT_WINDOW: Window = "90";

export const STATUS: Record<string, Tone> = { ACTIVE: "green", DEGRADED: "amber", PROBATION: "amber", TRUSTED: "green", EXTERNAL: "neutral", DISABLED: "neutral" };
export const statusTone = (status: string): Tone => STATUS[status] || "neutral";

export const pct = (r?: Rate | null) => (r && r.rate !== null ? `${Math.round(r.rate * 100)}% (${r.k}/${r.n})` : "—");
export const hours = (h?: number) => (h === undefined ? "—" : h < 48 ? `${h} h` : `${Math.round(h / 24)} days`);
export const fmtAt = (at: string | null) => (at ? at.replace("T", " ").slice(0, 16) : "not yet");

/** The purposes with a measured leader. */
export const ranked = (best: Best[]) => best.filter((b): b is Best & { leader: NonNullable<Best["leader"]> } => b.state === "RANKED" && !!b.leader);

/** Purposes without enough evidence, grouped by what is missing (no fake ranking): [need, labels without "Best for"]. */
export function collecting(best: Best[]): Array<[string, string[]]> {
  return Object.entries(
    best
      .filter((b) => b.state !== "RANKED")
      .reduce<Record<string, string[]>>((acc, b) => ({ ...acc, [b.need || ""]: [...(acc[b.need || ""] || []), b.label.replace(/^Best (for )?/, "")] }), {}),
  );
}

export const biasLine = (bias: SourcesPayload["bias"]) => `${bias.multi_source} of ${bias.events} material events were reported by two or more sources.`;

/** "Germany · 96 articles · more reliable" (an external benchmark says so). */
export const sourceMeta = (s: SourceRow, scopes: Record<string, string>) =>
  `${s.kind === "external" ? "external benchmark" : s.home_scope ? scopes[s.home_scope] || s.home_scope : ""} · ${s.articles.n} articles · ${s.sample.toLowerCase()}`;

/* ------------------------------------------------------------------ the details of one source */
export const coverageLine = (s: SourceRow, scopes: Record<string, string>) =>
  Object.entries(s.recall).length
    ? Object.entries(s.recall)
        .map(([k, r]) => `${scopes[k] || k} ${pct(r)}`)
        .join(" · ")
    : "—";
export const speedLine = (s: SourceRow) =>
  `median ${hours(s.speed.median_h)} · within 24 h ${pct(s.speed.within_24h)} · first ${pct(s.speed.first)} (${s.speed.n} shared events, ${s.speed.precision}-precision)`;
export const earlyLine = (s: SourceRow) =>
  `${s.earliness.companies} companies mentioned ≥ 14 days before their material event` +
  `${s.earliness.median_lead_days !== null ? ` (median ${s.earliness.median_lead_days} days)` : ""}` +
  `${
    s.earliness.examples.length > 0
      ? ` — e.g. ${s.earliness.examples
          .slice(0, 3)
          .map((e) => `${e.company} ${e.lead_days} days`)
          .join(", ")}`
      : ""
  }`;
export const uniqueLine = (s: SourceRow) => `${s.unique.events} material events and ${s.unique.early_companies} early companies no other source had`;
export const relevanceLine = (s: SourceRow) => `${pct(s.articles.precision)} of its articles were material European events`;
export const originalityLine = (s: SourceRow) => `syndicated copies ${pct(s.originality.syndicated)} · press-release markers ${pct(s.originality.press_release)}`;
export const authorityLine = (s: SourceRow) =>
  `${s.authority.prior.toLowerCase()} · facts agreed ${s.authority.agree}, contradicted ${s.authority.contradicted}, open ${s.authority.open} (${s.authority.basis})`;

/**
 * The technical health line. The Swiss deal ticker (`deal_flow_reuse`) took its health from System health, which is not
 * ported yet (028a decision e): it reads UNKNOWN with that reason, whatever the payload says.
 */
export function technical(s: SourceRow): { deferred: boolean; text: string } {
  if (s.kind === "deal_flow_reuse") return { deferred: true, text: `UNKNOWN (${NOT_PORTED.health})` };
  const t = s.technical;
  return {
    deferred: false,
    text: `${t.state.toLowerCase()}${t.runs ? ` · fetched ${t.ok}/${t.runs} runs` : ""}${t.streak ? ` · ${t.streak} failure(s) in a row` : ""} (${t.basis})`,
  };
}
