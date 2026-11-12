/**
 * Why a Founder Calls part is visible but does nothing yet (review 023, decisions b and c). Each keeps its place and
 * says why, until its backend is ported:
 * - the Call intelligence tabs (the old `GET call_prep` / `GET post_call`) read the Claim Index, identity and
 *   registries; a version built from founder calls alone would mark every claim "public verification needed";
 * - "Approve paid research" started a paid Scout Bridge job — the rewrite has no bridge yet.
 */
import { NOT_PORTED as CONVICTION } from "@/features/conviction/model/deferred";

export const NOT_PORTED = {
  intel: "The prep card and claim checks arrive with the claims & identity port",
  bridge: CONVICTION.bridge,
} as const;
