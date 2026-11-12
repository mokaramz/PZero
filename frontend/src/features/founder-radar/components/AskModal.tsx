import { useState } from "react";

import { Button, Callout, Field, Modal } from "@/components/ui";
import { initialValues, missingRequired, visibleFields, type AskField, type AskSpec, type Values } from "../model/ask";
import styles from "../FounderRadar.module.css";

/** The old AskDialog: the fields of `spec`, then (with `confirm`) a summary that needs a second press. Cancel, Escape or
 *  the backdrop answer null. */
export function AskModal({ spec, onDone }: { spec: AskSpec; onDone: (v: Values | null) => void }) {
  const [vals, setVals] = useState<Values>(() => initialValues(spec.fields));
  const [confirming, setConfirming] = useState(false);
  const visible = visibleFields(spec.fields, vals);
  const missing = missingRequired(spec.fields, vals);
  const set = (name: string, v: string | boolean) => setVals((x) => ({ ...x, [name]: v }));

  const submit = () => {
    if (missing) return;
    if (spec.confirm && !confirming) {
      setConfirming(true);
      return;
    }
    onDone(vals);
  };

  return (
    <Modal
      open
      onClose={() => onDone(null)}
      title={spec.title}
      width={620}
      footer={
        <>
          {confirming && <Button onClick={() => setConfirming(false)}>Back</Button>}
          <Button onClick={() => onDone(null)}>Cancel</Button>
          <Button variant="primary" disabled={missing} onClick={submit}>
            {confirming ? "Confirm" : (spec.submitLabel ?? "OK")}
          </Button>
        </>
      }
    >
      {spec.intro && <Callout tone="amber">{spec.intro}</Callout>}
      {confirming && spec.confirm ? (
        <div className={styles.confirmBox} role="alert">
          {spec.confirm(vals)}
        </div>
      ) : (
        <form
          className={styles.askForm}
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          {visible.map((f, i) => (
            <AskInput key={f.name} f={f} first={i === 0} value={vals[f.name]} onChange={(v) => set(f.name, v)} />
          ))}
          <button type="submit" hidden />
        </form>
      )}
    </Modal>
  );
}

function AskInput({ f, first, value, onChange }: { f: AskField; first: boolean; value: string | boolean | undefined; onChange: (v: string | boolean) => void }) {
  if (f.type === "checkbox")
    return (
      <label className={styles.check}>
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {f.label}
      </label>
    );
  const text = String(value ?? "");
  return (
    <Field label={f.label + (f.required ? " *" : "")} hint={f.hint}>
      {f.type === "textarea" ? (
        <textarea autoFocus={first} rows={3} placeholder={f.placeholder} value={text} onChange={(e) => onChange(e.target.value)} />
      ) : f.type === "select" ? (
        <select autoFocus={first} value={text} onChange={(e) => onChange(e.target.value)}>
          <option value="">choose…</option>
          {(f.options ?? []).map((o) => {
            const opt = typeof o === "string" ? { value: o, label: o } : o;
            return (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            );
          })}
        </select>
      ) : (
        <input autoFocus={first} type={f.type === "date" ? "date" : "text"} placeholder={f.placeholder} value={text} onChange={(e) => onChange(e.target.value)} />
      )}
    </Field>
  );
}
