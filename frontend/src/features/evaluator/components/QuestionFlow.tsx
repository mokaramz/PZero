/** The centre column: the current question (Record answer / UNKNOWN / Skip) or, once ended, the summary with its tasks,
 *  follow-ups, memo deltas and the Founder Call link; then "Then ask", "Asked so far" and End evaluation (confirmed). */
import { useState } from "react";
import { Link } from "react-router-dom";

import { Disclosure } from "@/components/focus";
import { Badge, Button, Callout } from "@/components/ui";
import type { Confirm } from "@/components/useConfirm";
import { cx } from "@/lib/format";
import { useAnswer, useEnd, useSkip } from "../api";
import type { EvaluationDetail, EvaluationsWorkspace, Question, Session } from "../model/types";
import { askedQuestions, callLink, familyLabel, isUnknownAnswer, newestFirst, openContradictions, questionTone } from "../model/view";
import { EvState } from "./EvState";
import styles from "../Evaluator.module.css";

const END_MESSAGE =
  "End evaluation? This creates the Founder Call record, verification tasks and provisional notes. Verified score unchanged, nothing sent to Manager.";

export function QuestionFlow({ d, w, confirm }: { d: EvaluationDetail; w: EvaluationsWorkspace; confirm: Confirm }) {
  const s = d.session;
  const qn = d.next;
  const ended = s.status === "ended";
  const answerA = useAnswer();
  const skipA = useSkip();
  const endA = useEnd();
  const busy = answerA.isPending || skipA.isPending || endA.isPending;
  const asked = askedQuestions(s);

  const end = async () => {
    const ok = await confirm(END_MESSAGE, { title: "End evaluation", ok: "End evaluation" });
    if (ok) endA.mutate({ id: s.id });
  };

  return (
    <div className={styles.center} data-testid="eval-center">
      <section className={styles.sect}>
        <h4 className={styles.hd}>{ended ? "Evaluation ended" : "Current question"}</h4>
        {ended && s.ended ? (
          <EndedSummary s={s} />
        ) : qn ? (
          <CurrentQuestion
            key={qn.id}
            qn={qn}
            w={w}
            busy={busy}
            onAnswer={(text) => answerA.mutate({ id: s.id, qid: qn.id, text })}
            onSkip={() => skipA.mutate({ id: s.id, qid: qn.id })}
          />
        ) : (
          <Callout tone="blue">
            All rubric families covered. Review the ledger, then <b>End evaluation</b>.
          </Callout>
        )}
      </section>
      {!ended && (
        <section className={styles.sect}>
          <h4 className={styles.hd}>Then ask</h4>
          {(s.queue || []).length ? (
            <>
              {s.queue.slice(0, 2).map((f, i) => (
                <div key={i} className={styles.sub} data-testid="eval-next">
                  • {f.text}
                </div>
              ))}
              {s.queue.length > 2 && (
                <Disclosure title={`View full question bank (${s.queue.length - 2} more)`} testId="eval-bank">
                  {s.queue.slice(2).map((f, i) => (
                    <div key={i} className={styles.sub}>
                      • [{f.kind}] {f.text}
                    </div>
                  ))}
                </Disclosure>
              )}
            </>
          ) : (
            <div className={styles.sub}>none — the next question comes from the highest-priority open family: {(s.plan || [])[0]?.label || "—"}</div>
          )}
        </section>
      )}
      <section className={cx(styles.sect, styles.sectLast)}>
        <Disclosure title={`Asked so far (${asked.length})`} testId="eval-asked">
          {asked.length ? (
            newestFirst(asked).map((x) => (
              <div key={x.id} className={styles.qa}>
                <div className={styles.sub}>
                  {familyLabel(w, x.family)} · {x.kind}
                </div>
                <div>
                  <b>Q:</b> {x.text}
                </div>
                <div>
                  <b>A:</b> {x.answer} <EvState st={isUnknownAnswer(x.answer) ? "UNKNOWN" : "FOUNDER-REPORTED"} />
                </div>
              </div>
            ))
          ) : (
            <div className={styles.sub}>nothing yet</div>
          )}
        </Disclosure>
        {!ended && (
          <div className={styles.endRow}>
            <Button variant="primary" onClick={() => void end()} busy={endA.isPending}>
              End evaluation
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}

/** The open question: its kind, family, text and why, the founder's answer and the three ways on. Keyed by the
 *  question, so a new question starts with an empty answer. */
function CurrentQuestion({
  qn,
  w,
  busy,
  onAnswer,
  onSkip,
}: {
  qn: Question;
  w: EvaluationsWorkspace;
  busy: boolean;
  onAnswer: (text: string) => void;
  onSkip: () => void;
}) {
  const [answer, setAnswer] = useState("");
  return (
    <>
      <div className={styles.q} data-testid="eval-question">
        <Badge tone={questionTone(qn.kind)}>{qn.kind}</Badge> <span className={styles.sub}>{familyLabel(w, qn.family)}</span>
        <div className={styles.qText}>{qn.text}</div>
        <div className={styles.sub}>
          Why: {qn.reason || ""}
          {qn.verification_hint && qn.verification_hint !== "—" ? ` · verify via: ${qn.verification_hint}` : ""}
        </div>
      </div>
      <textarea
        aria-label="Founder's answer"
        rows={4}
        value={answer}
        onChange={(e) => setAnswer(e.target.value)}
        placeholder="Founder's answer, in their words (stays FOUNDER-REPORTED — unverified). Type 'unknown' to record an UNKNOWN."
      />
      <div className={styles.qActs}>
        <Button variant="primary" onClick={() => onAnswer(answer)} disabled={busy}>
          Record answer → next
        </Button>
        <Button onClick={() => onAnswer("unknown")} disabled={busy}>
          UNKNOWN
        </Button>
        <Button onClick={onSkip} disabled={busy} title="Park this question — it comes back as an end-of-call follow-up">
          Skip
        </Button>
      </div>
    </>
  );
}

function EndedSummary({ s }: { s: Session }) {
  const e = s.ended!;
  const L = s.ledger || [];
  const open = openContradictions(L);
  return (
    <>
      <Callout tone="blue" data-testid="eval-ended">
        Ended {e.on} · Founder Call record {e.call_id ? "created" : "—"}
        {e.canonical_sections
          ? ` (${e.canonical_answered ?? 0} of ${e.canonical_sections} canonical sections mapped from founder-reported answers; the rest stay UNKNOWN)`
          : ""}
        <br />
        {e.answers ?? "—"} answers → {e.founder_reported} founder-reported claims · {e.deck_claims} deck claims · {e.unknowns} UNKNOWN · {e.contradictions}{" "}
        contradiction(s) · {e.ledger_items ?? L.length} ledger items · {e.tasks} verification task(s)
        <br />
        Verified score changed: <b>no</b> · sent to Manager: <b>no</b> · IMQ: <b>{e.imq.state}</b>
        {e.imq.blockers.length ? ` — ${e.imq.blockers[0]}` : ""}
        {e.count_note && <div className={styles.sub}>{e.count_note}</div>}
        {e.call_id && (
          <div>
            <Link to={callLink(e.call_id)}>Open the Founder Call record</Link>
          </div>
        )}
      </Callout>
      {open.length > 0 && (
        <>
          <h4 className={styles.hd}>Contradictions (unresolved)</h4>
          {open.map((x) => (
            <div key={x.id} className={styles.sub}>
              ⚠ {x.text}
            </div>
          ))}
        </>
      )}
      <h4 className={styles.hd}>Verification tasks</h4>
      {(s.tasks || []).length ? (
        s.tasks.map((t) => (
          <div key={t.id} className={styles.sub} data-testid="eval-task">
            ☐ {t.text} <i>({t.how})</i>
          </div>
        ))
      ) : (
        <div className={styles.sub}>none</div>
      )}
      <h4 className={styles.hd}>Follow-up questions</h4>
      {(e.followups || []).map((f, i) => (
        <div key={i} className={styles.sub} data-testid="eval-followup">
          • {f}
        </div>
      ))}
      <h4 className={styles.hd}>Draft memo deltas (provisional)</h4>
      {(s.memo_deltas || []).length ? (
        s.memo_deltas.map((m, i) => (
          <div key={i} className={styles.sub} data-testid="eval-delta">
            • {m}
          </div>
        ))
      ) : (
        <div className={styles.sub}>none</div>
      )}
    </>
  );
}
