/**
 * The Events endpoints (review 015, read-only) — the ONE place their paths live. The payloads are the old ones
 * (`/api/events`, `/api/event_health`, `/api/wsig`, and the old `POST /api/weekend`, which never wrote) under new paths.
 * The old weekend POST is a GET now (review 015 decision b); the writes arrive in review 016, the source scan in 017.
 */
import { get } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { EventHealthPayload, EventsPayload, WeekendMission, WsigItem } from "./model/types";

export const EVENTS = "events";
export const EVENT_HEALTH = "events/health";
export const WSIG = "events/wsig";
export const WEEKEND = "events/weekend";

export type WsigPayload = { ranked: WsigItem[] };
export type WeekendPayload = { missions: WeekendMission[] };

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
