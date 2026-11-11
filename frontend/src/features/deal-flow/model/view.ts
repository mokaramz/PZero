/**
 * What the Deal Flow page shows for the current controls (the old page's `view` memo, as a pure function).
 * The ranking itself is the protected `buildList` / `triageList`; this only picks which one answers.
 */
import { region, type NaFilter, type Workspace } from "./geo";
import { buildList, FILTERS, type BuiltList, type Filter } from "./list";
import { isNonStartup, ROUTE_LABEL, triageList, type RouteFilter, type RouteState, type TriageKind, type TriageScope, type TriageSummary } from "./triage";
import type { Candidate, InboxPayload } from "./types";

export type ViewControls = {
  ws: Workspace;
  naf: NaFilter;
  theme: string;
  im: boolean;
  filter: Filter;
  tScope: TriageScope;
  tKind: TriageKind;
  tRoute: RouteFilter;
};

/** `null` for the Agent Review Queue (its own list, not ported yet). */
export function candidateView(ib: InboxPayload, tri: Record<string, TriageSummary> | undefined, v: ViewControls): BuiltList | null {
  if (v.filter === "review") return null;
  if (v.filter === "triage") {
    const list = tri ? triageList(ib.candidates, tri, v.tScope, v.tKind, v.tRoute) : [];
    return { list, hidden: 0, counts: buildList(ib.candidates, { ws: "all", naf: v.naf, theme: "", im: v.im, filter: "new", lastRun: ib.last_run }).counts };
  }
  // Attention queue: non-startup records (universities, Catapults, incumbents …) stay out of the operating view.
  return buildList(ib.candidates, { ws: v.ws, naf: v.naf, theme: v.theme, im: v.im, filter: v.filter, lastRun: ib.last_run, skip: tri ? isNonStartup(tri) : undefined });
}

/** Filters that are not available yet (their list arrives with a later port). */
export const DEFERRED_FILTERS: ReadonlySet<Filter> = new Set<Filter>(["review"]);

/** A `?filter=` value the page can open, else null. */
export function linkFilter(v: string | null): Filter | null {
  const f = FILTERS.find((x) => x.value === v)?.value;
  return f && !DEFERRED_FILTERS.has(f) ? f : null;
}

/** Where a linked candidate is visible: its workspace and its decision's list (undecided → "All to decide"). */
export function placeOf(c: Candidate): { ws: Workspace; filter: Filter } {
  const r = region(c);
  return { ws: r === "eu" ? "eu" : r === "unknown" ? "unk" : "na", filter: c.decision === "new" ? "new" : c.decision };
}

/** A `?route=` value the triage view understands, else null. */
export const linkRoute = (v: string | null): RouteState | null => (v && Object.hasOwn(ROUTE_LABEL, v) ? (v as RouteState) : null);
