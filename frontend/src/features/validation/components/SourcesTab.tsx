import { Panel } from "@/components/ui";
import type { NewsMetrics, ValidationPayload } from "../model/types";
import { newsTail, pct, sourceLead } from "../model/view";
import styles from "../Validation.module.css";
import { Benchmarks } from "./Benchmarks";

/** "Which sources work?" — value per discovery (not volume), the external benchmarks and the News benchmark. */
export function SourcesTab({ d }: { d: ValidationPayload }) {
  return (
    <div className={styles.page}>
      <Panel title="Best sources — value, not volume" data-testid="val-sources">
        <div className={styles.scroll}>
          <table className={styles.tbl}>
            <thead>
              <tr>
                <th>Source</th>
                <th title="companies this source produced">Found</th>
                <th title="found by this source only">Unique</th>
                <th>Pre-funding</th>
                <th title="machine KEEP or RESEARCH">Machine K/R</th>
                <th>You accepted</th>
                <th>Conviction</th>
                <th>Strong</th>
                <th>Median lead</th>
                <th title="first seen in the funding announcement itself — no lead time">Via own funding news</th>
                <th title="Ranking aid only: strong outcomes count most, the machine's opinion least, divided by (found + 5) so volume cannot buy rank">
                  Value / found
                </th>
              </tr>
            </thead>
            <tbody>
              {d.sources.slice(0, 12).map((s) => (
                <tr key={s.source_id}>
                  <td className={styles.name}>{s.source}</td>
                  <td>{s.discoveries}</td>
                  <td>{s.unique}</td>
                  <td>{pct(s.pre_funding_share)}</td>
                  <td>{pct(s.keep_research_rate)}</td>
                  <td>{s.mohamed_accepted}</td>
                  <td>{s.conviction}</td>
                  <td>{s.strong}</td>
                  <td>{sourceLead(s.median_lead_days, s.lead_n)}</td>
                  <td>{s.at_announcement}</td>
                  <td>{s.value_per_discovery.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Benchmarks b={d.benchmarks} />
      {d.news.available && <NewsBenchmark n={d.news} />}
    </div>
  );
}

/** The News benchmark. The old page hid it while News was unavailable; it now keeps its place and says why (decision b). */
function NewsBenchmark({ n }: { n: NewsMetrics }) {
  return (
    <Panel title="News benchmark — did we know them before the news?" data-testid="val-news">
      {n.available ? (
        <>
          <div className="small">
            {n.reviewed} material stories about companies with a verdict: <b>{n.caught_early}</b> caught early · <b>{n.known_late}</b> known late ·{" "}
            <b>{n.operational_misses}</b> operational misses · <b>{n.historical_cases}</b> historical cases · {n.not_yet_reviewed} not yet reviewed
            {newsTail(n)}.
          </div>
          <div className="small faint">
            The same events feed the lead-time numbers above — there is no separate News score. Details on the News &amp; Learning page.
          </div>
        </>
      ) : null}
    </Panel>
  );
}
