import { Navigate, useSearchParams } from "react-router-dom";

import { DEAL_FLOW, scoutIntakeTarget } from "./legacyLinks";

/** `/scout-intake?item=<id>` → `/deal-flow?candidate=<id>&ns=scout_intake` (history entry replaced). */
export function ScoutIntakeRedirect() {
  const [search] = useSearchParams();
  return <Navigate replace to={scoutIntakeTarget(search)} />;
}

/** `/scout-bridge` → `/deal-flow` (history entry replaced). */
export function ScoutBridgeRedirect() {
  return <Navigate replace to={DEAL_FLOW} />;
}
