import { createContext, useContext } from "react";

import type { CallContext, FounderRadar } from "./model/types";
import type { FrActions } from "./useFrActions";

/** What every Founder Radar part reads: the GET body, the writes, the search and the drawers it opens. */
export type FrCtx = {
  data: FounderRadar;
  actions: FrActions;
  /** trimmed, lower-cased search query (v1 frQuery) */
  q: string;
  openFounder: (id: string) => void;
  openReview: (key: string) => void;
  openPromote: (id: string) => void;
  logCall: (c: CallContext) => void;
};

export const FounderRadarContext = createContext<FrCtx | null>(null);

export function useFr(): FrCtx {
  const c = useContext(FounderRadarContext);
  if (!c) throw new Error("FounderRadarContext missing");
  return c;
}
