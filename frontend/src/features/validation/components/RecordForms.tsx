import { useState } from "react";

import { Button, Field, Modal } from "@/components/ui";
import { useRecordAudit, useRecordOutcome } from "../api";
import type { Vocab } from "../model/types";
import { label } from "../model/view";
import {
  asksDatabase,
  AUDIT_FORM,
  auditBody,
  auditReady,
  auditTitle,
  needsEvidence,
  OUTCOME_FORM,
  outcomeReady,
  PREVENTABLE,
  toggleCause,
  type AuditFields,
  type AuditType,
  type OutcomeFields,
} from "../model/writes";
import styles from "../Validation.module.css";

type Change = { target: { value: string } };

/** Record a real-world milestone / outcome (append-only; needs a date, and evidence for real-world outcomes). As
 *  before, the form keeps what was typed while the page is open. */
export function OutcomeForm({ open, onClose, vocab }: { open: boolean; onClose: () => void; vocab: Vocab }) {
  const [f, setF] = useState<OutcomeFields>(OUTCOME_FORM);
  const save = useRecordOutcome();
  const needsUrl = needsEvidence(f.kind);
  const set = (k: keyof OutcomeFields) => (e: Change) => setF({ ...f, [k]: e.target.value });
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Record an outcome"
      footer={
        <Button variant="primary" busy={save.isPending} disabled={!outcomeReady(f)} onClick={() => save.mutate(f, { onSuccess: onClose })} data-testid="outcome-save">
          Record
        </Button>
      }
    >
      <p className="small faint">
        Something that happened in the world after Project Zero saw (or missed) a company. It is appended to a ledger — never edited, only retracted with a
        reason. This does not change any decision, score, Radar or IMQ.
      </p>
      <Field label="Company">
        <input value={f.company} onChange={set("company")} data-testid="outcome-company" />
      </Field>
      <Field label="What happened">
        <select value={f.kind} onChange={set("kind")} data-testid="outcome-kind">
          {Object.entries(vocab.kinds).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </Field>
      <Field label="When it happened (in the world)" hint="Not when you noticed it — this drives lead time.">
        <input type="date" value={f.event_date} onChange={set("event_date")} data-testid="outcome-date" />
      </Field>
      <Field label={needsUrl ? "Evidence URL (required)" : "Evidence URL"}>
        <input value={f.evidence_url} onChange={set("evidence_url")} placeholder="https://…" data-testid="outcome-url" />
      </Field>
      {asksDatabase(f.kind) && (
        <Field label="Which database" hint="Only a timestamp you actually saw — never an estimate.">
          <input value={f.benchmark_system} onChange={set("benchmark_system")} placeholder="Dealroom, Crunchbase, …" />
        </Field>
      )}
      <Field label="Note">
        <input value={f.note} onChange={set("note")} />
      </Field>
    </Modal>
  );
}

/** Miss audit or false-positive audit (append-only). Improves sensors and search — never the methodology. The page
 *  re-keys it by type, so each opening starts empty. */
export function AuditForm({ type, onClose, vocab }: { type: AuditType | null; onClose: () => void; vocab: Vocab }) {
  const [f, setF] = useState<AuditFields>(AUDIT_FORM);
  const save = useRecordAudit();
  const set = (k: Exclude<keyof AuditFields, "causes">) => (e: Change) => setF({ ...f, [k]: e.target.value });
  if (!type) return null;
  const miss = type === "miss";
  return (
    <Modal
      open
      onClose={onClose}
      title={auditTitle(type)}
      footer={
        <Button
          variant="primary"
          busy={save.isPending}
          disabled={!auditReady(type, f)}
          onClick={() => save.mutate(auditBody(type, f), { onSuccess: onClose })}
          data-testid="audit-save"
        >
          Record audit
        </Button>
      }
    >
      <Field label="Company">
        <input value={f.company} onChange={set("company")} data-testid="audit-company" />
      </Field>
      {miss ? (
        <>
          <Field label="Earliest public signal" hint="University page, paper, GitHub, grant, accelerator, incorporation, demo day …">
            <input value={f.earliest_signal} onChange={set("earliest_signal")} />
          </Field>
          <div className="row">
            <Field label="Signal date">
              <input type="date" value={f.earliest_signal_date} onChange={set("earliest_signal_date")} />
            </Field>
            <Field label="Where it was" className="grow">
              <input value={f.signal_source} onChange={set("signal_source")} placeholder="URL or source name" />
            </Field>
          </div>
          <Field label="Who should have found it" hint="Scout lane or source family">
            <input value={f.should_have_found} onChange={set("should_have_found")} />
          </Field>
          <div className="row">
            <Field label="Why missed">
              <select value={f.why_missed} onChange={set("why_missed")}>
                {vocab.miss_reasons.map((r) => (
                  <option key={r} value={r}>
                    {label(r)}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Preventable?">
              <select value={f.preventable} onChange={set("preventable")}>
                {PREVENTABLE.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Recommended sourcing improvement">
            <input value={f.improvement} onChange={set("improvement")} />
          </Field>
        </>
      ) : (
        <>
          {/* a fieldset, not a Field: a <label> around the checkboxes would label (and toggle) the first one */}
          <fieldset className={styles.causeSet}>
            <legend>What went wrong (pick all that apply)</legend>
            <div className={`row ${styles.causes}`}>
              {vocab.fp_causes.map((c) => (
                <label key={c} className="small">
                  <input type="checkbox" checked={f.causes.includes(c)} onChange={(e) => setF({ ...f, causes: toggleCause(f.causes, c, e.target.checked) })} />{" "}
                  {label(c)}
                </label>
              ))}
            </div>
          </fieldset>
          <Field label="Lesson" hint="The original decision stays on the record — this only explains it.">
            <input value={f.lesson} onChange={set("lesson")} />
          </Field>
        </>
      )}
      <Field label="Note">
        <input value={f.note} onChange={set("note")} />
      </Field>
    </Modal>
  );
}
