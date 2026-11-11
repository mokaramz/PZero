/**
 * The Network endpoints (review 013) — the ONE place their paths live; the Watchlist page uses them too. The shapes
 * are the old ones (`/api/people`, `/api/graph`, `/api/watchlist`, `/api/person_save`, `/api/talented`,
 * `/api/watch_log`) under new paths.
 *
 * `POST person_save` answers `{ok, id}`. An add (no `id`) whose generated id is taken is refused with 409
 * `{ok:false, duplicate:true, id, error}`; an edit of an unknown id is 404 `{error}`; a strong identifier that belongs to
 * someone else is 409 `{error}` without `duplicate`. Nothing is written in any of those cases.
 */
import { ApiError } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { PIPELINE } from "@/features/conviction/api";
import type { GraphPayload, PeoplePayload, PipelineSlice, WatchPerson } from "./model/types";

export const PEOPLE = "network/people";
export const GRAPH = "network/graph";
export const WATCHLIST = "network/watchlist";
export const PERSON_SAVE = "network/person_save";
export const TALENTED = "network/talented";
export const WATCH_LOG = "network/watch_log";

/** What a people write makes stale: every people view, and Conviction (it reads people for founders and the IMQ). */
export const NETWORK_KEYS = [PEOPLE, GRAPH, WATCHLIST, PIPELINE, "conviction/case"];

export type PersonSaveResult = { ok: boolean; id: string };
export type TalentedResult = { ok: boolean; created: string[] };

export function usePeople() {
  return useApi<PeoplePayload>(PEOPLE);
}

export function useGraph() {
  return useApi<GraphPayload>(GRAPH);
}

export function useWatchlist() {
  return useApi<{ people: WatchPerson[] }>(WATCHLIST);
}

/** The Conviction set (shared cache with the Conviction page): only slug / company / provisional score are read. */
export function usePipelineSlice() {
  return useApi<PipelineSlice>(PIPELINE);
}

/** The existing person a refused add points to (409 duplicate), or null for any other failure. */
export function duplicateOf(e: unknown): { id: string; message: string } | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const body = (e.body ?? {}) as { duplicate?: boolean; id?: unknown };
  if (!body.duplicate || typeof body.id !== "string" || !body.id) return null;
  return { id: body.id, message: e.message.startsWith("HTTP ") ? "A person with this name is already in your network." : e.message };
}

export const personLink = (id: string) => `/network?person=${encodeURIComponent(id)}`;
