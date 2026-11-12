/**
 * The Validation endpoints (reviews 027a, 027b) — the ONE place their paths live. The payloads are the old ones under
 * new paths.
 *
 * The reads:
 * - `GET validation` → the old `GET /api/validation` body (same keys, same order). It never writes: today's daily
 *   snapshot is computed in memory (027a decision a). `news` (decision b) and `native_bridge` (decision d) answer
 *   `{available: false, reason}`; the page shows its own reasons (./model/deferred).
 * - `GET validation/scout_packet?cycle=` → the old `GET /api/validation_scout_packet` body `{cycle, companies, text, sha,
 *   counts}`; its News and source-network sections are deferred (027a decision c).
 *
 * The writes (027b), each append-only; a refusal is a 400 `{ok: false, error}` with the old text, shown as the failure
 * toast:
 * - `POST validation/outcome` (the old `validation_outcome` body) → `{ok: true, entry}`;
 * - `POST validation/audit` (miss / false_positive) → `{ok: true, entry}`;
 * - `POST validation/retract {id, reason}` → `{ok: true, entry}`;
 * - `POST validation/benchmark_import {system, csv, confirm?}` → the old summary (no `ok`); a preview without `confirm`
 *   writes nothing and refreshes nothing;
 * - `POST validation/scout_packet {cycle, generated, sha}` (decision f) → the packet; a packet that changed since it was
 *   prepared is a 409 `{ok: false, error}` and logs nothing.
 * Every write refreshes `validation`, as before; the toasts and activity labels are the old ones.
 */
import { get } from "@/lib/api";
import { useAction, useApi } from "@/lib/hooks";
import type { Packet, ValidationPayload } from "./model/types";
import { importedMessage, type AuditFields, type AuditType, type BenchmarkFields, type BenchmarkSummary, type MarkBody, type OutcomeFields } from "./model/writes";

export const VALIDATION = "validation";
export const SCOUT_PACKET = "validation/scout_packet";
export const OUTCOME = "validation/outcome";
export const AUDIT = "validation/audit";
export const RETRACT = "validation/retract";
export const BENCHMARK_IMPORT = "validation/benchmark_import";

/** What every write makes stale. */
export const VALIDATION_KEYS = [VALIDATION];

/** The old action labels (Background activity and the "✓ … — done" / "✕ … failed" toasts). */
export const LABEL = {
  outcome: "Recording the outcome",
  audit: "Recording the audit",
  retract: "Retracting",
  packet: "Preparing the Scout 00 packet",
  benchmark: "Importing benchmark",
} as const;

/** The written log line, in insertion order. */
export type Written = { ok: true; entry: Record<string, unknown> };

export function useValidation() {
  return useApi<ValidationPayload>(VALIDATION, undefined, { staleTime: 30_000 });
}

/** Prepare the Scout 00 feedback packet for one cycle ("" = every cycle). A read: nothing is logged. */
export function fetchScoutPacket(cycle: string) {
  return get<Packet>(SCOUT_PACKET, { cycle });
}

export const useRecordOutcome = () =>
  useAction<OutcomeFields, Written>(OUTCOME, { invalidates: VALIDATION_KEYS, success: "Outcome recorded", label: LABEL.outcome });

export const useRecordAudit = () =>
  useAction<AuditFields & { type: AuditType }, Written>(AUDIT, { invalidates: VALIDATION_KEYS, success: "Audit recorded", label: LABEL.audit });

export const useRetract = () =>
  useAction<{ id: string; reason: string }, Written>(RETRACT, { invalidates: VALIDATION_KEYS, success: "Retracted (kept in history)", label: LABEL.retract });

/** The preview: a POST that writes nothing, so it refreshes nothing (the old generic "done" toast). */
export const useBenchmarkPreview = () => useAction<BenchmarkFields, BenchmarkSummary>(BENCHMARK_IMPORT, { invalidates: [], label: LABEL.benchmark });

export const useBenchmarkImport = () =>
  useAction<BenchmarkFields & { confirm: true }, BenchmarkSummary>(BENCHMARK_IMPORT, { invalidates: VALIDATION_KEYS, success: importedMessage, label: LABEL.benchmark });

/** Marking the packet as handed over (posted only after the copy succeeded, see ../useScoutPacket). */
export const useMarkPacket = () => useAction<MarkBody, Packet>(SCOUT_PACKET, { invalidates: VALIDATION_KEYS, label: LABEL.packet });
