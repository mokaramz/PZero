/**
 * Sources (v1 view `src`, review 021): the source registry with its health, the selected source's detail, the
 * geography × sector coverage, and the manual / watched sources. Reads `GET sources` (one call: the old page also read
 * `/api/inbox` for the scan report and the lists); the table and the detail write `POST sources/toggle` (see ./api).
 * The workspace is the one Deal Flow remembers (`pz:workspace`); its "Unresolved" view shows all sources here.
 */
import { useMemo, useState } from "react";

import { Async, Callout, PageHeader, Panel, Segmented } from "@/components/ui";
import { DEFAULT_WS_GEOS, type Workspace } from "@/features/deal-flow/model/geo";
import { usePref } from "@/lib/hooks";
import { useSources, useToggleSource } from "./api";
import { CoverageMatrix } from "./components/CoverageMatrix";
import { HealthSummary } from "./components/HealthSummary";
import { SourceDetail } from "./components/SourceDetail";
import { SourceLists } from "./components/SourceLists";
import { SourceTable } from "./components/SourceTable";
import { sourcesInWs, srcWs, WS_NOTE, wsGeoSet, type SrcWorkspace } from "./model/health";
import styles from "./Sources.module.css";

const WS_OPTIONS: Array<{ value: SrcWorkspace; label: string }> = [
  { value: "eu", label: "Europe" },
  { value: "na", label: "North America" },
  { value: "all", label: "All workspaces" },
];

export default function SourcesPage() {
  const [pref, setPref] = usePref<Workspace>("workspace", "eu");
  const ws = srcWs(pref);
  const [sel, setSel] = useState<string | null>(null);
  const q = useSources();
  const { toggle, isPending } = useToggleSource();
  const m = q.data;
  const set = useMemo(() => (m ? wsGeoSet(ws, m, m.ws_geos ?? DEFAULT_WS_GEOS) : []), [m, ws]);
  const list = useMemo(() => (m ? sourcesInWs(m, ws, set) : []), [m, ws, set]);
  const selId = sel ?? list[0]?.id ?? null;

  return (
    <>
      <PageHeader title="Sources" subtitle="Where Project Zero gets its edge." />
      <Async q={q} label="Loading source health…">
        {(m) => (
          <>
            <div className={styles.wsRow}>
              <Segmented<SrcWorkspace> label="Workspace" value={ws} onChange={setPref} options={WS_OPTIONS} />
              <span className="faint small">Shared with Deal Flow — the registry table and coverage matrix follow the workspace.</span>
            </div>
            <HealthSummary sources={m.sources} />
            <div className={styles.ws}>
              <div className={styles.listCol}>
                <header className={styles.ph}>
                  <h3>
                    Source registry{" "}
                    <small className="faint">
                      {m.sources.filter((s) => s.enabled).length} enabled of {m.sources.length}
                    </small>
                  </h3>
                  <span className="grow" />
                  <span className="faint small" data-testid="src-ws-note">
                    {WS_NOTE[ws]}
                  </span>
                </header>
                <SourceTable list={list} minReviewed={m.feedback_min_reviewed} sel={selId} onSel={setSel} onToggle={toggle} />
              </div>
              <aside className={styles.detCol} aria-label="Source detail">
                <SourceDetail s={m.sources.find((s) => s.id === selId)} m={m} report={m.report || []} onToggle={toggle} toggling={isPending} />
              </aside>
            </div>
            <Panel
              title={
                <>
                  Source coverage — geography × sector <small className="faint">reliability- and health-weighted, not source counts</small>
                </>
              }
            >
              <CoverageMatrix m={m} geos={set} />
            </Panel>
            <SourceLists manual={m.manual_sources || []} pages={m.pages || []} feeds={m.feeds || []} />
          </>
        )}
      </Async>
      <details className={styles.how2}>
        <summary>How Project Zero sources</summary>
        <Callout tone="blue">
          <b>Project Zero does NOT search the whole internet or LinkedIn.</b> It runs a <b>source registry</b> (sources.json): pre-company channels &amp;
          grant/award databases across Europe, the US and Canada — SBIR/NSF/NIH, UKRI, CORDIS/EIC, ESA BIC, accelerators — plus announcement feeds for discovery
          only. Sources are data, not code: coverage, health and yield are shown below. Every card is machine-tagged by archetype keywords; judging founders,
          market and timing is <b>your</b> job. Three things stay separate everywhere: <b>DISCOVERY source</b> (where found) · <b>EARLINESS</b> (how early we are)
          · <b>FUNDRAISING TIMING</b> (when contact is commercially useful).
        </Callout>
      </details>
    </>
  );
}
