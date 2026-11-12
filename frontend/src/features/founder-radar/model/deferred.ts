/**
 * Why a Founder Radar control is visible but does nothing (review 026a, decision h). It keeps its place and its text,
 * and says why: "Ask Scout 00 for identity evidence" created a Scout Bridge job; the Scout Bridge is never ported.
 * (The founder scan and the company research runs went live with review 026b.)
 */
import { NOT_PORTED as CONVICTION } from "@/features/conviction/model/deferred";

export const NOT_PORTED = {
  bridge: CONVICTION.bridge,
} as const;
