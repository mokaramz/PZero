import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { PathTrace } from "@/components/focus";
import { Badge } from "@/components/ui";
import { companyLink } from "@/features/conviction/api";
import { cx } from "@/lib/format";
import { ROLE } from "@/lib/roles";
import { firstName, initials, OMAR_ID, startupsOf, stripSuggested } from "../model/peopleUtil";
import type { Person, PipelineSlice } from "../model/types";
import { TalentedForm } from "./TalentedForm";
import styles from "../Network.module.css";

const POT_TAG: Record<string, ReactNode> = {
  maybe: <Badge>FOUNDER POT. MAYBE</Badge>,
  high: <Badge tone="green">FOUNDER POT. HIGH</Badge>,
  building: <Badge tone="green">BUILDING NOW</Badge>,
};

/** The Conviction entry a linked name refers to: the same company name, or one that contains it (case-insensitive). */
function pipeFor(pipeline: PipelineSlice | undefined, n: string) {
  const k = n.toLowerCase();
  return (pipeline?.signals ?? []).find((e) => e.company && (e.company.toLowerCase() === k || e.company.toLowerCase().includes(k)));
}

/** Centre column of the Network workspace (v1 renderPersonDetail). Every fact is user-provided. */
export function PersonProfile({ p, pipeline }: { p: Person; pipeline: PipelineSlice | undefined }) {
  const links = startupsOf(p);
  const recommended = p.recommended_names ?? [];
  const hasChain = !!p.introduced_by_name || !!recommended.length;

  return (
    <div className={styles.profile} data-testid="person-profile">
      <header className={styles.profHead}>
        <span className={cx(styles.avatar, styles.avatarLg, p.id === OMAR_ID && styles.avatarNavy)}>{initials(p.name)}</span>
        <div className="grow">
          <h2 className={styles.profName}>{p.name}</h2>
          <div className="muted small">
            {p.role || ""}
            {p.company ? ` · ${p.company}` : ""}
            {p.location ? ` · ${p.location}` : ""}
          </div>
        </div>
        <div className="row">
          {POT_TAG[p.founder_potential ?? ""]}
          {p.watch && <Badge tone="red">WATCHLIST</Badge>}
        </div>
      </header>

      <Sect title="Role & background">
        {[p.role, p.company].filter(Boolean).join(" · ") || "—"}
        {p.university && <div className="muted small">{p.university}</div>}
        {p.expertise && <div className="muted small">Expertise: {p.expertise}</div>}
        {p.founder_potential && <div className="muted small">Founder potential: {p.founder_potential}</div>}
      </Sect>

      <Sect title="Relationship context">
        {p.why_interesting || <span className="muted">Why interesting — not captured yet.</span>}
        {p.discovery && <div className="muted small">How we met: {p.discovery}</div>}
      </Sect>

      <Sect title="Linked companies / startups">
        {links.length ? (
          <div className="row">
            {links.map((n) => {
              const e = pipeFor(pipeline, n);
              return e ? (
                <Link key={n} className={styles.compChip} to={companyLink(e.slug)}>
                  {n} <span className="muted">{e.sc?.provisional ?? ""}</span>
                </Link>
              ) : (
                <Badge key={n}>{n}</Badge>
              );
            })}
          </div>
        ) : (
          <span className="muted">None linked — add in Edit / log (comma-separated).</span>
        )}
      </Sect>

      <Sect title="Introductions / referral path">
        {hasChain ? (
          <>
            {p.introduced_by_name && <PathTrace key={p.id} nodes={[ROLE.operator, p.introduced_by_name, p.name]} testId="intro-path" />}
            {p.introduced_by_name && (
              <div>
                <span className="muted">introduced by</span> <b>{p.introduced_by_name}</b> → {firstName(p.name)}
              </div>
            )}
            {!!recommended.length && (
              <div>
                <span className="muted">recommended</span>{" "}
                {recommended.map((n, i) => (
                  <span key={n + i}>
                    {i > 0 && ", "}
                    <b>{n}</b>
                  </span>
                ))}
              </div>
            )}
          </>
        ) : (
          <span className="muted">No chain logged yet.</span>
        )}
        <div className={styles.tree}>
          <b>{p.name}</b>
          {recommended.length ? (
            recommended.map((n, i) => (
              <div key={n + i} className={styles.treeNode}>
                ↳ <b>{n}</b>
              </div>
            ))
          ) : (
            <div className={cx(styles.treeNode, "muted")}>ask: "who are the three most talented people you know?"</div>
          )}
        </div>
        <TalentedForm key={p.id} person={p} variant="inline" />
      </Sect>

      <Sect title="Notes">
        <div className={styles.pre}>{p.notes || <span className="muted">No notes yet.</span>}</div>
      </Sect>

      <Sect title="Recent interactions">
        <ol className={styles.timeline}>
          {p.last_interaction ? (
            <li>
              <span className={styles.tlDate}>{p.last_interaction}</span>
              Last interaction{p.days_since_touch != null ? ` — ${p.days_since_touch}d ago` : ""}
            </li>
          ) : (
            <li>
              <span className={styles.tlDate}>—</span>
              <span className="muted">No interaction logged yet.</span>
            </li>
          )}
          <li>
            <span className={styles.tlDate}>{p.created || ""}</span>
            {p.discovery || "Added"}
          </li>
        </ol>
      </Sect>

      <Sect title="Next action">
        {p.next_action ? (
          <>
            {p.due && <Badge tone="red">DUE</Badge>} {stripSuggested(p.next_action)}
            {p.next_action.startsWith("SUGGESTED") && (
              <>
                {" "}
                <Badge>SUGGESTED</Badge>
              </>
            )}
            {p.next_action_date && <span className="muted small"> · {p.next_action_date}</span>}
          </>
        ) : (
          <span className="muted">No next action — set one in the rail.</span>
        )}
      </Sect>

      <p className="muted small">All facts user-provided · unknown fields left empty · auto-actions labelled SUGGESTED</p>
    </div>
  );
}

function Sect({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.sect}>
      <h4 className={styles.hd}>{title}</h4>
      <div className={styles.sectBody}>{children}</div>
    </section>
  );
}
