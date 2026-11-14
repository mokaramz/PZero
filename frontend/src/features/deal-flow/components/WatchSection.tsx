import { Link } from "react-router-dom";

import { useWatch } from "@/features/watchlist/api";
import { TriggerList } from "@/features/watchlist/components/TriggerList";
import { companyOf, pagesLine } from "@/features/watchlist/model/watch";
import styles from "../DealFlow.module.css";

/**
 * Candidate detail: what the WATCH sensors found for this company (the old `WatchSection`, review 037a) — its pages,
 * a link to manage them on the Watchlist, and its triggers with Reviewed / Dismiss. No "Check now" here, as in the old
 * app: it lives on the Watchlist.
 */
export function WatchSection({ candidateId }: { candidateId: string }) {
  const q = useWatch();
  const w = companyOf(q.data, candidateId);
  return (
    <section className={styles.dsec} data-testid="watch-section">
      <h4 className={styles.hd}>On WATCH — sensors</h4>
      {w ? (
        <>
          <div className="small faint">
            {pagesLine(w)} · <Link to="/watchlist">manage on Watchlist</Link>
          </div>
          <TriggerList triggers={w.triggers} />
        </>
      ) : (
        <div className="small faint">Loading watch state…</div>
      )}
    </section>
  );
}
