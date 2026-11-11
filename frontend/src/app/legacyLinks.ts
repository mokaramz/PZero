/**
 * Old links that must keep landing somewhere after a view was retired.
 * Scout Intake and Scout Bridge were merged into Deal Flow: `/scout-intake?item=<id>` opens that candidate in Deal Flow
 * (`/deal-flow?candidate=<id>&ns=scout_intake`: the item id is an OLD Scout Intake id, resolved in its own namespace,
 * never matched against current candidate ids — review 009, Codex), `/scout-bridge` opens Deal Flow.
 */
export const DEAL_FLOW = "/deal-flow";

export function scoutIntakeTarget(search: URLSearchParams): string {
  const item = search.get("item");
  return item ? `${DEAL_FLOW}?${new URLSearchParams({ candidate: item, ns: "scout_intake" })}` : DEAL_FLOW;
}
