import { useCallback, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ContextInspector } from "@/components/attention";
import { useToast } from "@/components/Toast";
import { Async, Panel } from "@/components/ui";
import { companyLink } from "@/features/conviction/api";
import { EditCompanyDrawer } from "@/features/conviction/components/EditCompanyDrawer";
import { CandidateDetail } from "./components/CandidateDetail";
import { CandidateFilters } from "./components/CandidateFilters";
import { CandidateList } from "./components/CandidateList";
import { DealFlowHero } from "./components/DealFlowHero";
import { MachineZone } from "./components/MachineZone";
import { ResearchDrawer } from "./components/ResearchDrawer";
import { TriageBars } from "./components/TriageBars";
import { WorkspaceBar } from "./components/WorkspaceBar";
import { useInbox, useTriage } from "./hooks/useDealFlowData";
import { useDecision } from "./hooks/useDecision";
import { useDeepLinks } from "./hooks/useDeepLinks";
import { useViewControls } from "./hooks/useViewControls";
import { wsCounts } from "./model/geo";
import type { BuiltList } from "./model/list";
import { routeCounts, triageCounts } from "./model/triage";
import { candidateView } from "./model/view";
import styles from "./DealFlow.module.css";

/**
 * Deal Flow (review 009): the whole inbox ranked on the client by the protected rules, the selected candidate's
 * inspector, and the operator's decision (Keep opens the Conviction scoring form). Panels whose backend is not ported
 * yet keep their place, disabled.
 */
export default function DealFlowPage() {
  const q = useInbox();
  const ib = q.data;
  const triage = useTriage();
  const tri = triage.proposals;
  const { controls, set, sel, setSel, limit, showMore, show } = useViewControls();
  const { ws, naf, theme, im, filter, tScope, tKind, tRoute } = controls;
  const [researchId, setResearchId] = useState<string | null>(null);
  const [keepId, setKeepId] = useState<string | null>(null);
  const navigate = useNavigate();
  const findRef = useRef<HTMLDivElement | null>(null);

  useDeepLinks(ib, { show, setFilter: set.setFilter, setRoute: set.setTRoute, findRef });

  const counts = useMemo(() => (ib ? wsCounts(ib.candidates) : { eu: 0, na: 0, unk: 0 }), [ib]);
  const view = useMemo(
    () => (ib ? candidateView(ib, tri, { ws, naf, theme, im, filter, tScope, tKind, tRoute }) : null),
    [ib, tri, ws, naf, theme, im, filter, tScope, tKind, tRoute],
  );
  const tCounts = useMemo(() => (ib && tri ? triageCounts(ib.candidates, tri, tScope) : {}), [ib, tri, tScope]);
  const rCounts = useMemo(() => (ib && tri ? routeCounts(ib.candidates, tri) : {}), [ib, tri]);
  const selId = view && view.list.some((c) => c.id === sel) ? sel : (view?.list[0]?.id ?? null);
  const byId = useCallback((id: string | null) => (id && ib ? ib.candidates.find((c) => c.id === id) : undefined), [ib]);

  const selected = byId(selId);
  const researchC = byId(researchId);
  const keepC = byId(keepId);
  const detail = useDecision(selected);
  const research = useDecision(researchC);
  const toast = useToast();

  return (
    <>
      <Async q={q} label="Loading the candidate inbox…">
        {(ib) => (
          <>
            <DealFlowHero ib={ib} ws={ws} naf={naf} />
            <WorkspaceBar ws={ws} setWs={set.setWs} counts={counts} />
            <Panel className={styles.candPanel} title={<CandidatesTitle view={view} />}>
              <CandidateFilters
                ws={ws}
                naf={naf}
                setNaf={set.setNaf}
                filter={filter}
                setFilter={set.setFilter}
                theme={theme}
                setTheme={set.setTheme}
                themes={ib.themes}
                im={im}
                setIm={set.setIm}
              />
              {filter === "triage" && (
                <TriageBars
                  tRoute={tRoute}
                  setTRoute={set.setTRoute}
                  tScope={tScope}
                  setTScope={set.setTScope}
                  tKind={tKind}
                  setTKind={set.setTKind}
                  rCounts={rCounts}
                  tCounts={tCounts}
                  payload={triage.data}
                />
              )}
              {!view || !view.list.length ? (
                <div className={styles.emptyRow} data-testid="inbox-empty">
                  Nothing to decide in this view. Run <b>Find New Candidates</b>, or work the manual sources on the Sources page — that is where the edge
                  is.
                </div>
              ) : (
                <div className={styles.dfGrid} data-has-selection={selId ? "" : undefined}>
                  <CandidateList
                    list={view.list}
                    selId={selId}
                    im={im}
                    themes={ib.themes}
                    onSelect={setSel}
                    limit={limit}
                    onMore={showMore}
                    hidden={filter === "top" ? view.hidden : 0}
                    tri={tri}
                  />
                  <ContextInspector label="Candidate inspector" className={styles.inspector}>
                    <CandidateDetail
                      c={selected}
                      ib={ib}
                      im={im}
                      actions={{
                        decide: (d) => void detail.decide(d),
                        research: () => selected && setResearchId(selected.id),
                        keep: () => selected && setKeepId(selected.id),
                        busy: detail.busy || research.busy,
                      }}
                      tri={selId && tri ? tri[selId] : undefined}
                      triPending={selId ? triage.data?.pending?.[selId] : undefined}
                    />
                  </ContextInspector>
                </div>
              )}
            </Panel>
            <MachineZone ib={ib} findRef={findRef} />
          </>
        )}
      </Async>

      {researchC && (
        <ResearchDrawer
          key={researchC.id}
          c={researchC}
          busy={detail.busy || research.busy}
          onClose={() => setResearchId(null)}
          onDecide={async (d, notes) => {
            const ok = await research.decide(d, notes);
            if (ok && d === "research") toast.show("Saved as researching", "ok");
            return ok;
          }}
          onKeep={() => {
            setResearchId(null);
            setKeepId(researchC.id);
          }}
        />
      )}
      {/* Keep is a Conviction save with the candidate's inbox_id (review 011): on success the new entry opens */}
      {keepC && (
        <EditCompanyDrawer key={keepC.id} open candidate={keepC} onClose={() => setKeepId(null)} onSaved={(slug) => navigate(companyLink(slug))} />
      )}
    </>
  );
}

function CandidatesTitle({ view }: { view: BuiltList | null }) {
  return (
    <span className={styles.candTitle}>
      Candidates{" "}
      {view && (
        <small className="faint" data-testid="ib-count">
          {view.counts.new || 0} to decide · {view.counts.research || 0} researching · {view.counts.watch || 0} watching · {view.counts.kept || 0} kept ·{" "}
          {view.counts.rejected || 0} rejected · {view.counts.baseline || 0} baseline
        </small>
      )}
    </span>
  );
}
