import { Badge } from "@/components/ui";
import { useFr } from "../context";
import type { Company } from "../model/types";
import { domainTag, linkedinCompanySearch, priorityFactorsLine, webSearchLink } from "../model/view";
import { Ext, LinkBtn, Row, Unk } from "./bits";
import styles from "../FounderRadar.module.css";

/** A company lead in the qualification queue (Research Queue → claim segment): claimed founders, sourced facts,
 *  unverified claims, access, company evidence, research priority and the next step. */
export function CompanyCard({ c }: { c: Company }) {
  const { openFounder, openReview, actions } = useFr();
  const ra = c.verified_facts?.recent_activity;
  const tag = domainTag(c);
  /** bounded official-domain research; the review opens when proposals are ready */
  const research = async () => {
    if (await actions.researchCompany(c.key)) openReview(c.key);
  };
  return (
    <article className={styles.card} data-testid="fr-company-card">
      <header className={styles.cardHead}>
        <span className={styles.name}>{c.name}</span>
        <Badge tone="blue">company lead</Badge>
        {tag && (
          <Badge tone="amber" title={c.domain_source}>
            {tag}
          </Badge>
        )}
        <Badge>{c.founders.length} claimed founder(s)</Badge>
        {c.in_pipeline && <Badge>in pipeline</Badge>}
        <span className={styles.spacer} />
        <span className={styles.meta}>{c.domain}</span>
      </header>
      <Row>
        <b>What:</b> <Unk v={c.description} />
      </Row>
      <Row>
        <b>Founders (claimed):</b>{" "}
        {c.founders.map((f, i) => (
          <span key={f.id + i}>
            {i > 0 && " · "}
            <LinkBtn onClick={() => openFounder(f.id)}>{f.name}</LinkBtn>{" "}
            <span className={styles.subInline}>
              ({f.role || "role UNKNOWN"} · {f.identity_status}
              {f.name_attributed === false ? " · login only" : ""})
            </span>
          </span>
        ))}
      </Row>
      <Row>
        <b>Founded:</b> <Unk v={c.founded} /> · <b>Status:</b> <Unk v={c.status} /> · <b>Stage/funding:</b> <Unk v={c.stage} /> / <Unk v={c.funding} /> ·{" "}
        <b>Recent activity (sourced, dated):</b>{" "}
        {ra ? `${ra.activity_date || "undated"} — ${String(ra.value).slice(0, 60)}` : <span className={styles.unk}>none</span>}{" "}
        <span className={styles.subInline}>({c.verified_field_count || 0} sourced fact(s) — only these count for Gold/Strong)</span>
      </Row>
      {Object.keys(c.claims ?? {}).length > 0 && (
        <Row tone="amber">
          <b>Unverified claims (never decision-bearing):</b>{" "}
          {Object.entries(c.claims ?? {})
            .map(([k, v]) => `${k}: ${v}`)
            .join(" · ")}
        </Row>
      )}
      <Row>
        <b>Project A fit:</b> {c.project_a_fit} · <b>Early-stage mandate fit:</b> {c.early_stage_fit} · <b>Access:</b> {c.access}
        {(c.access_routes ?? []).length > 0 && (
          <>
            {" — confirmed company routes (cold): "}
            {(c.access_routes ?? []).map((r, i) => (
              <span key={i}>
                {i > 0 && ", "}
                {r.value} <Ext href={r.url}>↗</Ext>
              </span>
            ))}
          </>
        )}
      </Row>
      <Row>
        <b>Company evidence ({c.evidence.length}, never person-level):</b>{" "}
        {c.evidence.length
          ? c.evidence.slice(0, 3).map((e, i) => (
              <span key={i}>
                {i > 0 && "; "}
                {e.claim.slice(0, 90)}{" "}
                <span className={styles.subInline}>
                  — {e.source}
                  {e.source_url && (
                    <>
                      {" "}
                      <Ext href={e.source_url}>↗</Ext>
                    </>
                  )}
                </span>
              </span>
            ))
          : "none"}
      </Row>
      <Row>
        <b>Priority: {c.priority_label || "Low"}</b> · <b>Why:</b> {c.priority_why || ""}
        {c.proposals_pending ? (
          <>
            {" · "}
            <b>{c.proposals_pending} proposal(s) to review</b>
          </>
        ) : null}
      </Row>
      <Row>
        <b>Next:</b> {c.next_action}
        {(c.next_missing ?? []).length ? " · missing: " + (c.next_missing ?? []).join(", ") : ""}
      </Row>
      <details className={styles.details}>
        <summary>priority factors (ordering only, never a score)</summary>
        {priorityFactorsLine(c)}
      </details>
      <footer className={styles.links}>
        <LinkBtn onClick={research}>Research company</LinkBtn>
        <LinkBtn onClick={() => openReview(c.key)}>Review proposals{c.proposals_pending ? ` (${c.proposals_pending})` : ""}</LinkBtn>
        <LinkBtn onClick={() => actions.companyEvidence(c.key)}>Add public evidence</LinkBtn>
        <LinkBtn onClick={() => actions.companyFact(c.key)}>Add sourced company fact</LinkBtn>
        <Ext href={webSearchLink(c.name)}>Web search ↗</Ext>
        <Ext href={linkedinCompanySearch(c.name)}>LinkedIn search ↗ (not evidence)</Ext>
      </footer>
    </article>
  );
}
