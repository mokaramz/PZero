import { lazy, type ComponentType, type LazyExoticComponent } from "react";

import type { IconName } from "@/components/Icon";

/**
 * Single source of truth for navigation + routing. `legacyView` is the v1 `show('<view>')` id, kept so deep links
 * like `/#pipe` (and the parity tests) can map old names to new routes.
 *
 * `page` is the view's lazily loaded page. A view without one is not ported yet: its route renders the NotPorted page
 * inside the shell, so every link still lands somewhere. Porting a view = adding
 * `page: lazy(() => import("@/features/<view>/<View>Page"))` to its item.
 */
export type NavItem = {
  path: string;
  label: string;
  icon: IconName;
  legacyView: string;
  page?: LazyExoticComponent<ComponentType>;
};

export type NavSection = { title: string | null; items: NavItem[] };

export const NAV: NavSection[] = [
  {
    title: null,
    items: [
      { path: "/", label: "Investment Desk", icon: "home", legacyView: "home" },
      { path: "/today", label: "Today", icon: "today", legacyView: "today" },
      { path: "/associate", label: "PZ Associate", icon: "heron", legacyView: "associate" },
      { path: "/health", label: "System health", icon: "pulse", legacyView: "health" },
    ],
  },
  {
    title: "Sourcing",
    items: [
      { path: "/deal-flow", label: "Deal Flow", icon: "search", legacyView: "inbox", page: lazy(() => import("@/features/deal-flow/DealFlowPage")) },
      { path: "/sources", label: "Sources", icon: "list", legacyView: "src" },
      { path: "/events", label: "Events", icon: "calendar", legacyView: "events" },
      { path: "/map", label: "Map", icon: "map", legacyView: "map" },
      { path: "/ecosystems", label: "Ecosystems", icon: "globe", legacyView: "eco" },
    ],
  },
  {
    title: "Judgment",
    items: [
      { path: "/conviction", label: "Conviction", icon: "conviction", legacyView: "pipe" },
      { path: "/radar", label: "Radar", icon: "radar", legacyView: "radar" },
      { path: "/founder-calls", label: "Founder Calls", icon: "phone", legacyView: "calls" },
      { path: "/evaluator", label: "Active Evaluator", icon: "chat", legacyView: "evaluator" },
      { path: "/validation", label: "Validation", icon: "validate", legacyView: "validation" },
      { path: "/news", label: "News & Learning", icon: "news", legacyView: "news" },
    ],
  },
  {
    title: "Network",
    items: [
      { path: "/founder-radar", label: "Founder Radar", icon: "target", legacyView: "founders" },
      { path: "/network", label: "Network", icon: "people", legacyView: "people" },
      { path: "/watchlist", label: "Watchlist", icon: "eye", legacyView: "watch" },
      { path: "/public-work", label: "Public work", icon: "pen", legacyView: "work" },
    ],
  },
];

export const ALL_ITEMS: NavItem[] = NAV.flatMap((s) => s.items);

/** v1 views that no longer have their own page: Scout Intake and Scout Bridge were merged into Deal Flow. */
export const RETIRED_VIEWS: Record<string, string> = { scout: "/deal-flow", bridge: "/deal-flow" };

export function pathForLegacyView(view: string): string | undefined {
  const item = ALL_ITEMS.find((i) => i.legacyView === view);
  if (item) return item.path;
  return Object.hasOwn(RETIRED_VIEWS, view) ? RETIRED_VIEWS[view] : undefined;
}
