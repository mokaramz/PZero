import { EmptyState } from "@/components/ui";
import { useFr } from "../context";
import { NO_FILTERS, frMatch, type Filters } from "../model/logic";
import { matchingCompanies } from "../model/view";
import { CompanyCard } from "./CompanyCard";
import { LeadCard } from "./LeadCard";
import { PersonCard } from "./PersonCard";
import styles from "../FounderRadar.module.css";

/** Top Founder Leads / Near Matches (v1 renderViews for FR_VIEW top|near) and, while searching, the cross-bucket
 *  search block. */
export function LeadsView({ view, filters }: { view: "top" | "near"; filters: Filters }) {
  const { data } = useFr();
  const L = data.leads ?? { top: [], near: [] };
  const list = view === "top" ? L.top : L.near;
  return (
    <div data-testid="fr-leads">
      <p className={styles.intro}>
        {view === "top" ? (
          <>
            Up to 10 founders worth your attention first. <b>Machine-qualified candidate</b> = clean official-domain quoted facts + founder evidence
            (non-destructive ranking). <b>Human-confirmed Gold</b> = the sourced shared gate you confirmed. Network promotion always stays
            human-confirmed.
          </>
        ) : (
          "Founders with some sourced signal but not enough for a machine-qualified ranking yet."
        )}
      </p>
      {list.length ? (
        <div className={styles.list}>
          {list.map((l, i) => (
            <LeadCard key={l.id + ":" + i} l={l} />
          ))}
        </div>
      ) : (
        <EmptyState>
          No verified founders yet — honestly empty. A person appears here only when an official company/team/press page (or your own evidence-backed
          confirmation) explicitly names them as founder or co-founder of a named company. Run <b>Research company queue</b> in the Research Queue.
        </EmptyState>
      )}
      <SearchBlock filters={filters} />
    </div>
  );
}

/** Search results across every bucket: company leads first, then people. Searching never writes. */
function SearchBlock({ filters = NO_FILTERS }: { filters?: Filters }) {
  const { data, q } = useFr();
  if (!q) return null;
  const P = data.people.filter((p) => frMatch(p, filters, q));
  const C = matchingCompanies(data, q);
  return (
    <section className={styles.searchBlock} data-testid="fr-search-block">
      <p className={styles.intro}>
        <b>Search results for “{q}”</b> across every Founder Radar bucket — {P.length} people · {C.length} company leads (identity states unchanged)
      </p>
      <div className={styles.list}>
        {C.map((c, i) => (
          <CompanyCard key={c.key + ":" + i} c={c} />
        ))}
        {P.map((p, i) => (
          <PersonCard key={p.id + ":" + i} p={p} />
        ))}
      </div>
      {!P.length && !C.length && <EmptyState>No person or company lead matches.</EmptyState>}
    </section>
  );
}
