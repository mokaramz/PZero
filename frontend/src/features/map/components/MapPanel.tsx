import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Badge, Button } from "@/components/ui";
import { companyLink } from "@/features/conviction/api";
import { personLink } from "@/features/network/api";
import type { MapData, MapEvent, MapOrg, MapPerson, MapStartup, Selection } from "../model/types";
import { eventsNearby, linkedCompanies, linkedPeople, peopleAtEvent } from "../model/view";
import styles from "../Map.module.css";

type Props = {
  d: MapData;
  sel: Selection;
  pipelineNext: (slug: string) => string | undefined;
  onSelect: (s: Selection) => void;
  onClose: () => void;
};

function K({ label, children, tone }: { label?: string; children: ReactNode; tone?: "red" | "green" }) {
  return (
    <div className={tone ? styles[`k_${tone}`] : styles.k}>
      {label && <b>{label}: </b>}
      {children}
    </div>
  );
}

function Lnk({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" className={styles.linkBtn} onClick={onClick}>
      {children}
    </button>
  );
}

/** "A, B, C" as in-panel jumps. */
function Jumps<T>({ items, keyOf, name, sel, onSelect }: { items: T[]; keyOf: (x: T) => string; name: (x: T) => string; sel: (x: T) => Selection; onSelect: (s: Selection) => void }) {
  return items.map((x, i) => (
    <span key={keyOf(x)}>
      {i > 0 && ", "}
      <Lnk onClick={() => onSelect(sel(x))}>{name(x)}</Lnk>
    </span>
  ));
}

function StartupBody({ d, s, next, onSelect }: { d: MapData; s: MapStartup; next?: string; onSelect: (s: Selection) => void }) {
  const linked = linkedPeople(d, s);
  const near = eventsNearby(d, s);
  return (
    <>
      <div className="row">
        <Badge tone="blue">COMPANY</Badge>
        {s.conflict === "potential_conflict" && <Badge tone="red">CONFLICT-GATED</Badge>}
        {s.sent_to_omar && <Badge>→ OMAR</Badge>}
      </div>
      <h3 className={styles.pName}>{s.company}</h3>
      <div className="muted small">
        {s.location} · {s.archetype}
      </div>
      <div className={styles.scoreLine}>
        <Badge tone={s.verified ? "green" : "blue"}>{s.score}</Badge> <span className="muted small">{s.verified ? "verified" : "provisional"}</span>
      </div>
      <K label="Stage">
        {s.stage_label}
        {s.funding ? ` — ${s.funding}` : ""}
      </K>
      <K label="Timing">{s.timing}</K>
      {s.founders && <K label="Founders">{s.founders}</K>}
      <K label="Why interesting">{s.why || s.one_liner}</K>
      {s.conflict === "potential_conflict" && (
        <K tone="red">
          <b>Potential portfolio conflict — Manager first.</b>
        </K>
      )}
      {s.sent_to_omar && (
        <K tone="green" label="Sent to Manager">
          {s.sent_to_omar}
        </K>
      )}
      {linked.length > 0 && (
        <K label="Linked people">
          <Jumps items={linked} keyOf={(p) => p.id} name={(p) => p.name} sel={(p) => ({ kind: "person", id: p.id })} onSelect={onSelect} />
        </K>
      )}
      {near.length > 0 && (
        <K label="Events nearby">
          <Jumps items={near} keyOf={(e) => e.id} name={(e) => e.name} sel={(e) => ({ kind: "event", id: e.id })} onSelect={onSelect} />
        </K>
      )}
      <K label="Next action">{next || <span className="muted">none set — open the Conviction workspace</span>}</K>
      <div className={styles.acts}>
        <Link className={styles.primaryLink} to={companyLink(s.slug)}>
          Open workspace
        </Link>
      </div>
    </>
  );
}

function EventBody({ d, e, onSelect }: { d: MapData; e: MapEvent; onSelect: (s: Selection) => void }) {
  const ppl = peopleAtEvent(d, e);
  const q = encodeURIComponent(e.id);
  return (
    <>
      <div className="row">
        <Badge>EVENT</Badge>
        <Badge tone="amber">{e.type_label || ""}</Badge>
      </div>
      <h3 className={styles.pName}>{e.name}</h3>
      <div className="muted small">
        {e.city} · {(e.start || "").slice(0, 10)}
      </div>
      <div className={styles.scoreLine}>
        <Badge tone={e.score >= 75 ? "green" : "blue"}>{e.score}</Badge> <span className="muted small">{e.band}</span>
      </div>
      {e.organizer && <K label="Organizer">{e.organizer}</K>}
      {e.audience && <K label="Expected audience">{e.audience}</K>}
      <K label="Why attend">{e.why}</K>
      {e.deadline && (
        <K tone="red" label="Register by">
          {e.deadline}
        </K>
      )}
      {e.url && (
        <K>
          <a href={e.url} target="_blank" rel="noreferrer">
            Registration / details ↗
          </a>
        </K>
      )}
      {ppl.length > 0 && (
        <K label="People to meet there">
          <Jumps items={ppl} keyOf={(p) => p.id} name={(p) => p.name} sel={(p) => ({ kind: "person", id: p.id })} onSelect={onSelect} />
        </K>
      )}
      <K label="Next action">{e.deadline ? `register by ${e.deadline}` : "decide GO / MAYBE / SKIP in Events"}</K>
      <div className={styles.acts}>
        <Link className={styles.primaryLink} to={`/events?event=${q}`}>
          Open workspace
        </Link>
        <Link className={styles.btnLink} to={`/events?event=${q}&edit=1`}>
          Edit score
        </Link>
        <Link className={styles.btnLink} to={`/events?event=${q}&debrief=1`}>
          Debrief
        </Link>
      </div>
    </>
  );
}

function PersonBody({ d, p, onSelect }: { d: MapData; p: MapPerson; onSelect: (s: Selection) => void }) {
  const lk = linkedCompanies(d, p);
  return (
    <>
      <div className="row">
        <Badge>PERSON</Badge>
        {p.watch && <Badge tone="red">WATCHLIST</Badge>}
      </div>
      <h3 className={styles.pName}>{p.name}</h3>
      <div className="muted small">
        {p.role || ""}
        {p.company ? ` · ${p.company}` : ""}
        {p.city ? ` · ${p.city}` : ""}
      </div>
      {p.watch && (
        <K tone="red">
          <b>On watchlist</b>
        </K>
      )}
      <K label="Why interesting">{p.why || ""}</K>
      <K label="Relationship">
        {p.strength || ""} · <b>Founder potential:</b> {p.potential}
      </K>
      {p.next_action && <K label="Next">{p.next_action}</K>}
      {lk.length > 0 && (
        <K label="Linked companies">
          <Jumps items={lk} keyOf={(s) => s.slug} name={(s) => s.company} sel={(s) => ({ kind: "startup", id: s.slug })} onSelect={onSelect} />
        </K>
      )}
      <div className={styles.acts}>
        <Link className={styles.primaryLink} to={personLink(p.id)}>
          Open profile
        </Link>
        <Link className={styles.btnLink} to={`${personLink(p.id)}&edit=1`}>
          Edit / log
        </Link>
      </div>
    </>
  );
}

function OrgBody({ o }: { o: MapOrg }) {
  return (
    <>
      <div className="row">
        <Badge>{String(o.kind || "ORG").toUpperCase()}</Badge>
      </div>
      <h3 className={styles.pName}>{o.name}</h3>
      <div className="muted small">
        {o.city} · {o.kind}
      </div>
      <K>{o.why}</K>
      <K>
        <a href={o.url} target="_blank" rel="noreferrer">
          Website ↗
        </a>
      </K>
      <div className={styles.acts}>
        <Link className={styles.primaryLink} to={`/ecosystems?city=${encodeURIComponent(o.city)}`}>
          Open {o.city} ecosystem
        </Link>
      </div>
    </>
  );
}

function body(d: MapData, sel: Selection, pipelineNext: Props["pipelineNext"], onSelect: Props["onSelect"]): ReactNode {
  if (sel.kind === "startup") {
    const s = d.startups.find((x) => x.slug === sel.id);
    return s ? <StartupBody d={d} s={s} next={pipelineNext(s.slug)} onSelect={onSelect} /> : null;
  }
  if (sel.kind === "event") {
    const e = d.events.find((x) => x.id === sel.id);
    return e ? <EventBody d={d} e={e} onSelect={onSelect} /> : null;
  }
  if (sel.kind === "person") {
    const p = d.people.find((x) => x.id === sel.id);
    return p ? <PersonBody d={d} p={p} onSelect={onSelect} /> : null;
  }
  const o = d.orgs.find((x) => x.name === sel.id);
  return o ? <OrgBody o={o} /> : null;
}

/** Right "intelligence panel" (v1 showMapStartup / showMapEvent / showMapPerson / showMapOrg) with jump-to-profile links. */
export function MapPanel({ d, sel, pipelineNext, onSelect, onClose }: Props) {
  return (
    <aside className={styles.panel} aria-label="Detail" data-testid="map-panel">
      <div className={styles.panelHead}>
        <b>Detail</b>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close detail">
          close ×
        </Button>
      </div>
      <div className={styles.panelBody}>{body(d, sel, pipelineNext, onSelect) ?? <span className="muted">Not on the map any more.</span>}</div>
    </aside>
  );
}
