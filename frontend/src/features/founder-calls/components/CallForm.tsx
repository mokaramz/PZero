import { useId, useState, type FormEvent } from "react";

import { Button, Callout } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { useSaveCall } from "../api";
import { formTarget, initialAnswers, initialFields, saveBody, type FormAnswers, type FormFields } from "../model/calls";
import type { CallCtx, CallsWorkspace } from "../model/types";
import { FC_LABEL, FcLabel } from "./bits";
import styles from "../FounderCalls.module.css";

/** Log / edit a founder call. Private notes only — the POST body is v1's saveCall() body, field for field. */
export function CallForm({ fc, ctx, onCancel, onSaved }: { fc: CallsWorkspace; ctx: CallCtx; onCancel: () => void; onSaved: (id: string) => void }) {
  const toast = useToast();
  const uid = useId();
  const formId = `fcForm${uid}`;
  const { call: c, founder: fdr, company: co } = formTarget(fc, ctx);
  const a0 = c?.assessment || {};

  const [f, setF] = useState<FormFields>(() => initialFields(fc, ctx));
  const [answers, setAnswers] = useState<FormAnswers>(() => initialAnswers(c));
  const [asm, setAsm] = useState<Record<string, string>>(() => ({ ...a0 }));
  const judgmentOpen = !!(a0.recommendation || a0.why_exceptional);

  const set = (k: keyof FormFields) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  const setAns = (sid: string, patch: Partial<FormAnswers[string]>) =>
    setAnswers((x) => ({ ...x, [sid]: { ...(x[sid] || { a: "", unknown: false, followups: {} }), ...patch } }));
  const tmpl = fc.templates[f.call_type] ?? { sections: [] };

  const save = useSaveCall();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const r = await save.mutateAsync(saveBody(fc, ctx, f, answers, asm));
      toast.show(r.changed ? "Call saved (private, unverified)" : "No changes", "ok");
      onSaved(r.call.id);
    } catch {
      /* toasted */
    }
  };

  const opt = (arr: string[]) =>
    arr.map((x) => (
      <option key={x} value={x}>
        {x}
      </option>
    ));

  return (
    <div className={styles.pane} data-testid="call-form">
      <div className={styles.paneBar} data-testid="call-form-bar">
        <b className={styles.paneTitle}>{c ? "Edit call" : "Log founder call"}</b>
        <FcLabel />
        <span className="grow" />
        <div className={styles.paneActs}>
          <Button onClick={onCancel}>Cancel</Button>
          <Button variant="primary" type="submit" form={formId} busy={save.isPending}>
            Save call
          </Button>
        </div>
      </div>
      <Callout tone="amber">
        Private notes only. Nothing here verifies identity or founder status, changes Gold/Strong, rankings or evidence gates, or triggers outreach. Leave
        unknown answers empty — they stay visibly <b>UNKNOWN</b>.
      </Callout>
      <form id={formId} className={styles.form} onSubmit={submit}>
        <label className={styles.fld}>
          <span>Founder</span>
          <input value={f.founder} onChange={set("founder")} readOnly={!!(c || fdr)} required placeholder="name (required)" />
        </label>
        <label className={styles.fld}>
          <span>Company</span>
          <input value={f.company} onChange={set("company")} readOnly={!!(c || co)} required placeholder="company (required)" />
        </label>
        <label className={styles.fld}>
          <span>Call type</span>
          <select
            value={f.call_type}
            onChange={(e) => {
              setF((x) => ({ ...x, call_type: e.target.value }));
              setAnswers({}); // v1 fcRetype: a new template starts with empty answers
            }}
          >
            {Object.entries(fc.call_types).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <div className={styles.fld}>
          <span>Date · time</span>
          <div className={styles.dt}>
            <input type="date" aria-label="Date" value={f.date} onChange={set("date")} required />
            <input aria-label="Time" value={f.time} onChange={set("time")} placeholder="hh:mm" />
          </div>
        </div>
        <label className={styles.fld}>
          <span>Channel</span>
          <select value={f.channel} onChange={set("channel")}>
            {opt(fc.channels)}
          </select>
        </label>
        <label className={styles.fld}>
          <span>Participants (comma-separated)</span>
          <input value={f.participants} onChange={set("participants")} />
        </label>
        <label className={styles.fld}>
          <span>Discovery origin</span>
          <input value={f.discovery_origin} onChange={set("discovery_origin")} placeholder="how the company surfaced (scan, event, referral…)" />
        </label>
        <label className={styles.fld}>
          <span>Introduction path</span>
          <input value={f.intro_path} onChange={set("intro_path")} placeholder="who → whom" />
        </label>
        <label className={`${styles.fld} ${styles.full}`}>
          <span>Objective of this call</span>
          <input value={f.objective} onChange={set("objective")} />
        </label>

        <div className={`${styles.full} ${styles.sections}`}>
          {tmpl.sections.map((s, i) => {
            const r = answers[s.id] || { a: "", unknown: false, followups: {} };
            return (
              <section key={s.id} className={styles.sec} data-testid="call-section">
                <h3 className={styles.boxHead}>
                  {i + 1}. {s.q}
                </h3>
                <div className={styles.boxBody}>
                  <textarea
                    aria-label={`Answer: ${s.q}`}
                    value={r.a}
                    onChange={(e) => setAns(s.id, { a: e.target.value })}
                    placeholder={`Founder's answer — ${FC_LABEL}. Leave empty if not answered.`}
                  />
                  <label className={styles.unkCb}>
                    <input type="checkbox" checked={r.unknown} onChange={(e) => setAns(s.id, { unknown: e.target.checked })} /> Unknown / not answered
                  </label>
                  {s.followups.length > 0 && (
                    <details className={styles.fu}>
                      <summary>Deeper follow-ups ({s.followups.length})</summary>
                      {s.followups.map((fq, j) => (
                        <label key={j} className={styles.fld}>
                          <span>{fq}</span>
                          <textarea
                            value={r.followups[j] || ""}
                            onChange={(e) => setAns(s.id, { followups: { ...r.followups, [j]: e.target.value } })}
                          />
                        </label>
                      ))}
                    </details>
                  )}
                </div>
              </section>
            );
          })}
        </div>

        <label className={`${styles.fld} ${styles.full}`}>
          <span>Exact founder claims — one per line ({FC_LABEL})</span>
          <textarea value={f.claims} onChange={set("claims")} placeholder="Quote what the founder claimed, verbatim where possible" />
        </label>
        <label className={`${styles.fld} ${styles.full}`}>
          <span>Smooth Operator's private observations</span>
          <textarea value={f.observations} onChange={set("observations")} />
        </label>
        <label className={styles.fld}>
          <span>Risks — one per line</span>
          <textarea value={f.risks} onChange={set("risks")} />
        </label>
        <label className={styles.fld}>
          <span>Unanswered questions — one per line</span>
          <textarea value={f.open_questions} onChange={set("open_questions")} />
        </label>
        <div className={`${styles.fld} ${styles.full}`}>
          <span>Next action · owner · due date</span>
          <div className={styles.na}>
            <input aria-label="Next action" value={f.na_text} onChange={set("na_text")} placeholder="what happens next" />
            <select aria-label="Owner" value={f.na_owner} onChange={set("na_owner")}>
              {opt(fc.owners.length ? fc.owners : ["Mohamed"])}
            </select>
            <input aria-label="Due date" type="date" value={f.na_due} onChange={set("na_due")} />
          </div>
        </div>
        <details className={`${styles.full} ${styles.fu}`} open={judgmentOpen}>
          <summary>Post-call judgment (private) — fill after the call</summary>
          <div className={styles.judg}>
            {fc.assessment_fields.map(([k, l]) => (
              <label key={k} className={styles.fld}>
                <span>{l}</span>
                <textarea className={styles.short} value={asm[k] || ""} onChange={(e) => setAsm((x) => ({ ...x, [k]: e.target.value }))} />
              </label>
            ))}
            <label className={styles.fld}>
              <span>Recommendation</span>
              <select value={asm.recommendation || ""} onChange={(e) => setAsm((x) => ({ ...x, recommendation: e.target.value }))}>
                <option value="">UNKNOWN</option>
                {opt(fc.recommendations)}
              </select>
            </label>
            <label className={styles.fld}>
              <span>Confidence</span>
              <select value={asm.confidence || ""} onChange={(e) => setAsm((x) => ({ ...x, confidence: e.target.value }))}>
                <option value="">UNKNOWN</option>
                {opt(fc.confidence)}
              </select>
            </label>
            <label className={`${styles.fld} ${styles.full}`}>
              <span>Next action (judgment)</span>
              <input value={asm.next_action || ""} onChange={(e) => setAsm((x) => ({ ...x, next_action: e.target.value }))} />
            </label>
          </div>
        </details>
        <div className={`${styles.full} ${styles.formFoot}`}>
          <Button onClick={onCancel}>Cancel</Button>
          <Button variant="primary" type="submit" busy={save.isPending}>
            Save call
          </Button>
        </div>
      </form>
    </div>
  );
}
