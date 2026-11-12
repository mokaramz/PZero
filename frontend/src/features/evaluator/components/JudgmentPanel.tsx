/** The right column: judgment inputs per dimension, evidence gaps, contradictions, Scout 00 staged evidence (read-only:
 *  Attach / Dismiss keep their place, disabled), provisional score movement, IMQ readiness and — for a session linked to
 *  a Conviction company — "Record dated why-now trigger". */
import { DeferredButton } from "@/components/Deferred";
import { Badge } from "@/components/ui";
import { cx } from "@/lib/format";
import { NOT_PORTED } from "../model/deferred";
import type { Panel, Session } from "../model/types";
import { awaitingStaged, GROUPS, groupOf, movementLine, supportsTone } from "../model/view";
import { EvState } from "./EvState";
import styles from "../Evaluator.module.css";

export function JudgmentPanel({ s, P, onTrigger }: { s: Session; P: Panel; onTrigger: () => void }) {
  const ctx = s.context || {};
  const ended = s.status === "ended";
  const staged = awaitingStaged(s);
  return (
    <aside className={styles.right} data-testid="eval-right" aria-label="Judgment inputs">
      <h4 className={cx(styles.hd, styles.hdFirst)}>Judgment inputs (claims only)</h4>
      {GROUPS.map(([k, l]) => {
        const x = groupOf(P, k);
        return (
          <div key={k} className={styles.g} data-group={k}>
            <b>{l}</b>{" "}
            <span className={styles.sub}>
              {x.claims} claims{x.covered ? " · covered" : ""}
            </span>
            <div className={styles.gStates}>
              {x.states.length
                ? x.states.map(([name, n]) => (
                    <span key={name}>
                      <EvState st={name} /> {n}
                    </span>
                  ))
                : "—"}
            </div>
          </div>
        );
      })}
      <h4 className={styles.hd}>Evidence gaps</h4>
      <div className={styles.sub} data-testid="eval-gaps">
        {(P.evidence_gaps || []).join(" · ") || "none"}
      </div>
      <h4 className={styles.hd}>Contradictions</h4>
      <div className={styles.sub} data-testid="eval-contradictions">
        {(P.contradictions || []).length
          ? P.contradictions.map((x) => (
              <div key={x.id} className={styles.red}>
                ⚠ {x.text}
              </div>
            ))
          : "none"}
      </div>
      {staged.length > 0 && (
        <div data-testid="eval-staged">
          <h4 className={styles.hd}>Scout 00 evidence awaiting your review</h4>
          {staged.map((x) => {
            const cl = (s.ledger || []).find((c) => c.id === x.claim_id);
            return (
              <div key={`${x.job_id}:${x.url}`} className={styles.g}>
                <div className={styles.sub}>claim: {(cl?.text || "").slice(0, 80)}</div>
                <a href={x.url} target="_blank" rel="noopener noreferrer">
                  {x.label || x.url}
                </a>{" "}
                <Badge tone={supportsTone(x.supports)}>{x.supports}</Badge>
                <div className={styles.sub}>
                  {x.note || ""}
                  {x.date ? ` · ${x.date}` : ""} · {x.job_id}
                </div>
                {!ended && (
                  <div className={styles.qActs}>
                    <DeferredButton size="sm" reason={NOT_PORTED.bridge}>
                      Attach as public source
                    </DeferredButton>
                    <DeferredButton size="sm" reason={NOT_PORTED.bridge}>
                      Dismiss
                    </DeferredButton>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <h4 className={styles.hd}>Provisional score movement</h4>
      <div className={styles.sub} data-testid="eval-movement">
        {(P.provisional_movement || []).map((m) => (
          <div key={m.dimension}>{movementLine(m)}</div>
        ))}
      </div>
      <div className={styles.sub}>Founder statements never change the Verified score.</div>
      <h4 className={styles.hd}>IMQ readiness</h4>
      <div data-testid="eval-imq">
        <b>{P.imq?.state || ""}</b>
      </div>
      <div className={styles.sub}>
        {(P.imq?.blockers || []).slice(0, 4).map((b, i) => (
          <div key={i}>{b}</div>
        ))}
      </div>
      {ctx.slug && (
        <div className={styles.imqAct}>
          <button type="button" className={styles.lnk} onClick={onTrigger}>
            Record dated why-now trigger (sourced)
          </button>
        </div>
      )}
    </aside>
  );
}
