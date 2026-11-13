import { Link } from "react-router-dom";

import { StatusChip } from "@/components/focus";
import { Icon } from "@/components/Icon";
import { short } from "@/features/today/missions";
import { eventDate } from "../model/desk";
import type { HomePayload } from "../model/types";
import styles from "../Home.module.css";

/** The one upcoming event the server picked (the weekend first), or the line that says there is none. */
export function UpcomingEvent({ be }: { be: HomePayload["best_event"] }) {
  const date = eventDate(be?.start);
  return (
    <section className={styles.card} aria-label="Upcoming event" data-testid="desk-event" data-tone="event">
      <div className={styles.cardHead}>
        <Icon name="calendar" size={18} className={styles.headIcon} />
        <h2>{be?.weekend ? "This weekend" : "Upcoming event"}</h2>
      </div>
      {be ? (
        <>
          <div className={styles.event}>
            <span className={styles.dateTile} aria-hidden>
              {date ? (
                <>
                  <span>{date.toLocaleDateString("en-GB", { month: "short" })}</span>
                  <b>{date.getDate()}</b>
                  <span>{date.toLocaleDateString("en-GB", { weekday: "short" })}</span>
                </>
              ) : (
                <Icon name="calendar" size={18} />
              )}
            </span>
            <div className={styles.eventBody}>
              <b className={styles.eventName}>{be.name}</b>
              <span>{[be.city, be.start].filter(Boolean).join(" · ")}</span>
              {be.reason && <span className={styles.eventWhy}>{short(be.reason, 12)}</span>}
            </div>
          </div>
          <div className={styles.eventActions}>
            <Link className={styles.rowBtn} to="/events">
              Plan <Icon name="arrow" size={12} />
            </Link>
            {be.deadline && <StatusChip tone="attention">Register by {be.deadline}</StatusChip>}
            {be.url && (
              <a className={styles.headLink} href={be.url} target="_blank" rel="noreferrer">
                Details ↗
              </a>
            )}
          </div>
        </>
      ) : (
        <p className={styles.none}>No dated upcoming event — scan sources in Events.</p>
      )}
    </section>
  );
}
