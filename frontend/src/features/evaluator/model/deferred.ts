/**
 * Why an Active Evaluator part is visible but does nothing yet (review 024, decision a). "verify via Scout 00" created a
 * Scout Bridge job, and Attach / Dismiss acted on the evidence such a job staged — the rewrite has no bridge yet. Staged
 * evidence a session already holds is shown read-only.
 */
import { NOT_PORTED as CONVICTION } from "@/features/conviction/model/deferred";

export const NOT_PORTED = {
  bridge: CONVICTION.bridge,
} as const;
