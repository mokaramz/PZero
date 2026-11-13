/**
 * The Events endpoints — the ONE place their paths live. The payloads are the old ones (`/api/events`,
 * `/api/event_health`, `/api/wsig`, `/api/event_suggest`, the old `POST /api/weekend`, which never wrote, the
 * writes `event_save`, `event_verify`, `event_lead`, `event_debrief`, `scout_event`, and the source scan `event_find`)
 * under new paths.
 *
 * Reads (review 015): the old weekend POST is a GET now (decision b).
 * Writes (review 016), same-origin POSTs:
 * - `save` answers `{ok, id}`; after a merge `id` is `"<id>|merged:<name>"`. An edit of an unknown id is 404
 *   `{ok:false, error, id}`; an add that collides with an event of the same name and date but other details is 409
 *   `{ok:false, error, id, collision:true}`. With `convert_lead: <lead id>` the lead is converted in the SAME request
 *   (the old form sent `event_save` then `event_lead`); a retry answers `replayed: true`.
 * - `verify {id, verified}` → `{ok}` (`ok:false` for an unknown id); `lead {id, decision}` → `{ok}` (400 / 404).
 * - `debrief {id, people_met, leads:[{name, desc, url}], notes}` → `{ok, people, leads}`; a startup lead without a
 *   public evidence URL is a 400 that carries `lead: <index in the sent list>`, and nothing is saved.
 * - `scout {id, action}` → `{ok, status, event_id}` (`ok:false, error` for an unknown report / action), once per report.
 *
 * Source scan (review 017): `find {}` → the old `event_find` body `{added, accepted, dropped_past, dropped_dupe, health,
 * report}`. It runs synchronously (up to a few minutes); 409 `{ok:false, error}` while another scan runs or before the
 * legacy import.
 */
import { INBOX } from "@/features/deal-flow/hooks/useDealFlowData";
import { GRAPH, PEOPLE } from "@/features/network/api";
import { ApiError, get } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { EventHealthPayload, EventsPayload, WeekendMission, WsigItem } from "./model/types";

export const EVENTS = "events";
export const EVENT_HEALTH = "events/health";
export const WSIG = "events/wsig";
export const WEEKEND = "events/weekend";
export const SUGGEST = "events/suggest";
export const SAVE = "events/save";
export const VERIFY = "events/verify";
export const LEAD = "events/lead";
export const DEBRIEF = "events/debrief";
export const SCOUT = "events/scout";
export const FIND = "events/find";

/** What an event write makes stale: every Events read, Today (its event decisions read the same events) and the
 *  Investment Desk (its best event and the planned count). */
export const EVENT_KEYS = [EVENTS, WSIG, EVENT_HEALTH, "today", "home"];
/** A debrief also creates people and Deal Flow candidates; a Scout 00 action changes the Scout reports Deal Flow reads. */
export const DEBRIEF_KEYS = [...EVENT_KEYS, PEOPLE, GRAPH, INBOX];
export const SCOUT_KEYS = [...EVENT_KEYS, INBOX];

/** The old action labels (Background activity and the "✓ … — done" toast). */
export const LABEL = {
  save: "Saving the event",
  verify: "Checking the event",
  lead: "Saving the lead",
  debrief: "Saving the debrief",
  find: "Searching for events",
} as const;

export type WsigPayload = { ranked: WsigItem[] };
export type WeekendPayload = { missions: WeekendMission[] };
export type SaveResult = { ok: boolean; id: string; replayed?: boolean };
export type DebriefResult = { ok: boolean; people: string[]; leads: number };
export type ScoutResult = { ok: boolean; status?: string; event_id?: string };

export function useEvents() {
  return useApi<EventsPayload>(EVENTS);
}

export function useEventHealth() {
  return useApi<EventHealthPayload>(EVENT_HEALTH);
}

/** "Where should I go?" over the next `days` days (the old `wsig?days=`; the server defaults to 14). */
export function useWsig(days: string) {
  return useApi<WsigPayload>(WSIG, { days });
}

/** The sourcing-weekend missions for one window — a read, fetched when the operator builds the plan. */
export function fetchWeekend(start: string, end: string, signal?: AbortSignal) {
  return get<WeekendPayload>(WEEKEND, { start, end }, { signal });
}

/** The existing event a refused add collides with (409 `collision`), or null for any other failure. */
export function collisionOf(e: unknown): { id: string; message: string } | null {
  if (!(e instanceof ApiError) || e.status !== 409) return null;
  const body = (e.body ?? {}) as { collision?: boolean; id?: unknown };
  if (!body.collision || typeof body.id !== "string" || !body.id) return null;
  return { id: body.id, message: e.message.startsWith("HTTP ") ? "An event with this name and date already exists." : e.message };
}

/** The debrief lead (index in the sent list) a 400 refused, with the server's message, or null. */
export function refusedLeadOf(e: unknown): { index: number; message: string } | null {
  if (!(e instanceof ApiError) || e.status !== 400) return null;
  const lead = ((e.body ?? {}) as { lead?: unknown }).lead;
  return typeof lead === "number" && Number.isInteger(lead) && lead >= 0 ? { index: lead, message: e.message } : null;
}

export const eventLink = (id: string) => `/events?event=${encodeURIComponent(id)}`;
