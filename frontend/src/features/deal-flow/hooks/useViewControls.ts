import { useCallback, useState } from "react";

import { usePref } from "@/lib/hooks";
import type { NaFilter, Workspace } from "../model/geo";
import type { RouteFilter, TriageKind, TriageScope } from "../model/triage";
import type { Candidate } from "../model/types";
import { placeOf, type ViewControls, type ViewFilter } from "../model/view";

/** Rows mounted at once (the inbox can hold ~1,000). */
export const PAGE = 50;

/**
 * The page's controls. Only the workspace is remembered (`pz:workspace`, as before); the rest starts fresh per visit.
 * The page size resets whenever the view changes: it is stored together with the view it was grown for.
 */
export function useViewControls() {
  const [ws, setWs] = usePref<Workspace>("workspace", "eu");
  const [naf, setNaf] = useState<NaFilter>("both");
  const [filter, setFilter] = useState<ViewFilter>("top");
  const [theme, setTheme] = useState("");
  const [im, setIm] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const [tScope, setTScope] = useState<TriageScope>("operating");
  const [tKind, setTKind] = useState<TriageKind>("ALL");
  const [tRoute, setTRoute] = useState<RouteFilter>("ANY");

  const controls: ViewControls = { ws, naf, theme, im, filter, tScope, tKind, tRoute };
  const viewKey = [ws, naf, theme, im, filter, tScope, tKind, tRoute].join("|");
  const [paging, setPaging] = useState({ key: viewKey, limit: PAGE });
  const limit = paging.key === viewKey ? paging.limit : PAGE;
  const showMore = () => setPaging({ key: viewKey, limit: limit + PAGE });

  /** Open the view in which this candidate is visible, and select it (deep links). */
  const show = useCallback(
    (c: Candidate) => {
      const place = placeOf(c);
      setWs(place.ws);
      setNaf("both");
      setTheme("");
      setFilter(place.filter);
      setSel(c.id);
    },
    [setWs],
  );

  return {
    controls,
    set: { setWs, setNaf, setFilter, setTheme, setIm, setTScope, setTKind, setTRoute },
    sel,
    setSel,
    limit,
    showMore,
    show,
  };
}
