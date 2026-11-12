/**
 * Founder Radar (v1 view `founders`, review 026a): output-first Top Founder Leads / Near Matches, the Research Queue
 * (bucket segments, the company qualification queue), Diagnostics (source coverage and health), and the evidence,
 * review, promote and import dialogs. Reads `GET founder-radar`; writes the `founder-radar/*` actions and Network's
 * `person_save` (see ./api).
 *
 * URL: `?view=top|near|research|diag` (default top; research opens the claim segment), `?seg=`, `?person=<id>` (the
 * evidence drawer) and `?review=<company key>` (the review drawer). "Scan founder signals" and the company research runs
 * (review 026b) are synchronous; a scan answered with `{started: true}` is polled until the scan time changes.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { useToast } from "@/components/Toast";
import { Async, Button, PageHeader, Segmented } from "@/components/ui";
import { useApi, useDebounced } from "@/lib/hooks";
import { FOUNDER_RADAR, useFounderRadar, useScan } from "./api";
import { Diagnostics } from "./components/Diagnostics";
import { ImportModal } from "./components/ImportModal";
import { LeadsView } from "./components/LeadsView";
import { PersonDrawer } from "./components/PersonDrawer";
import { PromoteModal } from "./components/PromoteModal";
import { ResearchView } from "./components/ResearchView";
import { ReviewDrawer } from "./components/ReviewDrawer";
import { FounderRadarContext, type FrCtx } from "./context";
import { NO_FILTERS, type Filters, type Seg, type View } from "./model/logic";
import type { FounderRadar } from "./model/types";
import { callLink, countsLine, initialSeg, scanFinished, scanToast, viewOf, withView } from "./model/view";
import { useFrActions } from "./useFrActions";
import styles from "./FounderRadar.module.css";

export default function FounderRadarPage() {
  const q = useFounderRadar();
  return (
    <div className={styles.page}>
      <Async q={q} label="Loading Founder Radar…">
        {(d) => <Workbench data={d} />}
      </Async>
    </div>
  );
}

function Workbench({ data }: { data: FounderRadar }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const actions = useFrActions(data);
  const scan = useScanRun(data);

  const view = viewOf(params);
  const [seg, setSeg] = useState<Seg>(() => initialSeg(params, view));
  const researchInit = useRef(view === "research");
  const setView = (v: View) => {
    if (v === "research" && !researchInit.current) {
      researchInit.current = true;
      setSeg("claim"); // v1: the Research Queue opens on the company qualification queue
    }
    setParams(withView(params, v), { replace: true });
  };

  const [search, setSearch] = useState("");
  const query = useDebounced(search.trim().toLowerCase(), 120);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);

  const [founderId, setFounderId] = useState<string | null>(() => params.get("person"));
  const [reviewKey, setReviewKey] = useState<string | null>(() => params.get("review"));
  const [promoteId, setPromoteId] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  const ctx: FrCtx = useMemo(
    () => ({
      data,
      actions,
      q: query,
      openFounder: (id) => {
        setReviewKey(null);
        setFounderId(id);
      },
      openReview: (key) => {
        setFounderId(null);
        setReviewKey(key);
      },
      openPromote: (id) => setPromoteId(id),
      logCall: (c) => navigate(callLink(c)),
    }),
    [data, actions, query, navigate],
  );

  return (
    <FounderRadarContext.Provider value={ctx}>
      <PageHeader
        title="Founder Radar"
        subtitle="Unusually strong builders detected from permitted public sources — before their companies are obvious. Detected ≠ Watchlist ≠ Network: three states of one person record."
        actions={
          <div className={styles.headActions}>
            <input
              type="search"
              className={styles.search}
              aria-label="Search people"
              placeholder="Search people…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Button onClick={() => setImportOpen(true)}>Authorized import (CSV)</Button>
            <Button onClick={scan.run} busy={scan.scanning} data-testid="fr-scan">
              {scan.scanning ? "Scanning…" : "Scan founder signals"}
            </Button>
          </div>
        }
      >
        <p className={styles.counts} data-testid="fr-counts">
          {countsLine(data, seg, query)}
        </p>
      </PageHeader>

      <div className={styles.views}>
        <Segmented
          label="Founder Radar views"
          value={view}
          onChange={setView}
          options={[
            { value: "top", label: "Top Founder Leads", count: data.leads?.top.length ?? 0 },
            { value: "near", label: "Near Matches", count: data.leads?.near.length ?? 0 },
            { value: "research", label: "Research Queue", count: (data.companies ?? []).length },
            { value: "diag", label: "Diagnostics" },
          ]}
        />
      </div>

      {(view === "top" || view === "near") && <LeadsView view={view} filters={filters} />}
      {view === "research" && <ResearchView seg={seg} setSeg={setSeg} filters={filters} setFilters={setFilters} />}
      {view === "diag" && <Diagnostics />}

      <PersonDrawer personId={founderId} onClose={() => setFounderId(null)} />
      <ReviewDrawer companyKey={reviewKey} onClose={() => setReviewKey(null)} />
      <PromoteModal personId={promoteId} onClose={() => setPromoteId(null)} />
      <ImportModal open={importOpen} onClose={() => setImportOpen(false)} />
      {actions.dialog}
    </FounderRadarContext.Provider>
  );
}

/** Scan founder signals: the old page answered synchronously with the health report; a server that answers with a
 *  started job instead is polled (the radar, every 2 s) until `health.scan_time` changes. The radar shown here IS the
 *  polled query, so "finished" is derived from it; the toast fires once per finished scan time. */
function useScanRun(data: FounderRadar) {
  const toast = useToast();
  const scan = useScan();
  /** the scan time the started job must move past (null: no started job) */
  const [pollSince, setPollSince] = useState<string | null>(null);
  const h = data.health ?? {};
  const doneAt = pollSince !== null && h.scan_time && h.scan_time !== pollSince ? h.scan_time : null;
  const polling = pollSince !== null && !doneAt;
  // the page's own radar query, re-read every 2 s while polling (never an extra read on mount)
  useApi<FounderRadar>(FOUNDER_RADAR, undefined, { refetchInterval: polling ? 2000 : false, refetchOnMount: false });
  const doneText = doneAt ? scanToast(h) : "";
  const toasted = useRef<string | null>(null);
  useEffect(() => {
    if (!doneAt || toasted.current === doneAt) return;
    toasted.current = doneAt;
    toast.show(doneText, "ok");
  }, [doneAt, doneText, toast]);

  const run = async () => {
    setPollSince(null);
    try {
      const r = await scan.mutateAsync({});
      if (scanFinished(r)) toast.show(scanToast(r), "ok");
      else setPollSince(data.health?.scan_time ?? "");
    } catch {
      toast.show("Scan failed", "error"); // after the failure toast with the server's reason (a 409, a 503)
    }
  };
  return { run, scanning: scan.isPending || polling };
}
