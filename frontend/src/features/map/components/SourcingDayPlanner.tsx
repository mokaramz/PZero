import { useState } from "react";

import { Button } from "@/components/ui";
import { useSourcingDay } from "../api";
import { berlinDayPlus } from "../model/dates";
import type { SourcingDay } from "../model/types";
import { GeoLink } from "./GeoLink";
import styles from "../Map.module.css";

function Plan({ p }: { p: SourcingDay }) {
  return (
    <div className={styles.plan} data-testid="sourcing-plan">
      <h3 className={styles.pName}>
        {p.city} — {p.weekday} {p.date}
      </h3>
      <div className="muted small">{p.travel.text}</div>
      <div className={styles.k}>
        <b>Mission objective:</b> {p.objective}
      </div>
      {p.before_you_go.length > 0 && (
        <>
          <div className={styles.geoHd}>Before you go — research</div>
          <ul className={styles.geoList}>
            {p.before_you_go.map((b) => (
              <li key={b.name}>
                <GeoLink link={b.link}>{b.name}</GeoLink> <span className="muted small">{b.why}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {p.people.length > 0 && (
        <>
          <div className={styles.geoHd}>People worth contacting (you decide, no automatic outreach)</div>
          <ul className={styles.geoList}>
            {p.people.map((x) => (
              <li key={x.name + x.org}>
                <b>{x.name}</b>{" "}
                <span className="muted small">
                  {[x.role, x.org].filter(Boolean).join(" · ")} · {x.relationship}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      <div className={styles.geoHd}>Stops / opportunities</div>
      {p.stops.length ? (
        <ul className={styles.geoList}>
          {p.stops.map((s) => (
            <li key={s.what}>
              <b>{s.time}</b> — {s.what} <span className="muted small">{s.why}</span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="muted small">Nothing concrete on this date — try a day with an event, or another city.</div>
      )}
      {p.events_other_days.length > 0 && (
        <div className="muted small">Other days nearby: {p.events_other_days.map((e) => `${e.label} (${e.date})`).join(" · ")}</div>
      )}
      <div className={styles.geoHd}>What to bring back into Project Zero</div>
      <ul className={styles.geoList}>
        {p.bring_back.map((b) => (
          <li key={b}>{b}</li>
        ))}
      </ul>
      {p.coverage_caveat.length > 0 && <div className="muted small">Blind spots here: {p.coverage_caveat.join(", ").toLowerCase()}.</div>}
      <p className="muted small">{p.note}</p>
    </div>
  );
}

/** The sourcing-day planner: one POST per "Build plan", a plan that is never stored. The default date is the Berlin
 *  day + 7 (decision g). */
export function SourcingDayPlanner({ city, onBack }: { city: string; onBack: () => void }) {
  const [day, setDay] = useState(() => berlinDayPlus(new Date(), 7));
  const build = useSourcingDay();
  return (
    <div data-testid="sourcing-day">
      <div className="row">
        <Button size="sm" variant="ghost" onClick={onBack}>
          ← back
        </Button>
        <input type="date" aria-label="Sourcing day date" value={day} onChange={(e) => setDay(e.target.value)} />
        <Button size="sm" variant="primary" busy={build.isPending} onClick={() => build.mutate({ city, date: day })}>
          Build plan
        </Button>
      </div>
      {build.data && <Plan p={build.data} />}
    </div>
  );
}
