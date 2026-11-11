/**
 * The Conviction endpoints (review 011) — the ONE place their paths live. The shapes are the old ones
 * (`/api/pipeline`, `/api/meta`, `/api/save`, `/api/status`, `/api/case`) under new paths.
 *
 * `POST save` answers `{ok, slug}`; 400 `{ok:false, error}`; 404 for an unknown `inbox_id`; 409
 * `{ok:false, duplicate:true, slug, error?}` when a new company's name already has an entry (Keep included).
 */
import { ApiError, isMissingEndpoint } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { CaseView } from "./model/case";
import type { Meta, Pipeline } from "./model/types";

export const PIPELINE = "conviction/pipeline";
export const META = "conviction/meta";
export const SAVE = "conviction/save";
export const STATUS = "conviction/status";
export const CASE = "conviction/case";

/** What a Conviction write makes stale (the Deal Flow inbox too: a save can decide or link a candidate). */
export const CONVICTION_KEYS = [PIPELINE, CASE, "deal-flow/inbox"];

export type SaveResult = { ok: boolean; slug: string };

/** The whole Conviction set in one read, grouped and filtered on the client. */
export function usePipeline() {
  return useApi<Pipeline>(PIPELINE);
}

/** The scoring tables (archetypes, ladders, enums, portfolio): they change only with a release. */
export function useMeta() {
  return useApi<Meta>(META, undefined, { staleTime: Infinity });
}

/** The prepared case of one company. A missing endpoint or an unknown case (404) is the "not started" state. */
export function useCase(slug: string) {
  return useApi<CaseView>(CASE, { slug }, { retry: (n, e) => !isMissingEndpoint(e) && n < 1 });
}

/** The existing entry a refused save points to (409 duplicate), or null for any other failure. */
export function duplicateOf(e: unknown): { slug: string; message: string } | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const body = (e.body ?? {}) as { duplicate?: boolean; slug?: unknown };
  if (!body.duplicate || typeof body.slug !== "string" || !body.slug) return null;
  return { slug: body.slug, message: e.message.startsWith("HTTP ") ? "A company with this name already exists in Conviction." : e.message };
}

export const companyLink = (slug: string) => `/conviction?company=${encodeURIComponent(slug)}`;
