import { Badge } from "@/components/ui";
import { useFr } from "../context";
import { UNRESOLVED } from "../model/logic";
import type { Lead } from "../model/types";
import { leadAccessText } from "../model/view";
import { AccessPill, Ext, LinkBtn, Row } from "./bits";
import styles from "../FounderRadar.module.css";

/** A Top Founder Leads / Near Matches card: why this founder stands out, the sourced proof, momentum, contact, the
 *  unknowns and the next action. */
export function LeadCard({ l }: { l: Lead }) {
  const { openFounder, openReview, logCall, actions } = useFr();
  const tag = l.human_gold ? (
    <Badge tone="green">Human-confirmed Gold</Badge>
  ) : l.machine_qualified ? (
    <Badge tone="amber">Machine-qualified candidate</Badge>
  ) : (
    <Badge>near match</Badge>
  );
  return (
    <article className={styles.card} data-testid="fr-lead-card">
      <header className={styles.cardHead}>
        <span className={styles.name}>{l.name}</span>
        {tag}
        <Badge tone="blue">{l.identity_status || ""}</Badge>
        <span className={styles.spacer} />
        <span className={styles.meta}>
          {l.company} · {l.role} · {l.location}
        </span>
      </header>
      <Row>
        <b>Why this founder stands out:</b> {l.standout}
      </Row>
      <Row>
        <b>Founder-specific evidence:</b>{" "}
        {l.proof.length ? (
          <ul className={styles.proof}>
            {l.proof.map((pp, i) => (
              <li key={i}>
                {pp.fact}{" "}
                <span className={styles.subInline}>
                  — <Ext href={pp.url}>{pp.source || "source"} ↗</Ext>
                  {pp.status === "confirmed" ? " · confirmed" : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <span className={styles.subInline}>no sourced proof yet</span>
        )}
      </Row>
      <Row>
        <b>Company momentum:</b> {l.why_now} · <b>Project A relevance:</b> {l.project_a}
      </Row>
      <Row>
        <b>LinkedIn:</b>{" "}
        {l.linkedin ? (
          <>
            <Ext href={l.linkedin}>{l.linkedin} ↗</Ext> <span className={styles.subInline}>(found on a public source — never scraped)</span>
          </>
        ) : (
          <Ext href={l.linkedin_search} className={styles.extBtn}>
            Search on LinkedIn ↗
          </Ext>
        )}{" "}
        · <b>Public contact:</b> {l.contacts.length ? l.contacts.join(", ") : <span className={styles.unk}>none found</span>} · <b>Access:</b>{" "}
        <AccessPill kind={l.access}>{leadAccessText(l)}</AccessPill>
      </Row>
      <Row>
        <b>Important unknowns:</b> {l.unknowns.length ? l.unknowns.join(", ") : "none"} · <b>Next action:</b> {l.next_action}
      </Row>
      <footer className={styles.links}>
        <LinkBtn onClick={() => openFounder(l.id)}>View evidence</LinkBtn>
        <LinkBtn onClick={() => logCall({ person_id: l.id, name: l.name, company: l.company || "", radar_key: l.company_key || "" })}>Log founder call</LinkBtn>
        {l.company_key && <LinkBtn onClick={() => openReview(l.company_key!)}>Review company facts</LinkBtn>}
        {l.identity_status !== UNRESOLVED && <LinkBtn onClick={() => actions.watch(l.id)}>Add to Watchlist</LinkBtn>}
      </footer>
    </article>
  );
}
