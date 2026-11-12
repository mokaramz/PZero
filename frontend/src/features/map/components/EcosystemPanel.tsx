import { useState } from "react";

import { Async, Badge, Button, type Tone } from "@/components/ui";
import { useEcosystem } from "../api";
import { GEO_COLOR } from "../model/colors";
import { SNAPSHOT_NOTE } from "../model/deferred";
import type { GeoDetail } from "../model/types";
import { GeoLink } from "./GeoLink";
import { SourcingDayPlanner } from "./SourcingDayPlanner";
import styles from "../Map.module.css";

const COV_TONE: Record<string, Tone> = {
  STRONG: "green",
  PARTIAL: "amber",
  WEAK: "red",
  "NOT COVERED": "red",
};

function WhyHere({ d, onPlan }: { d: GeoDetail; onPlan: () => void }) {
  return (
    <>
      <div className="row">
        <span className={styles.stateChip} style={{ background: GEO_COLOR[d.state] }}>
          {d.state}
        </span>
        <span className="muted small">{d.travel.text}</span>
      </div>
      <div className={styles.geoHd}>Why this area matters</div>
      <ul className={styles.geoList} data-testid="geo-why">
        {d.why_here.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      {d.convergence.converging && (
        <div className={styles.k}>
          <b>Signal convergence:</b> {d.convergence.signals} independent signals across {d.convergence.family_labels.length} families —{" "}
          {d.convergence.family_labels.join(", ").toLowerCase()}.
        </div>
      )}
      <div className={styles.nba} data-testid="geo-nba">
        <b>Next best action:</b> {d.next_best_action}
      </div>
      <Button size="sm" variant="primary" onClick={onPlan} data-testid="build-day">
        Build a sourcing day
      </Button>

      {d.companies.length > 0 && (
        <>
          <div className={styles.geoHd}>Companies worth knowing</div>
          {d.companies.slice(0, 8).map((c) => (
            <div key={c.name + c.kind} className={styles.geoItem}>
              <GeoLink link={c.link}>
                <b>{c.name}</b>
              </GeoLink>{" "}
              {c.early && <Badge tone="green">early</Badge>} {c.late && <Badge>already funded / late</Badge>} {c.watch && <Badge tone="amber">WATCH</Badge>}{" "}
              {c.scout && <Badge tone="purple">Scout 00 · cycle {c.scout}</Badge>}
              <div className="muted small">
                {c.pz_state} · first seen {c.first_seen} · {c.stage}
                {c.score && ` · ${c.score}`}
              </div>
              {c.machine && <div className="muted small">{c.machine}</div>}
              {c.why && <div className="small">{c.why}</div>}
              {c.news.length > 0 && <div className="small">News: {c.news[0]}</div>}
            </div>
          ))}
        </>
      )}
      {d.people.length > 0 && (
        <>
          <div className={styles.geoHd}>People worth knowing</div>
          {d.people.map((p) => (
            <div key={p.label} className={styles.geoItem}>
              <GeoLink link={p.link}>
                <b>{p.label}</b>
              </GeoLink>{" "}
              <span className="muted small">
                {[p.role, p.org].filter(Boolean).join(" · ")} · relationship: {p.relationship}
              </span>
              {p.why && <div className="small">{p.why}</div>}
            </div>
          ))}
        </>
      )}
      {d.events.length > 0 && (
        <>
          <div className={styles.geoHd}>Upcoming opportunities</div>
          {d.events.slice(0, 6).map((e) => (
            <div key={e.label + e.date} className={styles.geoItem}>
              <GeoLink link={e.link}>
                <b>{e.label}</b>
              </GeoLink>
              <div className="muted small">
                {e.date}
                {e.time && ` ${e.time}`} · {e.band.toLowerCase() || "unrated"} · {e.price} · registration: {e.registration} (yours to do)
              </div>
              {e.why && <div className="small">{e.why}</div>}
            </div>
          ))}
        </>
      )}
      <div className={styles.geoHd}>Coverage — can Project Zero see this area?</div>
      {d.coverage.assessed ? (
        <div className={styles.covGrid} data-testid="geo-coverage">
          {Object.entries(d.coverage.families).map(([f, v]) => (
            <span key={f} className={styles.covRow}>
              <span>{f}</span> <Badge tone={COV_TONE[v] ?? "neutral"}>{v}</Badge>
            </span>
          ))}
        </div>
      ) : (
        <div className="muted small">Coverage not assessed for this place — treat “no signals” as “we do not know”.</div>
      )}
      {d.source_candidates.length > 0 && (
        <div className={styles.k}>
          <b>Source candidates:</b> {d.source_candidates.map((s) => `${s.name} — ${s.state.toLowerCase()}`).join("; ")} (System health → New sources)
        </div>
      )}
      {d.news.length > 0 && (
        <>
          <div className={styles.geoHd}>What changed (News)</div>
          {d.news.slice(0, 4).map((n) => (
            <div key={n.headline} className="small">
              {n.date} · {n.headline} <span className="muted">({n.source})</span>
            </div>
          ))}
        </>
      )}
      {d.institutions.length > 0 && <div className="muted small">Institutions: {d.institutions.map((o) => o.name).join(" · ")}</div>}
      <p className="muted small">{d.note}</p>
      <p className="muted small" data-testid="geo-snapshot-note">
        {SNAPSHOT_NOTE}
      </p>
    </>
  );
}

/** WHY HERE? — one ecosystem: reasons, companies, people, events, coverage, sources, next best action. */
export function EcosystemPanel({ city, onClose }: { city: string; onClose: () => void }) {
  const q = useEcosystem(city);
  const [plan, setPlan] = useState(false);
  return (
    <aside className={styles.panel} aria-label="Ecosystem" data-testid="geo-panel">
      <div className={styles.panelHead}>
        <b>{city}</b>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close detail">
          close ×
        </Button>
      </div>
      <div className={styles.panelBody}>
        <Async q={q} label="Reading the area…">
          {(d) => (plan ? <SourcingDayPlanner city={d.city} onBack={() => setPlan(false)} /> : <WhyHere d={d} onPlan={() => setPlan(true)} />)}
        </Async>
      </div>
    </aside>
  );
}
