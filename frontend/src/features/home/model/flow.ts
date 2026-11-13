/**
 * SIGNAL → DECISION — the data of the hero graphic (review 031a, the old `DecisionFlow`, unchanged): today's operating
 * flow in four stages, every count from state the desk already holds:
 *   Signals   candidates first seen in the last 14 days (their own first-seen dates)
 *   Review    missions waiting on the Smooth Operator's judgment (the same list as Priority missions)
 *   Manager   companies blocked on the Manager (portfolio-conflict gate)
 *   Decision  companies the Smooth Operator chose to follow (in Conviction)
 */
import type { Candidate } from "./types";

export const FLOW_DAYS = 14;
export const FLOW_W = 320;
export const FLOW_Y = 22;

export type Stage = { key: "signals" | "review" | "manager" | "decision"; label: string; n: number; hint: string };

/** The first day of the window, "YYYY-MM-DD" on the local calendar: 13 days before `now`. */
export function flowSince(now: Date): string {
  const since = new Date(now);
  since.setHours(0, 0, 0, 0);
  since.setDate(since.getDate() - (FLOW_DAYS - 1));
  return `${since.getFullYear()}-${String(since.getMonth() + 1).padStart(2, "0")}-${String(since.getDate()).padStart(2, "0")}`;
}

export function flowStages(candidates: Candidate[], review: number, manager: number, decided: number, now = new Date()): Stage[] {
  const from = flowSince(now);
  const fresh = candidates.filter((c) => String(c.first_seen || c.detected_on || "").slice(0, 10) >= from).length;
  return [
    { key: "signals", label: "Signals", n: fresh, hint: `new · ${FLOW_DAYS} days` },
    { key: "review", label: "Review", n: review, hint: "need you" },
    { key: "manager", label: "Manager", n: manager, hint: "blocked" },
    { key: "decision", label: "Decision", n: decided, hint: "in Conviction" },
  ];
}

/** Each node sits on its label column's centre. */
export const flowXs = (n: number) => Array.from({ length: n }, (_, i) => ((i + 0.5) * FLOW_W) / n);

/** One calm journey line: gentle S-curves between the stages, no chart axis, no fake trend. */
export function flowPath(xs: number[], y = FLOW_Y): string {
  return xs.slice(1).reduce((acc, x, i) => {
    const x0 = xs[i];
    const m = (x0 + x) / 2;
    const dy = i % 2 ? 9 : -9;
    return `${acc} C ${m} ${y + dy}, ${m} ${y - dy}, ${x} ${y}`;
  }, `M ${xs[0]} ${y}`);
}

export const flowLabel = (stages: Stage[]) => `Today's operating flow: ${stages.map((st) => `${st.label} ${st.n} (${st.hint})`).join(" → ")}`;
