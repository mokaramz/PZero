/** Where an intelligence link goes in the rewrite (review 025, decision d). The answers keep the old targets. */
import { scoutIntakeTarget } from "@/app/legacyLinks";
import { NOT_PORTED } from "./deferred";

/** `to` — an in-app route; `reason` — shown as plain text, with the reason when there is one. */
export type LinkTarget = { to: string } | { to: null; reason: string | null };

/**
 * - `/news…` → plain text, News & Learning is not ported;
 * - `/scout-intake?candidate=<id>` → `/deal-flow?candidate=<id>` (an absorbed Deal Flow candidate);
 *   `/scout-intake?item=<id>` → the old-id redirect target (resolved in the Scout Intake namespace);
 *   a bare `/scout-intake` → plain text, the merged view has no card to open;
 * - anything else (Conviction, Deal Flow, Network, Events) is a route of its own; no link → plain text.
 */
export function linkTarget(link: string | null | undefined): LinkTarget {
  if (!link) return { to: null, reason: null };
  const i = link.indexOf("?");
  const path = i < 0 ? link : link.slice(0, i);
  const search = new URLSearchParams(i < 0 ? "" : link.slice(i + 1));
  if (path === "/news" || path.startsWith("/news/")) return { to: null, reason: NOT_PORTED.news };
  if (path === "/scout-intake") {
    const candidate = search.get("candidate");
    if (candidate) return { to: `/deal-flow?${new URLSearchParams({ candidate })}` };
    if (search.get("item")) return { to: scoutIntakeTarget(search) };
    return { to: null, reason: NOT_PORTED.scoutIntake };
  }
  return { to: link };
}
