import { useState, type ReactNode } from "react";

import { DisclosureGroupContext } from "./groupContext";

/** Wrap a region's disclosures: opening one collapses the previously open one (max 1 open per region). */
export function DisclosureGroup({ children, defaultOpen = null }: { children: ReactNode; defaultOpen?: string | null }) {
  const [open, setOpen] = useState<string | null>(defaultOpen);
  return <DisclosureGroupContext.Provider value={{ open, setOpen }}>{children}</DisclosureGroupContext.Provider>;
}
