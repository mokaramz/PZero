import { useState } from "react";

import { Badge, Button, ConfirmButton } from "@/components/ui";
import { useAuditMiss, useConfirmOutcome, useDecideOutcome } from "../api";
import type { Backcast as BackcastT, Story } from "../model/types";
import {
  analysisLabel,
  canAudit,
  checkText,
  disagreementLine,
  fmt,
  independence,
  metaLine,
  NO_BACKCAST,
  proposalText,
  provenance,
  showsProposal,
  signalBadge,
  stateBadge,
  takesSignals,
  whatHappened,
} from "../model/view";
import { auditMissBody, CONFIRM_TEXT, outcomeBody } from "../model/writes";
import styles from "../News.module.css";
import { Section } from "./Section";
import { SignalForm } from "./SignalForm";

export function StoryList({ stories, empty, families, pzStart }: { stories: Story[]; empty: string; families: string[]; pzStart: string }) {
  if (!stories.length) return <div className={styles.empty}>{empty}</div>;
  return (
    <div className={styles.list}>
      {stories.map((s) => (
        <StoryCard key={s.event_id} s={s} families={families} pzStart={pzStart} />
      ))}
    </div>
  );
}

/**
 * One story: what happened and why it matters, the Project Zero check, and — opened — the backcast and the sources.
 * The decisions write (028b, ../api): the outcome proposal (Confirm outcome — two clicks — / Reject / Not enough
 * evidence), "Audit this miss" and "Add an early signal" (its form). The old "Prepare backcast research (Scout Bridge,
 * paid)" is removed.
 */
export function StoryCard({ s, families, pzStart }: { s: Story; families: string[]; pzStart: string }) {
  const [open, setOpen] = useState(false);
  const [teach, setTeach] = useState(false);
  const [addSignal, setAddSignal] = useState(false);
  const confirm = useConfirmOutcome();
  const decide = useDecideOutcome();
  const audit = useAuditMiss();
  const st = stateBadge(s.state);
  const c = s.card;
  return (
    <article className={styles.card} data-testid="news-story" data-state={s.state}>
      <div className={styles.chips}>
        {s.materiality === "HIGH" && <Badge tone="red">🔥 IMPORTANT</Badge>}
        <Badge tone={st.tone}>{st.label}</Badge>
        {s.in_deal_flow && <Badge tone="blue">YOUR DEAL FLOW</Badge>}
        <span className={styles.meta}>{metaLine(s)}</span>
      </div>
      <h3 className={styles.headline}>{s.headline}</h3>
      {s.company && <div className={styles.company}>{s.company}</div>}
      <div className={styles.body}>
        <Section title="What happened">{whatHappened(s)}</Section>
        {c?.why_it_matters && <Section title="Why it matters">{c.why_it_matters}</Section>}
        {c?.the_company && <Section title="The company">{c.the_company}</Section>}
        {c?.vc_lesson && <Section title="VC lesson">{c.vc_lesson}</Section>}
      </div>
      {!!s.source_notes?.length && (
        <div className={styles.faint} data-testid="news-source-note">
          <b>Why this source matters:</b> {s.source_notes.join(" ")}
        </div>
      )}
      {!!s.disagreements?.length && (
        <div className={styles.proposal} data-testid="news-disagreement">
          <b>Sources disagree</b> — {disagreementLine(s.disagreements)}. Project Zero does not pick a winner silently.
        </div>
      )}
      <PzCheck s={s} pzStart={pzStart} />
      {showsProposal(s) && (
        <div className={styles.proposal} data-testid="news-outcome-proposal">
          <b>Propose outcome:</b>
          {proposalText(s)}{" "}
          <ConfirmButton
            size="sm"
            variant="primary"
            busy={confirm.isPending || decide.isPending}
            confirmText={CONFIRM_TEXT}
            onConfirm={() => confirm.mutate(outcomeBody(s.event_id, "confirm"))}
          >
            Confirm outcome
          </ConfirmButton>
          <Button size="sm" onClick={() => decide.mutate(outcomeBody(s.event_id, "reject"))}>
            Reject
          </Button>
          <Button size="sm" variant="ghost" onClick={() => decide.mutate(outcomeBody(s.event_id, "not_enough"))}>
            Not enough evidence
          </Button>
        </div>
      )}
      <div className={styles.row}>
        <Button size="sm" variant="ghost" onClick={() => setOpen(!open)}>
          {analysisLabel(s, open)}
        </Button>
        {!!s.concepts.length && (
          <Button size="sm" variant="ghost" onClick={() => setTeach(!teach)} data-testid="news-teach">
            Teach me
          </Button>
        )}
        {canAudit(s) && (
          <Button size="sm" onClick={() => audit.mutate(auditMissBody(s.event_id))} data-testid="news-audit">
            Audit this miss
          </Button>
        )}
        {s.audit_id && <span className={styles.faint}>miss audit recorded</span>}
      </div>
      {teach && (
        <div className={styles.teach}>
          {s.concepts.map((k) => (
            <div key={k.id}>
              <b>{k.title}</b> {k.text}
            </div>
          ))}
        </div>
      )}
      {open && (
        <div className={styles.more}>
          {s.backcast ? <Backcast b={s.backcast} /> : takesSignals(s) && <p className={styles.faint}>{NO_BACKCAST}</p>}
          {takesSignals(s) && (
            <div className={styles.row}>
              <Button size="sm" variant="ghost" onClick={() => setAddSignal(true)}>
                Add an early signal
              </Button>
            </div>
          )}
          {!!c?.watch_next.length && (
            <Section title="What to watch next">
              <ul>
                {c.watch_next.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </Section>
          )}
          <Section title="Sources">
            <ul className={styles.sources}>
              {s.sources.map((x) => {
                const ind = independence(x.independence);
                return (
                  <li key={x.url}>
                    <a href={x.url} target="_blank" rel="noreferrer">
                      {x.publisher}
                    </a>{" "}
                    · {fmt(x.published)} <Badge tone={ind.tone}>{ind.label}</Badge>
                  </li>
                );
              })}
            </ul>
            {c && <div className={styles.faint}>{provenance(c.generated_by)}</div>}
          </Section>
        </div>
      )}
      <SignalForm open={addSignal} onClose={() => setAddSignal(false)} eventId={s.event_id} families={families} />
    </article>
  );
}

function PzCheck({ s, pzStart }: { s: Story; pzStart: string }) {
  const t = checkText(s, pzStart);
  return (
    <div className={styles.check} data-testid="news-check">
      <span className={styles.kicker}>Project Zero check</span>{" "}
      {t.strong && (
        <>
          <b>{t.strong}</b>{" "}
        </>
      )}
      {t.text}
    </div>
  );
}

function Backcast({ b }: { b: BackcastT }) {
  return (
    <div className={styles.section} data-testid="news-backcast">
      <div className={styles.kicker}>Backcast — what could we have seen?</div>
      <ol className={styles.timeline}>
        {b.timeline.map((x) => {
          const k = signalBadge(x.kind);
          return (
            <li key={`${x.date}-${x.text}`}>
              <span className={styles.when}>{fmt(x.date)}</span> {x.text} <Badge tone={k.tone}>{k.label}</Badge>{" "}
              <a href={x.url} target="_blank" rel="noreferrer">
                source
              </a>
            </li>
          );
        })}
      </ol>
      {b.earliest_plausible_signal && (
        <p>
          <b>Earliest plausible signal:</b> {b.earliest_plausible_signal.text} ({fmt(b.earliest_plausible_signal.date)})
          <br />
          <b>Best sensor today:</b> {b.best_sensor}
        </p>
      )}
      <p>
        <b>Learning:</b> {b.learning}
      </p>
      <p className={styles.faint}>A learning is a proposal for sourcing — it never changes scores, sources or themes on its own.</p>
    </div>
  );
}
