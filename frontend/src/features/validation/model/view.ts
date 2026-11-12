/**
 * The page's pure logic, ported line for line from the old `features/validation/*` (types.ts, ValidationPage.tsx,
 * Benchmarks.tsx, NativeBridge.tsx). Rendering stays in ../components; every string the page builds lives here.
 */
import type { Tone } from "@/components/ui";
import type {
  Alpha,
  BenchmarkSystem,
  Calibration,
  Measurement,
  NativeBridge,
  NativeBridgeMetrics,
  NewsMetrics,
  Outcome,
  Snapshot,
  ValidationPayload,
} from "./types";

export const pct = (x: number | null | undefined) => (x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`);
export const label = (s: string) => s.replace(/_/g, " ");
/** A rate below the minimum group size is not shown — only the count. */
export const collecting = (n: number, min: number) => `collecting (${n}/${min})`;

/** The five analytical questions, one at a time (the old FocusTabs ids; the active one is local state, no query param). */
export const QUESTIONS = [
  { id: "early", label: "Are we early?" },
  { id: "right", label: "Are we right?" },
  { id: "sources", label: "Which sources work?" },
  { id: "miss", label: "Where do we miss?" },
  { id: "cost", label: "What does it cost?" },
] as const;
export type Question = (typeof QUESTIONS)[number]["id"];

/** The "Quality conversion" groupings, in the old order (`conversion[dim]`). */
export const DIMS = [
  { value: "tier", label: "Discovery type" },
  { value: "pre_funding", label: "Pre-Funding" },
  { value: "capital_stage", label: "Capital stage" },
  { value: "theme", label: "Theme" },
  { value: "ecosystem", label: "Country" },
  { value: "scout", label: "Scout lane" },
] as const;
export type Dim = (typeof DIMS)[number]["value"];
export const dimLabel = (dim: Dim) => DIMS.find((x) => x.value === dim)?.label;

export const STATE_TONE: Record<string, Tone> = { KNOWN: "green", "PARTLY KNOWN": "blue", COLLECTING: "amber", "NOT YET MEASURABLE": "neutral" };
export const stateTone = (state: string): Tone => STATE_TONE[state] || "neutral";

export const MISS_TYPE: Record<string, string> = {
  never_found: "never seen",
  found_too_late: "seen too late",
  found_early_but_rejected: "seen early, rejected",
  watch_not_followed: "on WATCH, then strong",
  found_early_not_progressed: "seen early, left undecided",
};
export const missType = (t: string) => MISS_TYPE[t] || t;

/** The "What can we measure yet?" hint: how many metrics are in each state, in first-seen order ("2 known · 4 collecting"). */
export function measurementHint(measurement: Measurement[]): string {
  return Object.entries(measurement.reduce<Record<string, number>>((a, m) => ({ ...a, [m.state]: (a[m.state] ?? 0) + 1 }), {}))
    .map(([k, v]) => `${v} ${k.toLowerCase()}`)
    .join(" · ");
}

/** The line under a metric ("3 so far · needs: …"); PARTLY KNOWN states only what it needs. */
export const measureNeeds = (m: Measurement) => `${m.state === "PARTLY KNOWN" ? "" : `${m.n} so far · `}needs: ${m.needs}`;

/** The headline trends drawn as sparklines. */
export const TREND_SERIES: Array<[string, string]> = [
  ["found_this_month", "first seen this month"],
  ["pre_funding_share", "pre-funding share"],
  ["median_lead_days", "median lead days"],
  ["conviction", "Conviction size"],
];

/** The series with at least 3 numeric daily snapshots (a gap stays a gap: non-numbers become null). */
export function trendRows(snaps: Snapshot[]): Array<readonly [string, Array<number | null>]> {
  return TREND_SERIES.map(([k, l]) => [l, snaps.map((s) => (typeof s[k] === "number" ? (s[k] as number) : null))] as const).filter(
    ([, v]) => v.filter((x) => x !== null).length >= 3,
  );
}
export const trendNote = (n: number) => `Direction over ${n} daily snapshots — not a significance claim.`;

/** "Outcome evidence today": strongest count first, ties in the server's order. */
export const strengthLine = (strength: Record<string, number>) =>
  Object.entries(strength)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${label(k).toLowerCase()} ${v}`)
    .join(" · ");
/** "Age of discoveries", in the server's order. */
export const horizonLine = (horizon: Record<string, number>) =>
  Object.entries(horizon)
    .map(([k, v]) => `${k} ${v}`)
    .join(" · ");

export const whoWasRight = (cal: Calibration) =>
  Object.keys(cal.who_was_right).length
    ? Object.entries(cal.who_was_right)
        .map(([k, v]) => `${k} ${v}`)
        .join(" · ")
    : "no disagreements with a known outcome yet";

export const verificationLine = (vc: ValidationPayload["verification_calibration"]) =>
  Object.keys(vc).length
    ? Object.entries(vc)
        .map(([k, v]) => `${k}: ${v.accepted} accepted · ${v.rejected} rejected`)
        .join(" — ")
    : "none yet (founder / funding proposals appear in Conviction → Verification)";

/** The outcome ledger, newest first (the server keeps the last 30 in line order). */
export const newestFirst = (outcomes: Outcome[]) => outcomes.slice().reverse();

export const leadDays = (days: number | null) => (days === null ? "—" : `${days} d`);
export const sourceLead = (days: number | null, n: number) => (days === null ? "—" : `${days} d (n=${n})`);

/** The Scout 00 summary line ("3 Scout intake item(s) across cycle(s) c1, c2: SUCCESS 1 · PENDING 2."). */
export function scoutLine(scout: ValidationPayload["scout"]): string {
  const cls =
    Object.entries(scout.classification)
      .map(([k, v]) => `${k} ${v}`)
      .join(" · ") || "none yet";
  return `${scout.items} Scout intake item(s) across cycle(s) ${scout.cycles.join(", ") || "—"}: ${cls}.`;
}
/** The packet is prepared for the last cycle in the archive's order ("" = every cycle). */
export const latestCycle = (cycles: string[]) => cycles[cycles.length - 1] || "";

/** One benchmark system's line. */
export function benchmarkLine(s: BenchmarkSystem): string {
  return (
    `${s.companies} compan${s.companies === 1 ? "y" : "ies"} · PZ earlier for ${s.pz_earlier}, same day or later for ${s.pz_later_or_same}` +
    (s.median_days !== null ? ` · median ${s.median_days} days` : " · median shown from 5 companies")
  );
}

/** The tail of the News benchmark line (shown only when News is available). */
export function newsTail(n: NewsMetrics): string {
  return (
    (n.median_lead_days !== null && n.median_lead_days !== undefined ? ` · median lead ${n.median_lead_days} days` : "") +
    (n.preventable_misses ? ` · ${n.preventable_misses} preventable` : "") +
    (n.most_common_miss_cause ? ` · most common miss cause: ${label(n.most_common_miss_cause)}` : "")
  );
}

/* ------------------------------------------------------------------ the native search bridge pilot (never live here) */

export const BRIDGE_STEPS: [string, string][] = [
  ["hunts", "hunts"],
  ["new", "new companies"],
  ["investigate", "credible INVESTIGATE"],
  ["contact_yes", "would contact"],
  ["promoted", "promoted"],
  ["contacted", "founder contacts"],
  ["replied", "responses"],
  ["call", "calls"],
  ["sent_to_omar", "Manager handoffs"],
  ["omar_positive", "positive Manager outcomes"],
];
export const BRIDGE_COST: [string, string][] = [
  ["hunt", "hunt"],
  ["investigate", "credible INVESTIGATE"],
  ["promoted", "promoted company"],
  ["founder_conversation", "founder conversation"],
  ["omar_handoff", "Manager handoff"],
];
/** The pilot's metrics, or null when the panel is deferred: `{available: false, reason}` (the rewrite) or null (the
 *  old answer when the pilot could not be read). */
export const bridgeMetrics = (m: NativeBridge | undefined): NativeBridgeMetrics | null => (m && !("available" in m) ? m : null);
export const usd = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `$${v.toFixed(2)}`);
export const topAlpha = (rows: Alpha[]) =>
  rows
    .slice(0, 3)
    .map((r) => `${r.key} ${r.investigate}/${r.found}`)
    .join(" · ") || "—";
