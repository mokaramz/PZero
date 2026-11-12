/**
 * The Founder Radar endpoints (review 026a) — the ONE place their paths live. The bodies and answers are the old ones
 * under new paths:
 * - `GET founder-radar` → the old `GET founder_radar` body (people, companies, leads, counts, health, coverage, geo,
 *   metrics, states). A read never writes (decision a).
 * - `POST founder-radar/action {id, action, …}` → `{ok, person}` (the old `radar_action`). A refusal is HTTP 200
 *   `{ok:false, error}` ("unknown person", the promotion guard, …); an unknown `state` is now a 400 `{ok:false, error}`
 *   (decision f). `lib/api` turns both into a failure toast. A merge that needs confirmation answers
 *   `{ok:false, error, needs_confirmation:true}` and is read with `allowErrorField`.
 * - `POST founder-radar/import {csv, include_email, label}`, `company {key, fact | evidence}`, `promote {id, …}`,
 *   `boardy_brief {id}`, `pair {key, proposal, person}`, `review {key, confirm | reject, bindings}`;
 *   `POST founder-radar/proposals {key}` is a read through POST.
 * - The judgment is Network's `person_save {id, human_judgment}` (features/network/api).
 * - The fetching runs (review 026b), synchronous and one at a time: a second run is a 409 `{ok:false, error}`, a run the
 *   deadline cut off before its write is a 503 `{ok:false, error}`; both are failure toasts.
 *   - `POST founder-radar/scan {}` → the health report (`{started: true}` is tolerated: the page polls the radar);
 *   - `POST founder-radar/research {key} | {keys} | {} (the next 5 un-researched), refresh` → `{ok, researched}`;
 *   - `POST founder-radar/research_queue {batch: 3}` → one resumable batch (`postResearchQueue`, looped by the page).
 */
import { useQuery } from "@tanstack/react-query";

import { NETWORK_KEYS, PERSON_SAVE } from "@/features/network/api";
import { post } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import type {
  ActionResult,
  BoardyResult,
  FounderRadar,
  ImportResult,
  PromoteForm,
  PromoteResult,
  Proposals,
  QueueResult,
  ResearchResult,
  ReviewResult,
  ScanResult,
} from "./model/types";

export const FOUNDER_RADAR = "founder-radar";
export const ACTION = "founder-radar/action";
export const IMPORT = "founder-radar/import";
export const COMPANY = "founder-radar/company";
export const PROMOTE = "founder-radar/promote";
export const BOARDY_BRIEF = "founder-radar/boardy_brief";
export const PROPOSALS = "founder-radar/proposals";
export const PAIR = "founder-radar/pair";
export const REVIEW = "founder-radar/review";
export const SCAN = "founder-radar/scan";
export const RESEARCH = "founder-radar/research";
export const RESEARCH_QUEUE = "founder-radar/research_queue";

/** What a person or company write makes stale (the old `founder_radar`, `people`, `watchlist`): the radar and every
 *  people view (a radar person IS a Network person). */
export const FR_KEYS = [FOUNDER_RADAR, ...NETWORK_KEYS];
/** A review also changes the research record. */
export const REVIEW_KEYS = [...FR_KEYS, PROPOSALS];
/** A scan or research run changes the people, the companies and the research records. */
export const RUN_KEYS = [...FR_KEYS, PROPOSALS];

/** The old action labels (Background activity and the "✓ … — done" / "✕ … failed" toasts). */
export const LABEL = {
  action: "Saving",
  import: "Importing",
  company: "Saving the company link",
  promote: "Promoting",
  boardy: "Working",
  pair: "Pairing",
  review: "Saving the review",
  judgment: "Saving the person",
  scan: "Scanning founders",
  research: "Starting founder research",
} as const;

export function useFounderRadar() {
  return useApi<FounderRadar>(FOUNDER_RADAR);
}

/** The research record of one company (a read through POST, cached per company). */
export function useProposals(key: string) {
  return useQuery<Proposals>({ queryKey: [PROPOSALS, key], queryFn: () => post<Proposals>(PROPOSALS, { key }) });
}

export type ActionBody = { id: string; action: string } & Record<string, unknown>;

export const useRadarAction = () => useAction<ActionBody, ActionResult>(ACTION, { invalidates: FR_KEYS, label: LABEL.action });

/** A merge reads its refusal (it may ask for confirmation), so it goes through `post` with `allowErrorField`. */
export const postMerge = (body: { id: string; other: string; confirm?: true }) =>
  post<ActionResult>(ACTION, { id: body.id, action: "merge", other: body.other, ...(body.confirm ? { confirm: true } : {}) }, { allowErrorField: true });

export const useCompanyWrite = () => useAction<{ key: string } & Record<string, unknown>, { ok: boolean }>(COMPANY, { invalidates: FR_KEYS, label: LABEL.company });

export const useBoardyBrief = () => useAction<{ id: string }, BoardyResult>(BOARDY_BRIEF, { invalidates: FR_KEYS, label: LABEL.boardy });

export const useJudgment = () =>
  useAction<{ id: string; human_judgment: string }, { ok: boolean; id: string }>(PERSON_SAVE, { invalidates: FR_KEYS, success: "Judgment saved", label: LABEL.judgment });

export const usePromote = () =>
  useAction<{ id: string } & PromoteForm, PromoteResult>(PROMOTE, {
    invalidates: FR_KEYS,
    success: (r) => (r.ok ? "Now in Network — history preserved" : undefined),
    label: LABEL.promote,
  });

export const useImport = () => useAction<{ csv: string; label: string; include_email: boolean }, ImportResult>(IMPORT, { invalidates: FR_KEYS, label: LABEL.import });

export const useReview = () => useAction<{ key: string; bindings: Record<string, string>; confirm?: string[]; reject?: string[] }, ReviewResult>(REVIEW, { invalidates: REVIEW_KEYS, label: LABEL.review });

export const usePair = () => useAction<{ key: string; proposal: string; person: string }, { ok: boolean }>(PAIR, { invalidates: [PROPOSALS], label: LABEL.pair });

export type ResearchBody = { key?: string; keys?: string[]; refresh?: true };

export const useScan = () => useAction<Record<string, never>, ScanResult>(SCAN, { invalidates: RUN_KEYS, label: LABEL.scan });

export const useResearch = () => useAction<ResearchBody, ResearchResult>(RESEARCH, { invalidates: RUN_KEYS, label: LABEL.research });

/** One batch of the company research queue. As before, the queue is a plain POST: the page loops it, reports progress
 *  after every batch and toasts once at the end (no Background activity row per batch). */
export const postResearchQueue = () => post<QueueResult>(RESEARCH_QUEUE, { batch: 3 });
