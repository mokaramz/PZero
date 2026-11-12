/**
 * Founder Radar (v1 view `founders`, review 026a): output-first Top Founder Leads / Near Matches, the Research Queue
 * (bucket segments, the company qualification queue), Diagnostics (source coverage and health), and the evidence,
 * review, promote and import dialogs. Reads `GET founder-radar`; writes the `founder-radar/*` actions and Network's
 * `person_save` (see ./api).
 *
 * URL: `?view=top|near|research|diag` (default top; research opens the claim segment), `?seg=`, `?person=<id>` (the
 * evidence drawer) and `?review=<company key>` (the review drawer). The founder scan and the company research crawl
 * arrive with review 026b: their controls stay in place, disabled with the reason.
 */
import { useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { DeferredButton } from "@/components/Deferred";
import { Async, Button, PageHeader, Segmented } from "@/components/ui";
import { useDebounced } from "@/lib/hooks";
import { useFounderRadar } from "./api";
import { Diagnostics } from "./components/Diagnostics";
import { ImportModal } from "./components/ImportModal";
import { LeadsView } from "./components/LeadsView";
import { PersonDrawer } from "./components/PersonDrawer";
import { PromoteModal } from "./components/PromoteModal";
import { ResearchView } from "./components/ResearchView";
import { ReviewDrawer } from "./components/ReviewDrawer";
import { FounderRadarContext, type FrCtx } from "./context";
import { NOT_PORTED } from "./model/deferred";
import { NO_FILTERS, type Filters, type Seg, type View } from "./model/logic";
import type { FounderRadar } from "./model/types";
import { callLink, countsLine, initialSeg, viewOf, withView } from "./model/view";
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
            <DeferredButton reason={NOT_PORTED.scan} data-testid="fr-scan">
              Scan founder signals
            </DeferredButton>
          </div>
        }
      >
        <p className={styles.counts} data-testid="fr-counts">
          {countsLine(data, seg, query)}
        </p>
        <p className={styles.deferredNote} data-testid="fr-scan-deferred">
          {NOT_PORTED.scan}
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
