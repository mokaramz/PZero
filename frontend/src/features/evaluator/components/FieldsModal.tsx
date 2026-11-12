/** The old labelled replacement for v1's chain of window.prompt()s (start, attach a source, operator verified, resolve,
 *  the why-now trigger): the same values, trimmed, handed to `onSubmit` after the dialog closes. */
import { useState, type FormEvent, type ReactNode } from "react";

import { Button, Field, Modal } from "@/components/ui";
import styles from "../Evaluator.module.css";

export type FieldSpec = {
  name: string;
  label: string;
  type?: "text" | "date" | "url" | "textarea" | "select";
  options?: string[];
  required?: boolean;
  initial?: string;
  placeholder?: string;
};

export type FieldsAsk = { title: string; intro?: ReactNode; fields: FieldSpec[]; ok: string; onSubmit: (v: Record<string, string>) => void };

const FORM_ID = "evaluatorFieldsForm";

export function FieldsModal({ ask, onClose }: { ask: FieldsAsk | null; onClose: () => void }) {
  return (
    <Modal
      open={!!ask}
      onClose={onClose}
      title={ask?.title}
      width={560}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form={FORM_ID}>
            {ask?.ok}
          </Button>
        </>
      }
    >
      {ask && <Fields key={ask.title} ask={ask} onClose={onClose} />}
    </Modal>
  );
}

/** The form itself: mounted with each ask, so its values start from that ask's `initial`s. */
function Fields({ ask, onClose }: { ask: FieldsAsk; onClose: () => void }) {
  const [v, setV] = useState<Record<string, string>>(() =>
    Object.fromEntries(ask.fields.map((f) => [f.name, f.initial ?? (f.type === "select" ? (f.options?.[0] ?? "") : "")])),
  );
  const set = (name: string, value: string) => setV((x) => ({ ...x, [name]: value }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const out = Object.fromEntries(Object.entries(v).map(([k, x]) => [k, x.trim()]));
    onClose();
    ask.onSubmit(out);
  };
  return (
    <form id={FORM_ID} className={styles.modalForm} onSubmit={submit}>
      {ask.intro && <div className={styles.sub}>{ask.intro}</div>}
      {ask.fields.map((f, i) => (
        <Field key={f.name} label={f.label}>
          {f.type === "textarea" ? (
            <textarea rows={3} value={v[f.name] ?? ""} required={f.required} placeholder={f.placeholder} onChange={(e) => set(f.name, e.target.value)} />
          ) : f.type === "select" ? (
            <select value={v[f.name] ?? ""} onChange={(e) => set(f.name, e.target.value)}>
              {(f.options ?? []).map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          ) : (
            <input
              autoFocus={i === 0}
              type={f.type ?? "text"}
              value={v[f.name] ?? ""}
              required={f.required}
              placeholder={f.placeholder}
              onChange={(e) => set(f.name, e.target.value)}
            />
          )}
        </Field>
      ))}
    </form>
  );
}
