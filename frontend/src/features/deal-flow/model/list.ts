/**
 * The Deal Flow list: workspace scope first, then the filter (protected; old `logic.ts` `buildList`, v1 rules).
 * Each workspace has its own top 15; the theme filter is a lens. Sorts are stable, so ties keep the payload order
 * (the old inbox file order — the server keeps it, review 009 #2).
 */
import { gateOk, lensRank } from "./attention";
import { geoOk, type NaFilter, type Workspace } from "./geo";
import type { Candidate } from "./types";

export type Filter = "top" | "triage" | "pre" | "thisrun" | "new" | "research" | "watch" | "review" | "kept" | "rejected" | "baseline";
/** Filters `buildList` answers; `review` and `triage` have their own lists. */
export type ListFilter = Exclude<Filter, "review" | "triage">;

export const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: "top", label: "Attention queue" },
  { value: "triage", label: "Machine triage" },
  { value: "pre", label: "Pre-company only" },
  { value: "thisrun", label: "New this run" },
  { value: "new", label: "All to decide" },
  { value: "research", label: "Researching" },
  { value: "watch", label: "Watch" },
  { value: "review", label: "Agent Review Queue" },
  { value: "kept", label: "Kept" },
  { value: "rejected", label: "Rejected" },
  { value: "baseline", label: "Baseline" },
];

export const TOP_N = 15;

export type ListOptions = {
  ws: Workspace;
  naf: NaFilter;
  theme: string;
  im: boolean;
  filter: ListFilter;
  lastRun: string | null;
  /** Candidates kept out of the Attention queue (the triage router's `non_startup` queue). */
  skip?: (c: Candidate) => boolean;
};

export type BuiltList = { list: Candidate[]; hidden: number; counts: Record<string, number> };

const priority = (c: Candidate) => c.priority || 0;

export function buildList(all: Candidate[], opts: ListOptions): BuiltList {
  const scoped = all.filter((c) => geoOk(c, opts.ws, opts.naf) && (!opts.theme || (c.themes || []).includes(opts.theme)));
  const counts: Record<string, number> = {};
  for (const c of scoped) counts[c.decision] = (counts[c.decision] || 0) + 1;
  if (opts.filter === "top") {
    const queue = scoped
      .filter((c) => c.decision === "new" && gateOk(c) && !opts.skip?.(c))
      .sort((a, b) => lensRank(a, b, opts.im) || priority(b) - priority(a));
    return { list: queue.slice(0, TOP_N), hidden: Math.max(0, queue.length - TOP_N), counts };
  }
  let list: Candidate[];
  if (opts.filter === "pre") list = scoped.filter((c) => c.decision === "new" && c.discovery_tier === "pre_company").sort((a, b) => priority(b) - priority(a));
  else if (opts.filter === "thisrun") list = scoped.filter((c) => c.run_id === opts.lastRun && c.decision !== "baseline");
  else list = scoped.filter((c) => c.decision === opts.filter);
  return { list, hidden: 0, counts };
}
