/**
 * The Conviction endpoints (review 011) — the ONE place their paths live. The shapes are the old ones
 * (`/api/pipeline`, `/api/meta`, `/api/save`, `/api/status`, `/api/case`) under new paths.
 *
 * `POST save` answers `{ok, slug}`; 400 `{ok:false, error}`; 404 for an unknown `inbox_id`; 409
 * `{ok:false, duplicate:true, slug, error?}` when a new company's name already has an entry (Keep included).
 *
 * Radar, memo, email and weekly (review 019): `GET radar` (the old `/api/radar`), `GET memo?c=` / `GET email?c=` →
 * `{text}` (404 for an unknown company), `POST weekly {insight, question}` → `{text}`. The old `POST /api/run` wrote
 * `weekly_memo.html` and the `output/` memos & emails into a data folder; the rewrite has none, so "Generate Radar"
 * downloads `GET radar.html` (the same `weekly_memo.html`) instead.
 *
 * The dated why-now trigger (review 024): `POST imq_trigger {slug, kind, date, url, fact, confirm: true}` → the old
 * `{ok, trigger}`; a refusal is HTTP 200 `{ok: false, error}` (unknown company, no confirmation, a kind outside the
 * list, a date in the future, a source the evidence rules reject), which `lib/api` turns into a failure toast. The
 * Active Evaluator records it through the same endpoint.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { actions, friendlyError } from "@/lib/activity";
import { ApiError, download, isMissingEndpoint } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import type { CaseView } from "./model/case";
import type { WhyNow } from "./model/case";
import type { DocText, Meta, Pipeline, Radar } from "./model/types";

export const PIPELINE = "conviction/pipeline";
export const META = "conviction/meta";
export const SAVE = "conviction/save";
export const STATUS = "conviction/status";
export const CASE = "conviction/case";
export const RADAR = "conviction/radar";
export const RADAR_HTML = "conviction/radar.html";
export const MEMO = "conviction/memo";
export const EMAIL = "conviction/email";
export const WEEKLY = "conviction/weekly";
export const IMQ_TRIGGER = "conviction/imq_trigger";

/** What a Conviction write makes stale: the records and everything derived from them — the memo, the outreach email
 *  and the Radar (the old `PIPE_KEYS`; Codex H-141) — and the Deal Flow inbox (a save can decide or link a candidate). */
export const CONVICTION_KEYS = [PIPELINE, CASE, MEMO, EMAIL, RADAR, "deal-flow/inbox"];

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

/** The Radar: the 8 / 1 / 1 Top 10 slots, then the research queue, the conflict-gated and the watchlist. */
export function useRadar() {
  return useApi<Radar>(RADAR);
}

/** The Scout memo of one company. */
export function useScoutMemo(slug: string) {
  return useApi<DocText>(MEMO, { c: slug });
}

/** The timing-aware outreach email of one company; `null` reads nothing (the email drawer is closed). */
export function useOutreachEmail(slug: string | null) {
  return useApi<DocText>(EMAIL, { c: slug ?? "" }, { enabled: !!slug });
}

/** The Weekly Sourcing Update: it writes nothing, so nothing goes stale. */
export function useWeekly() {
  return useAction<{ insight: string; question: string }, DocText>(WEEKLY, { invalidates: [], label: "Preparing the weekly update" });
}

export type TriggerBody = WhyNow & { slug: string; confirm: true };
export type TriggerResult = { ok: boolean; trigger?: WhyNow & { label: string; by: string; recorded: string } };

/** "Record dated why-now trigger": the old label and success toast. `invalidates` is what the caller's view reads (the
 *  Conviction set by default; the evaluator adds its session). */
export function useImqTrigger(invalidates: string[] = CONVICTION_KEYS) {
  return useAction<TriggerBody, TriggerResult>(IMQ_TRIGGER, {
    invalidates,
    label: "Recording the why-now trigger",
    success: "Dated why-now trigger recorded — IMQ re-evaluated",
  });
}

const GENERATE_RADAR = "Generating the Radar";

/** "Generate Radar": downloads the Radar HTML (`weekly_memo.html`) with the same feedback as a POST action — a
 *  Background activity row the instant it is clicked, then a toast — and refreshes the Radar view. */
export function useGenerateRadar() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation<string, Error, void, { act: number }>({
    mutationFn: () => download(RADAR_HTML, undefined, "weekly_memo.html"),
    onMutate: () => ({ act: actions.start(GENERATE_RADAR) }),
    onSuccess: async (name, _v, ctx) => {
      await qc.invalidateQueries({ queryKey: [RADAR] });
      const message = `${name} (Radar) downloaded`;
      if (ctx) actions.finish(ctx.act, "COMPLETE", message);
      toast.show(message, "ok");
    },
    onError: (e, _v, ctx) => {
      const message = friendlyError(e.message, e instanceof ApiError ? e.status : undefined);
      if (ctx) actions.finish(ctx.act, "FAILED", message);
      toast.show(`✕ ${GENERATE_RADAR} failed — ${message}`, "error");
    },
  });
}

/** The existing entry a refused save points to (409 duplicate), or null for any other failure. */
export function duplicateOf(e: unknown): { slug: string; message: string } | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const body = (e.body ?? {}) as { duplicate?: boolean; slug?: unknown };
  if (!body.duplicate || typeof body.slug !== "string" || !body.slug) return null;
  return { slug: body.slug, message: e.message.startsWith("HTTP ") ? "A company with this name already exists in Conviction." : e.message };
}

export const companyLink = (slug: string) => `/conviction?company=${encodeURIComponent(slug)}`;
