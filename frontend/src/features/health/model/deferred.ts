/**
 * Absent subsystems are visible, not faked (review 032a, decision d). The server sends a key whose source is not
 * ported as `{"deferred": "<reason>"}` instead of the old data or the old "temporarily unavailable" fallback; the page
 * shows that reason as visible text wherever the data would be.
 *
 * And the action controls that are not ported yet (decision h): each keeps its place, label and order, is disabled
 * through the shared `useDeferred`, and shows one of these reasons next to it (one constant per reason, as
 * `features/deal-flow/model/deferred.ts`).
 */

/** A key the server could not fill because its subsystem is not ported yet. */
export type Deferred = { deferred: string };

/** A payload value that is either the data or its deferred reason. */
export type Maybe<T> = T | Deferred;

/** Is this value the deferred shape: an object whose only key is a non-empty `deferred` string? */
export function isDeferred(x: unknown): x is Deferred {
  if (!x || typeof x !== "object" || Array.isArray(x)) return false;
  const keys = Object.keys(x);
  const reason = (x as { deferred?: unknown }).deferred;
  return keys.length === 1 && keys[0] === "deferred" && typeof reason === "string" && reason.trim() !== "";
}

/** The reason when the value is deferred, else null. */
export const reasonOf = (x: unknown): string | null => (isDeferred(x) ? x.deferred : null);

/** The data when the value is present and not deferred, else undefined. */
export function ported<T>(x: Maybe<T> | null | undefined): T | undefined {
  return x == null || isDeferred(x) ? undefined : (x as T);
}

/** Why an action control (or a panel the page makes no request for) does nothing yet. */
export const NOT_PORTED = {
  /** "Run overdue now", in all of its places (032c) */
  runner: "The background-job runner is not ported yet.",
  /** "Back up now", "Test latest backup", "Safe repair" and the hardening panels (032b) */
  hardening: "Backups, integrity checks and model provenance arrive with the hardening port.",
  /** "Look for new sources" (the source-network run) and the source decisions (032b) */
  sourceNetwork: "The source network and its decisions arrive with the hardening port.",
} as const;

/** The one line next to the recorded job outcomes and ages, until the runner is ported (decision e). */
export const JOBS_SNAPSHOT = "Background jobs are not ported yet: job state and history are the imported snapshot.";
