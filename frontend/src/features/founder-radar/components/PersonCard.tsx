import { Link } from "react-router-dom";

import { Badge, type Tone } from "@/components/ui";
import { cx } from "@/lib/format";
import { useFr } from "../context";
import { GOLD, RESEARCH, STRONG, UNRESOLVED, frBucket, frTier, nextStep, unknownBands } from "../model/logic";
import type { Person } from "../model/types";
import { scoutReviewLink } from "../model/view";
import { AccessPill, BandPill, Ext, LinkBtn, Row } from "./bits";
import styles from "../FounderRadar.module.css";

/** A person in a radar segment (Research Queue, search): bucket, identity, evidence, bands, proof and the next step.
 *  A click anywhere opens the evidence drawer. */
export function PersonCard({ p }: { p: Person }) {
  const { data, openFounder, openPromote, actions } = useFr();
  const ns = data.network_states ?? [];
  const s = p.signal ?? {};
  const b = (s.bands ?? {}) as Record<string, string>;
  const bk = frBucket(p);
  const unres = (p.identity_status || "") === UNRESOLVED;
  const srcs = [...new Set((p.sources ?? []).map((x) => x.source))];
  const fe = s.founder_eligibility ?? {};
  const research = bk === RESEARCH;
  const tier = frTier(p, ns);
  const access = s.access?.label || "No access path recorded";
  const bucketTone: Tone = bk === GOLD ? "green" : bk === STRONG ? "amber" : "neutral";
  const ra = s.recent_activity ?? {};
  return (
    <article className={cx(styles.card, styles.clickable)} data-testid="fr-person-card" onClick={() => openFounder(p.id)}>
      <header className={styles.cardHead}>
        <span className={styles.name}>{p.name}</span>
        <Badge tone={bucketTone}>{s.queue_label || bk}</Badge>
        {unres ? <Badge tone="amber">IDENTITY UNRESOLVED — NOT YET VERIFIABLE</Badge> : <Badge tone="green">{p.identity_status || ""}</Badge>}
        {p.name_attributed === false && (
          <Badge tone="amber" title="GitHub supplied no human name; the login is kept as an alias">
            LOGIN ONLY — NAME NOT ATTRIBUTED
          </Badge>
        )}
        <span className={styles.spacer} />
        {s.ordering != null ? (
          <span className={styles.order} title={"evidence ordering (eligible founders only): " + (s.ordering_factors ?? []).map((f) => f.factor + " " + f.points).join(", ")}>
            order {s.ordering}
          </span>
        ) : (
          <Badge>Not founder-scorable</Badge>
        )}
        <Badge tone="blue">{p.radar_state || ""}</Badge>
      </header>
      {p.connection_source === "linkedin_export" && (
        <Row sub>
          Imported: {p.provenance_label || "authorized import"}
          {p.linkedin_connected_on ? " · connected " + p.linkedin_connected_on : ""}
          {p.import_date ? " · imported " + p.import_date.slice(0, 10) : ""}
        </Row>
      )}
      <Row>
        <b>Who:</b> {p.role || "role UNKNOWN"}
        {p.company ? " · " + p.company : ""}
        {(p.institutions ?? []).length ? " · " + (p.institutions ?? []).slice(0, 2).join(", ") : ""} · {p.location || "location UNKNOWN"}
        {p.country ? " " + p.country : ""}
      </Row>
      <Row>
        <b>Founder evidence:</b> {s.founder_status_class || "unknown"}
        {(fe.evidence ?? []).length ? " — " + fe.evidence![0] : " — none attributed"}
      </Row>
      <Row>
        <b>Why now:</b> {p.why_surfaced || p.why_interesting || "—"}
      </Row>
      {s.access?.company_route && (
        <Row sub>
          Access via confirmed company route (cold, never warm): {s.access.label} · <Ext href={s.access.provenance || "#"}>provenance ↗</Ext>
        </Row>
      )}
      <Row sub>
        Last observed (scan/merge): {p.last_observed || p.updated || "—"} · Last meaningful activity:{" "}
        {ra.date ? `${ra.date} (${ra.source || ""})${ra.recent ? "" : " — older than 90 days"}` : "none dated"}
        {s.recent_activity_used ? " · gate used " + s.recent_activity_used : ""}
      </Row>
      <div className={styles.pills}>
        {research ? <BandPill label="Technical theme overlap" value={b.technical_theme_overlap} /> : <BandPill label="Project A relevance" value={b.project_a} />}
        <BandPill label="Builder" value={b.builder} />
        <BandPill label="Technical" value={b.technical_depth} />
        <BandPill label="Entrepreneurial" value={b.entrepreneurial} />
        <BandPill label="Trajectory" value={b.trajectory} />
      </div>
      <Row>
        <b>Proof:</b> {(p.evidence ?? []).length} attributed item(s) from {srcs.join(", ") || "no source"} · <b>Unknown:</b>{" "}
        {(s.missing ?? []).join(", ") || unknownBands(b, true) || "nothing"} · <AccessPill kind={s.access?.kind}>{access}</AccessPill>
      </Row>
      <Row>
        <b>Next:</b> {nextStep(p)}
      </Row>
      <footer className={styles.links}>
        <LinkBtn onClick={() => openFounder(p.id)}>View evidence</LinkBtn>
        {research ? (
          <LinkBtn onClick={() => actions.investigate(p.id)}>Investigate founder status</LinkBtn>
        ) : tier === "radar" ? (
          <LinkBtn onClick={() => actions.watch(p.id)}>Add to Watchlist</LinkBtn>
        ) : null}
        {!research &&
          tier !== "network" &&
          (p.promotion_block ? (
            <span className={styles.blocked} title={p.promotion_block}>
              Add to Network — {p.promotion_block}
            </span>
          ) : (
            <LinkBtn onClick={() => openPromote(p.id)}>Add to Network</LinkBtn>
          ))}
        {p.scout_identity_review?.ready && unres && (
          <Link className={styles.linkBtn} to={scoutReviewLink(p.scout_identity_review.intake_item_id || "")} onClick={(e) => e.stopPropagation()}>
            Review identity evidence (Scout Packet)
          </Link>
        )}
        {p.proposed_identity && <LinkBtn onClick={() => actions.confirmIdentity(p.id)}>Confirm proposed identity: {p.proposed_identity.name}</LinkBtn>}
        <LinkBtn onClick={() => actions.dismiss(p.id)}>Dismiss</LinkBtn>
      </footer>
    </article>
  );
}
