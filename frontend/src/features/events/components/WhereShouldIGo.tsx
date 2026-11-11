import { Button } from "@/components/ui";
import type { EventRecord, WsigItem } from "../model/types";
import styles from "../Events.module.css";

type Props = {
  days: string;
  onDays: (d: string) => void;
  ranked: WsigItem[] | undefined;
  loading: boolean;
  events: EventRecord[];
  onOpen: (id: string) => void;
};

/** "Where should I go?" — evidence ordering × travel + open contacts (GET wsig?days=). */
export function WhereShouldIGo({ days, onDays, ranked, loading, events, onOpen }: Props) {
  const acts = (w: WsigItem) => {
    const ac = events.find((x) => x.id === w.id)?.action ?? {};
    return (
      <div className={styles.wsActs}>
        <Button size="sm" onClick={() => onOpen(w.id)}>
          Open
        </Button>
        {ac.state === "sold_out" ? (
          <span className={styles.wsTag}>Sold out</span>
        ) : ac.state === "waitlist" ? (
          <a className={styles.wsBtn} href={ac.url} target="_blank" rel="noreferrer">
            Sold out — check waitlist ↗
          </a>
        ) : w.url ? (
          <a className={styles.wsBtn} href={w.url} target="_blank" rel="noreferrer">
            Register ↗
          </a>
        ) : null}
      </div>
    );
  };
  const meta = (w: WsigItem) => (
    <div className={styles.wsMeta}>
      {w.start} · {w.event_score != null ? `evidence ordering score ${w.event_score}` : "not yet scorable"} · {w.priority}
      {w.deadline && (
        <>
          {" "}· <span className={styles.wsDl}>register by {w.deadline}</span>
        </>
      )}
    </div>
  );
  const top = ranked?.[0];
  const rest = ranked?.slice(1, 4) ?? [];

  return (
    <section className={styles.wsig} aria-labelledby="wsig-h" data-testid="wsig">
      <div className={styles.wsHead}>
        <h3 id="wsig-h">Where should I go?</h3>
        <select aria-label="Where should I go window" value={days} onChange={(e) => onDays(e.target.value)}>
          <option value="7">7 days</option>
          <option value="14">14 days</option>
          <option value="21">21 days</option>
          <option value="30">30 days</option>
        </select>
      </div>
      <div className={styles.wsSub}>Evidence ordering × travel + open contacts.</div>
      {loading && !ranked ? (
        <div className={styles.wsSub}>Loading…</div>
      ) : !top ? (
        <div className={styles.wsEmpty}>No dated upcoming events in this window.</div>
      ) : (
        <>
          <div className={styles.wsTop}>
            <div className={styles.wsRank}>{top.rank != null ? `trip ordering score ${top.rank}` : "not yet scorable"}</div>
            <div className={styles.wsName}>
              {top.city || "?"} — {top.name}
            </div>
            {meta(top)}
            <p className={styles.wsWhy}>{top.reason}</p>
            {top.extra && <div className={styles.wsMeta}>{top.extra}</div>}
            {acts(top)}
          </div>
          {rest.length > 0 && (
            <div className={styles.wsRest}>
              {rest.map((w, i) => (
                <details key={w.id} className={styles.wsRow}>
                  <summary>
                    <span className={styles.wsPos}>{i + 2}</span>
                    <span className="grow">
                      {w.city || "?"} — {w.name}
                    </span>
                    <span>{w.rank ?? "—"}</span>
                  </summary>
                  {meta(w)}
                  <div className={styles.wsWhy}>
                    {w.reason}
                    {w.extra ? ` · ${w.extra}` : ""}
                  </div>
                  {acts(w)}
                </details>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
