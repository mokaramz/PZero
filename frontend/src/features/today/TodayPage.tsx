/**
 * TODAY (v1 view `today`, review 030a) — the Smooth Operator's DAILY OPERATING BRIEF. Reading order: the day (date ·
 * Today · its own small flow graphic) → the briefing → four orientation tiles → Missions (the primary workspace: one
 * container, structured rows, the first mission featured) → Manager decisions and Events side by side → machine work
 * folded. Same deterministic actions and order as the server sends — nothing here sends, registers or scores anything:
 * every button is a link (./api). Two reads: `today` and Conviction's pipeline (the company facts and the tiles).
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import { Icon } from "@/components/Icon";
import { Async } from "@/components/ui";
import { usePipeline, useToday } from "./api";
import { DayFlow } from "./components/DayFlow";
import { Machine } from "./components/Machine";
import { EventRow, ManagerRow, MissionRow } from "./components/Rows";
import { Tile } from "./components/Tile";
import type { Company } from "./missions";
import type { Only, TodayView } from "./model/types";
import { board, heroDate } from "./model/view";
import styles from "./Today.module.css";

export default function TodayPage() {
  const q = useToday();
  const pipe = usePipeline();
  return (
    <Async q={q} label="Working out today…">
      {(d) => <Today d={d} pipeline={pipe.data?.signals} />}
    </Async>
  );
}

/** The page once the day has loaded; `pipeline` is Conviction's read (the tiles wait for it, the rows join it). */
function Today({ d, pipeline }: { d: TodayView; pipeline: Company[] | undefined }) {
  const [only, setOnly] = useState<Only>("all");
  const { signals, missions, events, manager, shown, nCompany, top, brief } = board(d, pipeline, only);
  return (
    <>
      {/* 1 · the day: date, title, purpose — and Today's own small graphic */}
      <header className={styles.hero}>
        <div className={styles.heroText}>
          <div className={styles.heroDate} data-testid="today-date">
            {heroDate(new Date())}
          </div>
          <h1 className={styles.heroTitle}>Today</h1>
          <p className={styles.heroSub}>Your daily brief for sourcing, investigation and decisions.</p>
        </div>
        <DayFlow missions={missions.length} decisions={manager.length + events.length} handled={d.triage?.total} />
      </header>

      {/* 2 · the briefing: one line, one supporting line */}
      <section className={styles.brief} aria-label="Today's briefing" data-testid="today-brief">
        <span className={styles.briefLabel}>Today's briefing</span>
        <div className={styles.briefMain}>
          <p className={styles.briefLine}>{brief}</p>
          {top && (
            <p className={styles.briefSignal}>
              {top.name} — {top.whyNow}
            </p>
          )}
        </div>
      </section>

      {/* 3 · orientation: four compact tiles */}
      {pipeline && (
        <ul className={styles.tiles} aria-label="Orientation">
          <Tile icon="layers" tone="conviction" n={signals.length} label="in Conviction" to="/conviction" />
          <Tile icon="shield" tone="verified" n={signals.filter((e) => e.sc.fully_verified).length} label="fully verified" to="/conviction" />
          <Tile icon="target" tone="missions" n={missions.length} label={missions.length === 1 ? "mission" : "missions"} to="#today-missions" />
          <Tile
            icon="approval"
            tone="manager"
            n={manager.length}
            label={manager.length === 1 ? "Manager decision" : "Manager decisions"}
            to="/conviction?seg=gated"
          />
        </ul>
      )}

      {/* 4 · Missions — the primary workspace: one container, structured rows */}
      <section className={styles.workspace} aria-label="Missions" id="today-missions">
        <header className={styles.workHead}>
          <h2 className={styles.workTitle}>Missions</h2>
          <span className={styles.workCount}>{missions.length}</span>
          <span className="grow" />
          {nCompany > 0 && nCompany < missions.length && (
            <div className={styles.segmented} role="group" aria-label="Mission filter">
              {(
                [
                  ["all", "All", missions.length],
                  ["company", "Companies", nCompany],
                  ["signal", "Signals", missions.length - nCompany],
                ] as const
              ).map(([v, l, n]) => (
                <button key={v} type="button" className={styles.seg} aria-pressed={only === v} onClick={() => setOnly(v)}>
                  {l} <span className={styles.segN}>{n}</span>
                </button>
              ))}
            </div>
          )}
        </header>
        <div className={styles.workCard}>
          {!d.actions.length ? (
            <div className={styles.empty} data-testid="today-empty">
              Nothing needs you today.
            </div>
          ) : !shown.length ? (
            <p className={styles.quiet}>No mission of this kind today.</p>
          ) : (
            <ol className={styles.missions} data-testid="today-list">
              {shown.map((m, i) => (
                <MissionRow key={`${m.a.type}-${i}`} m={m} featured={i === 0 && only === "all"} />
              ))}
            </ol>
          )}
        </div>
      </section>

      {/* 5 · secondary: blocked on the Manager · dated decisions — two sibling panels */}
      {(events.length > 0 || manager.length > 0) && (
        <div className={styles.context} data-testid="today-context">
          {manager.length > 0 && (
            <section className={styles.panel} data-tone="manager" aria-label="Manager decisions">
              <header className={styles.panelHead}>
                <Icon name="people" size={17} className={styles.panelIcon} />
                <h2 className={styles.panelTitle}>Manager decisions</h2>
                <span className={styles.panelCount}>{manager.length} blocked until the Manager answers</span>
                <span className="grow" />
                <Link className={styles.viewAll} to="/conviction?seg=gated">
                  View all <Icon name="arrow" size={13} />
                </Link>
              </header>
              <ol className={styles.panelList}>
                {manager.map((m, i) => (
                  <ManagerRow key={`mg-${i}`} m={m} />
                ))}
              </ol>
            </section>
          )}
          <section className={styles.panel} data-tone="events" aria-label="Events">
            <header className={styles.panelHead}>
              <Icon name="calendar" size={16} className={styles.panelIcon} />
              <h2 className={styles.panelTitle}>Events</h2>
              <span className={styles.panelCount}>{events.length} decide before the date</span>
              <span className="grow" />
              <Link className={styles.viewAll} to="/events">
                View all <Icon name="arrow" size={13} />
              </Link>
            </header>
            {events.length ? (
              <ol className={styles.panelList}>
                {events.map((m, i) => (
                  <EventRow key={`ev-${i}`} m={m} />
                ))}
              </ol>
            ) : (
              <p className={styles.quiet}>No event needs a decision today.</p>
            )}
          </section>
        </div>
      )}

      {/* 6 · machine work: last, one line, folded */}
      <section className={styles.machineZone} aria-label="Machine work" data-zone="background">
        <Machine d={d} />
      </section>
    </>
  );
}
