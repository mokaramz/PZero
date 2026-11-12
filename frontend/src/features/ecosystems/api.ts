/**
 * The Ecosystems endpoints (review 022) — the ONE place their paths live. The payloads are the old ones under new paths.
 *
 * - `GET ecosystems/coverage` → the old `/api/coverage` body (coverage intelligence per ecosystem and source family).
 * - `GET ecosystems/registry` → the old `/api/city_registry` body (curated + detected cities).
 * - `GET ecosystems/eco?city=` → the old `/api/eco?city=` body (one city's page).
 * - `POST ecosystems/coverage/adopt {id, confirm: true}` → `{ok:true, source_id, note}` | `{ok:true, already:true, source_id}`;
 *   a refusal is `{ok:false, error}` (HTTP 200, or 409 before the legacy import) and reaches the UI as a failure toast.
 */
import { SOURCES } from "@/features/sources/api";
import { useAction, useApi } from "@/lib/hooks";
import { adoptMessage } from "./model/coverage";
import type { AdoptResult, CityPage, CityRegistry, Coverage } from "./model/types";

export const COVERAGE = "ecosystems/coverage";
export const REGISTRY = "ecosystems/registry";
export const ECO = "ecosystems/eco";
export const ADOPT = "ecosystems/coverage/adopt";

/** What an adoption makes stale: the coverage, and the Sources registry (the adopted watcher is a configured source). */
export const ADOPT_KEYS = [COVERAGE, SOURCES];

/** The old action label (Background activity and the "✕ … failed" toast). */
export const LABEL = { adopt: "Adopting the source" } as const;

export function useCoverage() {
  return useApi<Coverage>(COVERAGE);
}

export function useCityRegistry() {
  return useApi<CityRegistry>(REGISTRY);
}

export function useCityPage(city: string) {
  return useApi<CityPage>(ECO, { city });
}

/** Adopt ONE audit candidate as a configured watcher — explicit, always with `confirm: true`. */
export function useAdoptCandidate() {
  return useAction<{ id: string; confirm: true }, AdoptResult>(ADOPT, { invalidates: ADOPT_KEYS, label: LABEL.adopt, success: adoptMessage });
}
