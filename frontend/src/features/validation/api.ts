/**
 * The Validation endpoints (review 027a) — the ONE place their paths live. Both are reads; the payloads are the old
 * ones under new paths:
 * - `GET validation` → the old `GET /api/validation` body (same keys, same order). It never writes: today's daily
 *   snapshot is computed in memory (decision a). `news` (decision b) and `native_bridge` (decision d) answer
 *   `{available: false, reason}`; the page shows its own reasons (./model/deferred).
 * - `GET validation/scout_packet?cycle=` → the old `GET /api/validation_scout_packet` body `{cycle, companies, text, sha,
 *   counts}`; its News and source-network sections are deferred (decision c).
 * The writes (outcome, audit, retract, benchmark import, marking the packet as handed over) arrive with review 027b;
 * until then their controls are disabled with `NOT_PORTED.writes` and nothing here can call them.
 */
import { get } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Packet, ValidationPayload } from "./model/types";

export const VALIDATION = "validation";
export const SCOUT_PACKET = "validation/scout_packet";

export function useValidation() {
  return useApi<ValidationPayload>(VALIDATION, undefined, { staleTime: 30_000 });
}

/** Prepare the Scout 00 feedback packet for one cycle ("" = every cycle). A read: nothing is logged. */
export function fetchScoutPacket(cycle: string) {
  return get<Packet>(SCOUT_PACKET, { cycle });
}
