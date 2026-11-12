/**
 * The Map endpoints (review 025) — the ONE place their paths live. The payloads are the old ones under new paths:
 * - `GET map/pins` → the old `/api/map` body plus `new_signals` (decision c; the old page read it from `/api/home`);
 * - `GET map/intel` → the old `/api/geo_intel` body;
 * - `GET map/ecosystem?city=` → the old `/api/geo_ecosystem` body (404 `{ok:false, error}` for an unknown city);
 * - `GET map/search?q=` → the old `/api/geo_search` body, asked only when the local search misses;
 * - `POST map/sourcing_day {city, date}` → the old `/api/sourcing_day` body (400 `{ok:false, error}`). It is a plan
 *   that is never stored, so it makes nothing stale.
 * The page's other reads are the ported Events, Network and Conviction ones (their own api modules).
 */
import { get } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import type { GeoDetail, GeoIntel, GeoSearch, MapData, SourcingDay } from "./model/types";

export const PINS = "map/pins";
export const INTEL = "map/intel";
export const ECOSYSTEM = "map/ecosystem";
export const SEARCH = "map/search";
export const SOURCING_DAY = "map/sourcing_day";

/** The old action label (Background activity and the "✓ … — done" toast). */
export const LABEL = { sourcingDay: "Building plan" } as const;

export function usePins() {
  return useApi<MapData>(PINS);
}

export function useIntel() {
  return useApi<GeoIntel>(INTEL, undefined, { staleTime: 60_000 });
}

export function useEcosystem(city: string) {
  return useApi<GeoDetail>(ECOSYSTEM, { city }, { staleTime: 60_000 });
}

/** The server-side search (Deal Flow, Scout 00, events and institutions → their ecosystem). */
export function searchMap(q: string) {
  return get<GeoSearch>(SEARCH, { q });
}

/** Build a sourcing-day plan: a read in effect, so it invalidates nothing. */
export function useSourcingDay() {
  return useAction<{ city: string; date: string }, SourcingDay>(SOURCING_DAY, { invalidates: [], label: LABEL.sourcingDay });
}
