import { createContext, useContext, useEffect, useId, useRef, useState } from "react";

/** The one open disclosure of a region (null: all closed). */
export type DisclosureGroupState = { open: string | null; setOpen: (id: string | null) => void };

export const DisclosureGroupContext = createContext<DisclosureGroupState | null>(null);

/** Open state for one disclosure — single-open inside a DisclosureGroup, independent otherwise. */
export function useGroupedOpen(defaultOpen: boolean, key?: string): [boolean, (v: boolean) => void] {
  const group = useContext(DisclosureGroupContext);
  const auto = useId();
  const id = key ?? auto;
  const [own, setOwn] = useState(defaultOpen);
  const claimed = useRef(false);
  useEffect(() => {
    // a group member that asks to start open claims the slot once (only if nothing else is open)
    if (group && defaultOpen && !claimed.current && group.open === null) group.setOpen(id);
    claimed.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once, on mount
  }, []);
  if (!group) return [own, setOwn];
  return [group.open === id, (v: boolean) => (v ? group.setOpen(id) : group.open === id && group.setOpen(null))];
}
