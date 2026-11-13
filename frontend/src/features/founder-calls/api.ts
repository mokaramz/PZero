/**
 * The Founder Calls endpoints (review 023) — the ONE place their paths live. The bodies are the old ones under new paths.
 *
 * - `GET founder-calls/calls` → the old `/api/calls` body (the workspace plus the people and Conviction pickers).
 * - `GET founder-calls/memo?id=` → `{markdown, label}` | 404 `{error}`.
 * - `POST founder-calls/briefing {founder_id, confirm: true}` → `{markdown, label}` | 400 / 404 `{error}`.
 * - `POST founder-calls/save` (v1's `saveCall()` body) → `{ok, changed, call, founder_id, company_id, pipeline_slug?}` |
 *   400 `{error}`; 409 `{ok: false, error}` before the legacy import.
 * - `POST founder-calls/followup {id, done}` → `{ok, call}` | 404 `{error}`.
 * - `POST founder-calls/link {founder_id, person_id} | {company_id, pipeline_slug}` → `{ok, founder_id | company_id}` |
 *   400 / 404 `{error}` (an unknown founder answers `{ok: false, founder_id: null}`).
 *
 * Failures are `{error}` bodies without `ok`, as before: `lib/api` turns every one into an ApiError, so each reaches the
 * operator as a failure toast.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { PIPELINE } from "@/features/conviction/api";
import { get } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import type { CallsWorkspace, FollowupResult, LinkResult, MarkdownDoc, SaveBody, SaveResult } from "./model/types";

export const CALLS = "founder-calls/calls";
export const MEMO = "founder-calls/memo";
export const BRIEFING = "founder-calls/briefing";
export const SAVE = "founder-calls/save";
export const FOLLOWUP = "founder-calls/followup";
export const LINK = "founder-calls/link";

/** What a save, follow-up or link makes stale: the workspace, Conviction's pipeline and Today (they read the same calls). */
export const CALL_KEYS = [CALLS, PIPELINE, "today"];

/** The old action labels (Background activity and the "✓ … — done" / "✕ … failed" toasts); link and briefing had no
 *  label of their own and showed the generic one. */
export const LABEL = { save: "Saving the call", followup: "Saving the follow-up", link: "Working", briefing: "Working" } as const;

export function useCallsWorkspace() {
  return useApi<CallsWorkspace>(CALLS);
}

export function useSaveCall() {
  return useAction<SaveBody, SaveResult>(SAVE, { invalidates: CALL_KEYS, label: LABEL.save });
}

export function useFollowup() {
  return useAction<{ id: string; done: boolean }, FollowupResult>(FOLLOWUP, { invalidates: CALL_KEYS, label: LABEL.followup });
}

export function useLink() {
  return useAction<{ founder_id: string; person_id: string } | { company_id: string; pipeline_slug: string }, LinkResult>(LINK, {
    invalidates: CALL_KEYS,
    label: LABEL.link,
  });
}

/** The Manager briefing: generated on request only, never stored — nothing goes stale. */
export function useBriefing() {
  return useAction<{ founder_id: string; confirm: true }, MarkdownDoc>(BRIEFING, { invalidates: [], label: LABEL.briefing });
}

/** The call memo, read fresh on every click (never served from the cache). */
export function useFetchMemo() {
  const qc = useQueryClient();
  return useCallback(
    (id: string) => qc.fetchQuery({ queryKey: [MEMO, { id }], queryFn: () => get<MarkdownDoc>(MEMO, { id }), staleTime: 0 }),
    [qc],
  );
}
