import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { Button, Callout, Field } from "@/components/ui";
import { useAction } from "@/lib/hooks";
import { duplicateOf, NETWORK_KEYS, PERSON_SAVE, personLink, type PersonSaveResult } from "../api";
import { startupsOf, today } from "../model/peopleUtil";
import { PERSON_FIELDS, type PeoplePayload, type Person, type PersonSaveBody } from "../model/types";
import { TalentedForm } from "./TalentedForm";
import styles from "../Network.module.css";

/**
 * Add / edit a person (v1 openPerson + savePerson) plus the "3 most talented" ritual for existing people. An add whose
 * person already exists is refused (409, review 013 decision a) and offers that person instead; any other refusal
 * keeps the form as typed.
 */
export function PersonForm({ p, data, onDone }: { p: Person | null; data: PeoplePayload; onDone: (id?: string) => void }) {
  const navigate = useNavigate();
  const [dup, setDup] = useState<{ id: string; message: string } | null>(null);
  const save = useAction<PersonSaveBody, PersonSaveResult>(PERSON_SAVE, { invalidates: NETWORK_KEYS, label: "Saving the person", success: "Saved" });

  const submit = async (ev: FormEvent<HTMLFormElement>) => {
    ev.preventDefault();
    setDup(null);
    const fd = new FormData(ev.currentTarget);
    const o: PersonSaveBody = p ? { id: p.id } : {};
    for (const k of PERSON_FIELDS) o[k] = String(fd.get(k) ?? "");
    o.watch = fd.get("watch") === "on";
    const r = await save.mutateAsync(o).catch((err: unknown) => {
      setDup(duplicateOf(err));
      return null;
    });
    if (r) onDone(r.id);
  };

  const openExisting = (id: string) => {
    onDone();
    navigate(personLink(id));
  };

  const opts = (m: Record<string, string>) =>
    Object.entries(m).map(([k, l]) => (
      <option key={k} value={k}>
        {l}
      </option>
    ));

  return (
    <div className="stack">
      <form className={styles.formGrid} onSubmit={submit} aria-label="Person form">
        <Field label="Name">
          <input name="name" required defaultValue={p?.name ?? ""} />
        </Field>
        <Field label="Location">
          <input name="location" defaultValue={p?.location ?? ""} />
        </Field>
        <Field label="Company">
          <input name="company" defaultValue={p?.company ?? ""} />
        </Field>
        <Field label="Role">
          <input name="role" defaultValue={p?.role ?? ""} />
        </Field>
        <Field label="University">
          <input name="university" defaultValue={p?.university ?? ""} />
        </Field>
        <Field label="Technical expertise">
          <input name="expertise" defaultValue={p?.expertise ?? ""} />
        </Field>
        <Field label="Why interesting" className={styles.fullCol}>
          <input name="why_interesting" defaultValue={p?.why_interesting ?? ""} />
        </Field>
        <Field label="How discovered (event, Boardy, referral...)">
          <input name="discovery" defaultValue={p?.discovery ?? ""} />
        </Field>
        <Field label="Founder potential">
          <select name="founder_potential" defaultValue={p?.founder_potential ?? "maybe"}>
            {opts(data.potential)}
          </select>
        </Field>
        <Field label="Relationship strength">
          <select name="relationship_strength" defaultValue={p?.relationship_strength ?? "met_once"}>
            {opts(data.strengths)}
          </select>
        </Field>
        <Field label="Last interaction (YYYY-MM-DD)">
          <input name="last_interaction" defaultValue={p ? (p.last_interaction ?? "") : today()} />
        </Field>
        <Field label="LinkedIn">
          <input name="linkedin" defaultValue={p?.linkedin ?? ""} />
        </Field>
        <Field label="X / Twitter">
          <input name="x" defaultValue={p?.x ?? ""} />
        </Field>
        <Field label="Associated startups (comma-separated)">
          <input name="startups" defaultValue={p ? startupsOf(p).join(", ") : ""} />
        </Field>
        <Field label="Email">
          <input name="email" defaultValue={p?.email ?? ""} />
        </Field>
        <div className={styles.watchCell}>
          <label className={styles.check}>
            <input type="checkbox" name="watch" defaultChecked={!!p?.watch} /> Watch (signal watchlist — weekly manual sweep)
          </label>
          <Field label="GitHub profile (optional)">
            <input name="github" defaultValue={p?.github ?? ""} />
          </Field>
        </div>
        <Field label="Next action">
          <input name="next_action" defaultValue={p?.next_action ?? ""} />
        </Field>
        <Field label="Next action date (YYYY-MM-DD)">
          <input name="next_action_date" defaultValue={p?.next_action_date ?? ""} />
        </Field>
        <Field label="Notes" className={styles.fullCol}>
          <textarea name="notes" rows={3} defaultValue={p?.notes ?? ""} />
        </Field>
        <Callout tone="amber" className={styles.fullCol}>
          Data rule: everything here is <b>user-provided</b> — the tool never fills in facts about people. Leave unknown fields <b>empty</b> instead
          of guessing; auto-created follow-ups are labelled <b>SUGGESTED:</b> and are yours to change or delete.
        </Callout>
        {dup && (
          <Callout tone="amber" role="alert" className={styles.fullCol} data-testid="save-duplicate">
            <div className="row">
              <span className="grow">{dup.message}</span>
              <Button size="sm" variant="primary" onClick={() => openExisting(dup.id)}>
                Open existing person
              </Button>
            </div>
          </Callout>
        )}
        <div className={styles.fullCol}>
          <Button type="submit" variant="success" size="lg" busy={save.isPending}>
            Save person
          </Button>
        </div>
      </form>
      {p && (
        <Callout tone="blue">
          <TalentedForm person={p} variant="ritual" onDone={() => onDone(p.id)} />
        </Callout>
      )}
    </div>
  );
}
