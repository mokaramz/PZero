import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Async, Badge, Callout, Panel } from "@/components/ui";
import { useCityPage } from "../api";
import { HOME_CITY } from "../model/registry";
import type { CityRegistry } from "../model/types";
import styles from "../Ecosystems.module.css";

/** One city's page (`GET ecosystems/eco?city=`): its registry coverage line, the city note with the travel time from home,
 *  then four panels — startups in pipeline, upcoming events, your people, and universities, labs & hubs. */
export function CityView({ city, reg }: { city: string; reg: CityRegistry | undefined }) {
  const q = useCityPage(city);
  const r = reg?.cities.find((x) => x.name === city);
  const cov = r?.coverage;
  return (
    <div data-testid="city-page">
      <h2 className={styles.cityTitle}>{city}</h2>
      {r && !r.curated && cov && (
        <Callout tone="blue">
          Detected city — appears in your data (startups {cov.startups} · events {cov.events} · people {cov.people}) but has no curated institutions yet.
        </Callout>
      )}
      {cov && (
        <p className="muted small" data-testid="city-coverage">
          Coverage: startups {cov.startups} · events {cov.events} · people {cov.people} · universities/labs/hubs {cov.institutions}
          {cov.last_refresh ? ` · last refresh ${cov.last_refresh}` : " · no refresh yet"}
        </p>
      )}
      <Async q={q} label={`Loading ${city}…`}>
        {(e) => (
          <>
            {e.note && (
              <Callout tone="amber" data-testid="city-note">
                {e.note}
                {e.travel_hours != null && <span className="muted"> · ~{e.travel_hours}h from {HOME_CITY}</span>}
              </Callout>
            )}
            <div className={styles.grid}>
              <Sec title={`Startups in pipeline (${e.startups.length})`}>
                {e.startups.length ? (
                  e.startups.map((s) => (
                    <Row key={s.slug} aside={<Badge tone={s.verified ? "green" : "blue"}>{s.score}</Badge>}>
                      <Link to={`/conviction?company=${encodeURIComponent(s.slug)}`}>{s.company}</Link>
                      <div className="muted small">{s.one_liner}</div>
                      <div className="muted small">
                        {s.stage}
                        {s.sent && <b className={styles.green}> · → Manager</b>}
                      </div>
                    </Row>
                  ))
                ) : (
                  <Empty>None yet — that is information too.</Empty>
                )}
              </Sec>
              <Sec title={`Upcoming events (${e.events_upcoming.length})`}>
                {e.events_upcoming.length ? (
                  e.events_upcoming.map((x) => (
                    <Row key={x.id} aside={<Badge tone={(x.score ?? 0) >= 75 ? "green" : "blue"}>{x.score ?? "—"}</Badge>}>
                      <Link to={`/events?event=${encodeURIComponent(x.id)}`}>{x.name}</Link>
                      <div className="muted small">
                        {(x.start || "").slice(0, 10)} · {x.type_label}
                      </div>
                    </Row>
                  ))
                ) : (
                  <Empty>No dated events here yet.</Empty>
                )}
              </Sec>
              <Sec title={`Your people (${e.people.length})`}>
                {e.people.length ? (
                  e.people.map((p) => (
                    <Row key={p.id}>
                      <Link to={`/network?person=${encodeURIComponent(p.id)}`}>{p.name}</Link>{" "}
                      <span className="muted small">
                        {p.role || ""}
                        {p.company ? ` · ${p.company}` : ""}
                      </span>
                      {p.next_action && <div className="muted small">{p.next_action}</div>}
                    </Row>
                  ))
                ) : (
                  <Empty>Nobody here yet — an event debrief fixes that.</Empty>
                )}
              </Sec>
              <Sec title="Universities, labs & hubs">
                {e.orgs.length ? (
                  e.orgs.map((o) => (
                    <Row key={o.name}>
                      <b>{o.name}</b> <Badge tone={o.kind === "hub" ? "amber" : "green"}>{o.kind}</Badge>
                      <div className="muted small">
                        {o.why} ·{" "}
                        <a href={o.url} target="_blank" rel="noreferrer">
                          site ↗
                        </a>
                      </div>
                    </Row>
                  ))
                ) : (
                  <Empty>—</Empty>
                )}
              </Sec>
            </div>
          </>
        )}
      </Async>
    </div>
  );
}

const Sec = ({ title, children }: { title: string; children: ReactNode }) => (
  <Panel title={title} className={styles.sec}>
    <div className={styles.secBody}>{children}</div>
  </Panel>
);

const Row = ({ children, aside }: { children: ReactNode; aside?: ReactNode }) => (
  <div className={styles.row}>
    <div className="grow">{children}</div>
    {aside}
  </div>
);

const Empty = ({ children }: { children: ReactNode }) => <div className="muted small">{children}</div>;
