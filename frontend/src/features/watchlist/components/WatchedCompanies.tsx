import { EmptyState, ErrorBox, Panel } from "@/components/ui";
import { useWatch } from "../api";
import { PAGE_CHECKS_DEFERRED } from "../model/watch";
import { CompanyRow } from "./CompanyRow";

/**
 * WATCH companies (the old `WatchedCompanies`, review 037a): what is monitored, what fired, and the human decision on
 * each trigger. Pages are saved and triggers acknowledged here; the page checks themselves arrive with 037b.
 */
export function WatchedCompanies() {
  const q = useWatch();
  return (
    <Panel
      title="Watched companies — WATCH is active, not a graveyard"
      data-testid="watched-companies"
      aside={<span className="small faint">Deterministic sensors · no model · nothing changes a decision</span>}
    >
      <p className="small faint">
        <b>Why am I seeing this?</b> Companies you put on WATCH come back automatically when reality changes. Two sensors: a later Deal Flow scan
        finds the company in a <i>new</i> source (funding news, grant registry), or an official page you attached gains a new line about a pilot,
        customer, funding, grant, launch, approval, hire… The first page check only records a baseline. The same evidence never alerts twice.
      </p>
      <p className="small faint" data-testid="watch-checks-deferred">
        {PAGE_CHECKS_DEFERRED}.
      </p>
      {q.error ? (
        <ErrorBox error={q.error} onRetry={() => void q.refetch()} />
      ) : !q.data ? null : q.data.companies.length ? (
        q.data.companies.map((c) => <CompanyRow key={c.key} c={c} />)
      ) : (
        <EmptyState>No companies on WATCH. In Deal Flow, choose WATCH for a company that is not interesting yet but could become so.</EmptyState>
      )}
    </Panel>
  );
}
