import { Link } from "react-router-dom";

import { cx } from "@/lib/format";
import type { WsigItem } from "@/features/events/model/types";
import type { GeoIntel } from "../model/types";
import { dueText } from "../model/view";
import styles from "../Map.module.css";

/** The intelligence cards along the bottom (Opportunity / Where to go / Coverage gaps): each opens its city. */
export function GeoCards({ geo, shifted, onCity }: { geo?: GeoIntel; shifted: boolean; onCity: (c: string) => void }) {
  return (
    <div className={cx(styles.strip, shifted && styles.stripShift)} data-testid="geo-cards">
      {(geo?.cards ?? []).map((c) => (
        <button key={c.id} type="button" className={styles.stripCard} onClick={() => onCity(c.city)}>
          <span className={styles.hd}>{c.title}</span>
          <span className={styles.ellipsis}>{c.text}</span>
        </button>
      ))}
      {geo && !geo.cards.length && <span className={styles.stripCard}>Not enough geographic signal yet.</span>}
    </div>
  );
}

/** Explore mode's cards: the best event this weekend, the undecided Deal Flow candidates, the first follow-up due. */
export function ExploreCards({
  best,
  newSignals,
  due,
  shifted,
}: {
  best?: WsigItem;
  newSignals?: number;
  due?: { name: string; next_action?: string };
  shifted: boolean;
}) {
  return (
    <div className={cx(styles.strip, shifted && styles.stripShift)}>
      <Link to="/events" className={styles.stripCard}>
        <span className={styles.hd}>Best this weekend</span>
        {best ? (
          <span>
            <b>{best.name}</b> · {best.city} <span className={styles.green}>{best.rank}</span>
          </span>
        ) : (
          <span className="muted">no dated events yet</span>
        )}
      </Link>
      <Link to="/deal-flow" className={styles.stripCard}>
        <span className={styles.hd}>Deal Flow</span>
        <span>
          <b>{newSignals ?? "—"}</b> undecided candidates
        </span>
      </Link>
      <Link to="/network" className={styles.stripCard}>
        <span className={styles.hd}>Follow-ups due</span>
        {due ? (
          <span className={styles.ellipsis}>
            <b>{due.name}</b> · {dueText(due.next_action)}
          </span>
        ) : (
          <span className="muted">nothing overdue</span>
        )}
      </Link>
    </div>
  );
}
