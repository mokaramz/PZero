import { Badge, Callout, Spinner } from "@/components/ui";
import type { EventHealthPayload } from "../model/types";
import styles from "../Events.module.css";

const pill = (s?: string) =>
  s === "ok" ? <Badge tone="green">OK</Badge> : s === "failed" ? <Badge tone="red">FAILED</Badge> : <Badge tone="amber">CONFIG REQUIRED</Badge>;

const n = (v: number | undefined, dash = false) => (v ?? (dash ? "—" : 0));

/** Event source health — separate from startup-source health; persisted by the scanner (GET event_health). */
export function EventHealth({ h, loading }: { h: EventHealthPayload | undefined; loading: boolean }) {
  const t = h?.totals ?? {};
  return (
    <section id="event-health" className={styles.health} aria-labelledby="evh-h" data-testid="event-health">
      <div className={styles.healthHead}>
        <h3 id="evh-h">Event source health</h3>
        <span className="muted small">separate from startup-source health · persists across reloads</span>
      </div>
      {loading && !h ? (
        <Spinner />
      ) : !h?.scan_time ? (
        <div className="muted small">{h?.note || "No event scan yet."}</div>
      ) : (
        <>
          <div className={styles.hd}>Sources</div>
          <div className={styles.sum}>
            <span><b>{n(t.attempted)}</b> attempted</span>
            <span><b className={styles.green}>{n(t.ok)}</b> retrieved successfully</span>
            <span><b className={styles.green}>{n(t.productive, true)}</b> productive (≥1 parsed future event)</span>
            <span><b className={styles.amber}>{n(t.watch_only, true)}</b> watch-only / unstructured (retrieved, 0 event records)</span>
            <span><b className={styles.red}>{n(t.failed)}</b> failed</span>
            <span><b className={styles.amber}>{n(t.config_required)}</b> configuration required</span>
          </div>
          <div className={styles.hd}>Pipeline — this scan</div>
          <div className={styles.sum}>
            <span><b>{n(t.raw)}</b> retrieved items</span>
            <span>→ <b>{t.parsed ?? t.raw ?? 0}</b> parsed / structured</span>
            <span>→ <b>{n(t.future)}</b> future-dated</span>
            <span>→ <b>{t.ingested ?? t.accepted ?? 0}</b> ingested into the timeline</span>
            <span>· <b>{n(t.dups)}</b> duplicates merged</span>
            <span>· <b>{n(t.past)}</b> past dropped</span>
            <span>· <b>{n(t.policy_rejected)}</b> rejected by promotion policy</span>
            <span>· <b>{t.watcher_review ?? t.review ?? 0}</b> watcher items to Needs Review</span>
          </div>
          <div className={styles.hd}>Current inventory (all future events, assessed by evidence)</div>
          <div className={styles.sum}>
            <span><b>{n(t.structured_future, true)}</b> future events</span>
            <span>= <b className={styles.green}>{n(t.high_signal, true)}</b> high-signal</span>
            <span>+ <b>{n(t.needs_review, true)}</b> needs review</span>
            <span>+ <b>{n(t.rejected_irrelevant, true)}</b> general / rejected</span>
            <span>· <b>{n(t.missing_price, true)}</b> missing price</span>
            <span>· <b>{n(t.missing_location, true)}</b> missing location</span>
            <span>· <b>{n(t.missing_organizer, true)}</b> missing organizer</span>
            <span className="muted">
              scan {h.scan_time} · {n(t.seconds)}s
            </span>
          </div>
          {h.note && <Callout tone="amber">{h.note}</Callout>}
          <div className={styles.tableWrap}>
            <table className={styles.healthTable}>
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Kind</th>
                  <th>Retrieval</th>
                  <th>Productive</th>
                  <th>Retrieved</th>
                  <th>Future-dated</th>
                  <th>Ingested</th>
                  <th>Watcher → review</th>
                  <th>Past</th>
                  <th>Dups</th>
                  <th>Last successful</th>
                  <th>Reason / route</th>
                </tr>
              </thead>
              <tbody>
                {(h.sources ?? []).map((s, i) => (
                  <tr key={s.name + i}>
                    <td>
                      {s.url ? (
                        <a href={s.url} target="_blank" rel="noreferrer">
                          {s.name} ↗
                        </a>
                      ) : (
                        s.name
                      )}
                      {s.city && <span className="muted"> {s.city}</span>}
                    </td>
                    <td className="muted">{s.kind || ""}</td>
                    <td>{pill(s.status)}</td>
                    <td>{s.status === "ok" ? (s.future ?? 0) > 0 ? <Badge tone="green">YES</Badge> : <Badge tone="amber">WATCH-ONLY</Badge> : "—"}</td>
                    <td className={styles.num}>{s.raw || 0}</td>
                    <td className={styles.num}>{s.future || 0}</td>
                    <td className={styles.num}>{s.ingested ?? s.accepted ?? 0}</td>
                    <td className={styles.num}>{s.review || 0}</td>
                    <td className={styles.num}>{s.past || 0}</td>
                    <td className={styles.num}>{s.dups || 0}</td>
                    <td className="muted">{s.last_ok || "never"}</td>
                    <td className="muted">{s.note || s.route || ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
