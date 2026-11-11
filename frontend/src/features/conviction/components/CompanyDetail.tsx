/**
 * Right-hand company workspace — a decision workspace, not a dashboard. Above the fold: the company, what it is, its
 * CURRENT STATE, and the prepared case (why it matters · biggest risk · top unknown · PZ view · your move). Everything
 * else is one deliberate click below, in a few grouped sections (CasePanel). Secondary company actions sit in one
 * Actions menu; the one contextual primary action lives in the decision anchor.
 */
import { ConvergenceTrace, HighlightStrip, Monogram, StatusChip, VerificationBar, type Highlight } from "@/components/focus";
import { Icon } from "@/components/Icon";
import { ago, cx } from "@/lib/format";
import { archetypeOf, convergenceSources, currentState, human, pzView, sentence, verifiedCount } from "../model/logic";
import type { Meta, Signal } from "../model/types";
import { ActionsMenu, type DetailActions } from "./ActionsMenu";
import { CasePanel } from "./CasePanel";
import { Score } from "./parts";
import styles from "../Conviction.module.css";

export function CompanyDetail({ e, all, meta, actions }: { e: Signal; all: Signal[]; meta?: Meta; actions: DetailActions }) {
  const a = archetypeOf(meta, e.archetype);
  const st = currentState(e);
  return (
    <article className={styles.detail} aria-label={e.company}>
      <header className={styles.head}>
        <div className={styles.headTop}>
          <Monogram name={e.company} size={56} />
          <div className={styles.identity}>
            <h2 className={styles.company} title={e.discovery_status ?? undefined}>
              {e.company}
            </h2>
            {e.one_liner && (
              <p className={styles.oneLiner} title={e.one_liner}>
                {e.one_liner}
              </p>
            )}
            <div className={styles.chips}>
              {e.earliness && e.earliness !== "unknown" && <StatusChip>{human(e.earliness)}</StatusChip>}
              {e.location && (
                <span className={styles.geo}>
                  <Icon name="pin" size={13} /> {e.location}
                </span>
              )}
              {a && (
                <span className={styles.meta}>
                  #{a.id} {a.name}
                </span>
              )}
            </div>
          </div>
          <div className={styles.scoreBlock} data-testid="score-block">
            <span>
              <Score value={e.sc.provisional} kind="prov" /> <span className={styles.sub}>provisional</span>
            </span>
            <span>
              <Score value={e.sc.verified} kind="ver" /> <span className={styles.sub}>verified</span>
            </span>
            {/* the band is the PZ view; repeat it here only when the PZ view shows something else (watching / gated) */}
            {e.op && e.op.source !== "score band" && pzView(e) !== sentence(e.sc.verdict) && (
              <span className={styles.band} data-testid="score-band">
                score band: {e.sc.verdict}
              </span>
            )}
            <div className={styles.traceSlot}>
              <ConvergenceTrace sources={convergenceSources(e)} target={e.company} testId="company-convergence" />
            </div>
          </div>
        </div>
        <div className={styles.stateRow}>
          <span className={styles.stateLabel}>Current state</span>
          <span className={cx(styles.state, styles[`st_${st.tone}`])} data-testid="op-status" title={e.op ? `${e.op.action} (${e.op.source})` : undefined}>
            {st.label}
          </span>
          {st.why && (
            <span className={styles.stateWhy} title={st.why}>
              {st.why}
            </span>
          )}
          <ActionsMenu e={e} actions={actions} />
        </div>
      </header>
      <HighlightStrip testId="company-highlights" items={highlights(e)} />
      <CasePanel e={e} all={all} meta={meta} actions={actions} />
    </article>
  );
}

/** Founders · funding · strongest signal · geography · verification — empty ones are not shown. */
function highlights(e: Signal): Highlight[] {
  const names = (e.founders ?? []).map((f) => f.name || "").filter(Boolean);
  const funding = e.funding_status || (e.fundraising_timing && e.fundraising_timing !== "unknown" ? human(e.fundraising_timing) : "");
  const strongest = (e.founder_signal || e.why_project_a || "").split(/[.;—]/)[0].trim();
  const n = verifiedCount(e);
  return [
    { icon: "people", label: "Founders", value: names.length ? `${names.length} named` : "UNKNOWN", hint: names.slice(0, 2).join(", ") || undefined },
    {
      icon: "funding",
      label: "Funding",
      value: funding ? funding.split(/[;,(]/)[0].trim().slice(0, 44) || undefined : undefined,
      hint: funding.includes(",") || funding.includes(";") ? "details in Funding & timing" : undefined,
    },
    { icon: "signal", label: "Strongest signal", value: strongest ? (strongest.length > 48 ? `${strongest.slice(0, 46)}…` : strongest) : undefined, tone: "progress" },
    { icon: "pin", label: "Geography", value: e.location || undefined },
    {
      icon: "shield",
      label: "Verification",
      value: (
        <>
          {n} of 3 core facts
          <VerificationBar n={n} of={3} label={`${n} of 3 core facts verified`} />
        </>
      ),
      tone: n === 3 ? "progress" : undefined,
      hint: e.discovery_date ? `in PZ since ${ago(e.discovery_date)}` : undefined,
    },
  ];
}
