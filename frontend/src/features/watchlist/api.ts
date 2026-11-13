/**
 * The WATCH endpoints (review 037a) — the ONE place their paths live; the Deal Flow WATCH section uses them too. They
 * are the old `/api/watch`, `/api/watch_target` and `/api/watch_ack`, under the old paths, with the old bodies:
 *
 * - `GET watch` → `{companies, labels, note}`: every Deal Flow `watch` candidate plus the active manual targets, each
 *   with its pages, page-check state and 10 newest triggers;
 * - `POST watch_target {name, urls[], candidate_id}` → `{ok, target}`; a 400 names the refusal ("company name
 *   required", "not a public http(s) URL: …"). It never changes a Deal Flow decision;
 * - `POST watch_ack {id, status: reviewed|dismissed}` → `{ok, kind:"status", trigger_id, status, at, note}`; the
 *   trigger stays on record. A 400 is "no such trigger" or a bad status. Both writes
 *   answer 409 before the legacy import; the action's error toast shows the server's text.
 *
 * "Check now" (`watch_check`) is review 037b: no request is ever made for it here.
 */
import { CASE, PIPELINE } from "@/features/conviction/api";
import { SYSTEM_HEALTH } from "@/features/health/api";
import { HOME } from "@/features/home/api";
import { INTEL } from "@/features/map/api";
import { TODAY } from "@/features/today/api";
import { useAction, useApi } from "@/lib/hooks";
import type { WatchAckAnswer, WatchAckBody, WatchPayload, WatchTargetAnswer, WatchTargetBody } from "./model/types";

export const WATCH = "watch";
export const WATCH_TARGET = "watch_target";
export const WATCH_ACK = "watch_ack";

/** Saving pages: the old `watch` invalidation, plus Health (it counts the active manual targets from the same set). */
export const TARGET_KEYS = [WATCH, SYSTEM_HEALTH];
/** Acknowledging: the old `watch` and `today`, plus every other reader of the trigger log — Home, Health (open
 *  triggers), Conviction (a trigger re-opens a case) and the Map's intel. */
export const ACK_KEYS = [WATCH, TODAY, HOME, SYSTEM_HEALTH, PIPELINE, CASE, INTEL];

export function useWatch() {
  return useApi<WatchPayload>(WATCH);
}

export function useSavePages() {
  return useAction<WatchTargetBody, WatchTargetAnswer>(WATCH_TARGET, {
    invalidates: TARGET_KEYS,
    success: "Pages saved — first check records a baseline",
  });
}

export function useAckTrigger() {
  return useAction<WatchAckBody, WatchAckAnswer>(WATCH_ACK, {
    invalidates: ACK_KEYS,
    success: "Trigger updated (kept on record)",
  });
}
