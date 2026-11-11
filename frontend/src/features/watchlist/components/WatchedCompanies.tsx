import { Panel } from "@/components/ui";
import { NOT_PORTED } from "@/features/network/model/deferred";

/**
 * WATCH companies (old `WatchedCompanies`): the panel keeps its place, title and explanation, but what is monitored,
 * what fired and the trigger decisions arrive with the WATCH sensors port — nothing is read or written here.
 */
export function WatchedCompanies() {
  return (
    <Panel
      title="Watched companies — WATCH is active, not a graveyard"
      data-testid="watched-companies"
      data-deferred=""
      aside={<span className="small faint">Deterministic sensors · no model · nothing changes a decision</span>}
    >
      <p className="small faint">
        <b>Why am I seeing this?</b> Companies you put on WATCH come back automatically when reality changes. Two sensors: a later Deal Flow scan
        finds the company in a <i>new</i> source (funding news, grant registry), or an official page you attached gains a new line about a pilot,
        customer, funding, grant, launch, approval, hire… The first page check only records a baseline. The same evidence never alerts twice.
      </p>
      <p className="small faint" data-testid="watched-companies-deferred">
        {NOT_PORTED.watchCompanies}.
      </p>
    </Panel>
  );
}
