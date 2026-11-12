import { useState } from "react";

import { EmptyState, Segmented } from "@/components/ui";
import { useFr } from "../context";
import { SEGMENTS, radarPeople, segmentCounts, type Filters, type Seg } from "../model/logic";
import type { Person, QueueResult } from "../model/types";
import { matchingCompanies, metricRows, researchList } from "../model/view";
import { LinkBtn } from "./bits";
import { CompanyCard } from "./CompanyCard";
import { FilterBar } from "./FilterBar";
import { PersonCard } from "./PersonCard";
import styles from "../FounderRadar.module.css";

/** The Research Queue: bucket segments, filters, person cards or the company qualification queue, and the "Truthful
 *  counts" metrics rail. */
export function ResearchView({ seg, setSeg, filters, setFilters }: { seg: Seg; setSeg: (s: Seg) => void; filters: Filters; setFilters: (f: Filters) => void }) {
  const { data, q } = useFr();
  const n = segmentCounts(radarPeople(data), data.network_states ?? []);
  const { list: L, hidden } = researchList(data, seg, filters, q);

  return (
    <div data-testid="fr-research">
      <div className={styles.segs}>
        <Segmented label="Founder Radar buckets" value={seg} onChange={setSeg} options={SEGMENTS.map(([k, l]) => ({ value: k, label: l, count: n[k] }))} />
      </div>
      <FilterBar filters={filters} setFilters={setFilters} />
      <div className={styles.researchGrid}>
        <div className={styles.list} data-testid="fr-list">
          {seg === "claim" ? (
            <ClaimList people={L} />
          ) : L.length ? (
            L.map((p, i) => <PersonCard key={p.id + ":" + i} p={p} />)
          ) : (
            <EmptyState>{seg === "gold" ? <GoldEmpty /> : "Nothing here."}</EmptyState>
          )}
          {seg !== "claim" && hidden > 0 && <p className={styles.intro}>{hidden} more not shown — narrow with the filters.</p>}
        </div>
        <aside className={styles.metrics} aria-label="Truthful counts">
          <h3>Truthful counts</h3>
          <Metrics />
        </aside>
      </div>
    </div>
  );
}

function GoldEmpty() {
  return (
    <>
      Nobody qualifies as Gold or Strong yet: founder-eligible evidence + identity + Project A fit + recent activity + an access path. Researchers stay
      under <b>Research &amp; spinout talent</b>; pipeline names under <b>Founder claims</b>.
    </>
  );
}

/** The company qualification queue (claim segment) and, while searching, the matching people. "Research next 5 leads"
 *  and the resumable company research queue, whose progress (`fr-rq-state`) shows once it has started. */
function ClaimList({ people }: { people: Person[] }) {
  const { data, q, actions } = useFr();
  const [rq, setRq] = useState<QueueResult | null>(null);
  const [running, setRunning] = useState(false);
  const C = matchingCompanies(data, q);
  const failed = Object.entries(rq?.failed ?? {});
  const skipped = rq?.skipped_no_domain ?? [];
  const runQueue = async () => {
    setRunning(true);
    await actions.researchQueue(setRq);
    setRunning(false);
  };
  return (
    <>
      <div className={styles.intro}>
        Queue ordered by <b>research priority</b> (never a quality score, never Gold/Strong) ·{" "}
        <LinkBtn onClick={() => actions.researchLeads()} disabled={actions.busy}>
          Research next 5 leads
        </LinkBtn>{" "}
        ·{" "}
        <LinkBtn onClick={runQueue} disabled={running}>
          Research company queue (all leads with an official domain, resumable)
        </LinkBtn>
        {(rq || running) && (
          <div className={styles.rqState} role="status" data-testid="fr-rq-state">
            {rq ? (
              <>
                Company research queue: <b>{rq.done}</b> done · <b>{rq.remaining}</b> remaining · {failed.length} failed
                {skipped.length ? " · skipped (no official domain): " + skipped.join(", ") : ""}
                {rq.resume ? " · resumable — press again to continue" : " · complete"}
                {failed.length > 0 && <div>failures: {failed.map(([k, v]) => `${k}: ${v}`).join("; ")}</div>}
              </>
            ) : (
              "Company research queue: starting…"
            )}
          </div>
        )}
      </div>
      {C.length ? (
        C.map((c, i) => <CompanyCard key={c.key + ":" + i} c={c} />)
      ) : (
        <EmptyState>{q ? `No company lead matches “${q}” (company name, claimed / scout-reported / linked founder names).` : "No company leads to qualify."}</EmptyState>
      )}
      {q && (
        <>
          <p className={styles.intro}>
            <b>People matching “{q}”</b> across every Founder Radar bucket ({people.length})
          </p>
          {people.length ? people.map((p, i) => <PersonCard key={p.id + ":" + i} p={p} />) : <EmptyState>No person matches.</EmptyState>}
        </>
      )}
    </>
  );
}

function Metrics() {
  const { data } = useFr();
  const m = data.metrics;
  if (!m) return null;
  return (
    <div className={styles.metricsBody} data-testid="fr-metrics">
      {metricRows(m).map((r) => (
        <div key={r.key}>
          <b>{r.value}</b> {r.label}
        </div>
      ))}
      <div className={styles.sub}>recorded {String(m.date || "")} · counts of recorded events, never inferred</div>
    </div>
  );
}
