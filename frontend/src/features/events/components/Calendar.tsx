import { useState } from "react";

import { cx } from "@/lib/format";
import { addDays, dayMarks, monthGrid, shiftMonth, type Item } from "../model/workspace";
import styles from "../Events.module.css";

type Props = {
  items: Item[];
  today: string;
  date: string;
  month: string;
  past: boolean;
  onDate: (d: string) => void;
  onMonth: (ym: string) => void;
  onPast: (p: boolean) => void;
};

const WD = ["M", "T", "W", "T", "F", "S", "S"];

/** Month navigator: dots come only from real records (event · priority · planned). Clicking a day filters the list. */
export function Calendar({ items, today, date, month, past, onDate, onMonth, onPast }: Props) {
  const marks = dayMarks(items);
  const [y, m] = month.split("-").map(Number);
  const name = new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-GB", { month: "long", timeZone: "UTC" });
  return (
    <div className={styles.cal} data-testid="event-calendar">
      <div className={styles.calHead}>
        <span className={styles.calMonth}>{name}</span>
        <span className={styles.calYear}>{y}</span>
        <span className="grow" />
        <button type="button" className={styles.calNav} aria-label="Previous month" onClick={() => onMonth(shiftMonth(month, -1))}>
          ‹
        </button>
        <button type="button" className={styles.calNav} aria-label="This month" onClick={() => onMonth(today.slice(0, 7))}>
          •
        </button>
        <button type="button" className={styles.calNav} aria-label="Next month" onClick={() => onMonth(shiftMonth(month, 1))}>
          ›
        </button>
      </div>
      <div className={styles.calGrid} role="grid" aria-label={`${name} ${y}`}>
        {WD.map((w, i) => (
          <span key={i} className={styles.calWd} aria-hidden>
            {w}
          </span>
        ))}
        {monthGrid(month).map((d) => {
          const mk = marks.get(d);
          return (
            <button
              key={d}
              type="button"
              className={cx(styles.calDay, d.slice(0, 7) !== month && styles.calOut, mk && styles.calHas, d === today && styles.calToday, d === date && styles.calOn)}
              aria-pressed={d === date}
              aria-label={`${new Date(`${d}T12:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "long" })}: ${mk?.n ?? 0} event${mk?.n === 1 ? "" : "s"}`}
              tabIndex={mk || d === date ? 0 : -1}
              onClick={() => onDate(d === date ? "" : d)}
            >
              {Number(d.slice(8))}
              {mk && (
                <span className={styles.calDots} aria-hidden>
                  {mk.planned && <i className={styles.dotGo} />}
                  {mk.priority && <i className={styles.dotPrio} />}
                  {!mk.planned && !mk.priority && <i />}
                </span>
              )}
            </button>
          );
        })}
      </div>
      <div className={styles.calSeg} role="group" aria-label="Upcoming or attended">
        <button type="button" aria-pressed={!past} className={cx(!past && styles.calSegOn)} onClick={() => onPast(false)}>
          Upcoming
        </button>
        <button type="button" aria-pressed={past} className={cx(past && styles.calSegOn)} onClick={() => onPast(true)}>
          Attended
        </button>
      </div>
      <div className={styles.calLegend} aria-hidden>
        <span>
          <i />
          events
        </span>
        <span>
          <i className={styles.dotPrio} />
          priority
        </span>
        <span>
          <i className={styles.dotGo} />
          planned
        </span>
      </div>
    </div>
  );
}

/** Mobile: a swipeable two-week strip, with the full month one tap away. */
export function DayStrip(p: Props) {
  const [month, setMonth] = useState(false);
  const marks = dayMarks(p.items);
  const from = p.date && p.date > p.today ? (addDays(p.date, -2) < p.today ? p.today : addDays(p.date, -2)) : p.today;
  const days = Array.from({ length: 14 }, (_, i) => addDays(from, i));
  return (
    <div className={styles.strip} data-testid="event-day-strip">
      <div className={styles.stripHead}>
        <span className={styles.stripMonth}>{new Date(`${from}T12:00:00`).toLocaleDateString("en-GB", { month: "long" })}</span>
        <span className="grow" />
        <button type="button" className={styles.linkBtn} aria-expanded={month} onClick={() => setMonth(!month)}>
          {month ? "Hide month" : "Month view"}
        </button>
      </div>
      <div className={styles.stripDays}>
        {days.map((d) => {
          const mk = marks.get(d);
          return (
            <button key={d} type="button" aria-pressed={d === p.date} className={cx(styles.stripDay, d === p.date && styles.stripOn)} onClick={() => p.onDate(d === p.date ? "" : d)}>
              {new Date(`${d}T12:00:00`).toLocaleDateString("en-GB", { weekday: "short" }).slice(0, 2)}
              <b>{Number(d.slice(8))}</b>
              <span className={styles.stripDots}>{mk && <i className={cx(mk.priority && styles.dotPrio)} />}</span>
            </button>
          );
        })}
      </div>
      {month && <Calendar {...p} />}
    </div>
  );
}
