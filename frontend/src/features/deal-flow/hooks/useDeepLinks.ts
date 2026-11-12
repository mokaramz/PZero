import { useQueryClient } from "@tanstack/react-query";
import { useEffect, type RefObject } from "react";
import { useSearchParams } from "react-router-dom";

import { get } from "@/lib/api";
import type { RouteState } from "../model/triage";
import type { Candidate, InboxPayload } from "../model/types";
import { linkFilter, linkRoute, type ViewFilter } from "../model/view";
import { INBOX_KEY } from "./useDealFlowData";

const KEYS = ["candidate", "review", "filter", "find", "route", "ns"] as const;
/** Old id namespaces the backend resolves (`candidate` = current ids, plus the retired views' item ids). */
const NAMESPACES = new Set(["candidate", "scout_intake", "native_scout"]);

/**
 * The survivor of an id through the detail read: an old id absorbed by a merge, or an old Scout Intake / Native item
 * id in its own namespace (whose string may equal an unrelated current id — so it is never matched locally).
 */
async function survivorOf(id: string, ns: string): Promise<string | null> {
  try {
    const query = ns === "candidate" ? undefined : { ns };
    const r = await get<{ candidate?: { id?: string } }>(`deal-flow/candidates/${encodeURIComponent(id)}`, query);
    return r.candidate?.id ?? null;
  } catch {
    return null;
  }
}

type Handlers = {
  show: (c: Candidate) => void;
  setFilter: (f: ViewFilter) => void;
  setRoute: (r: RouteState) => void;
  /** the Find bar row: `?find=1` focuses its first button */
  findRef: RefObject<HTMLElement | null>;
};

/**
 * Deep links (global search, Investment Desk), consumed once the inbox is there and then removed from the URL:
 *   ?candidate=<id>  open the candidate's workspace / decision view and select it (an absorbed id selects its survivor)
 *   &ns=<namespace>  the id is an old item id of a retired view (`scout_intake`, `native_scout`): resolved by the server
 *   ?review=<id>     the review overlay is not ported: the candidate is selected, nothing else happens
 *   ?filter=<f>      preselect a filter chip
 *   ?route=<state>   preselect a machine-triage routing view
 *   ?find=1          scroll to and focus the Find control — never starts a scan
 * None of them sends a POST.
 */
export function useDeepLinks(ib: InboxPayload | undefined, { show, setFilter, setRoute, findRef }: Handlers) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  useEffect(() => {
    if (!ib || !KEYS.some((k) => params.has(k))) return;
    const linked = params.get("candidate") || params.get("review");
    const ns = params.get("ns") ?? "candidate";
    if (linked && NAMESPACES.has(ns)) {
      const c = ns === "candidate" ? ib.candidates.find((x) => x.id === linked) : undefined;
      if (c) show(c);
      else
        void survivorOf(linked, ns).then((id) => {
          const now = qc.getQueryData<InboxPayload>(INBOX_KEY) ?? ib;
          const s = id ? now.candidates.find((x) => x.id === id) : undefined;
          if (s) show(s);
        });
    }
    const f = linkFilter(params.get("filter"));
    if (f) setFilter(f);
    const r = linkRoute(params.get("route"));
    if (r) setRoute(r);
    if (params.get("find")) {
      requestAnimationFrame(() => {
        findRef.current?.scrollIntoView?.({ block: "center" });
        findRef.current?.querySelector("button")?.focus();
      });
    }
    const next = new URLSearchParams(params);
    for (const k of KEYS) next.delete(k);
    setParams(next, { replace: true });
  }, [ib, params, setParams, show, setFilter, setRoute, findRef, qc]);
}
