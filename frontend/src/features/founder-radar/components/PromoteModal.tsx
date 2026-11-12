import { useState } from "react";

import { Button, Callout, Field, Modal } from "@/components/ui";
import { usePromote } from "../api";
import { useFr } from "../context";
import type { PromoteForm } from "../model/types";
import styles from "../FounderRadar.module.css";

/** "Add to Network": a state transition on the same record — only the relationship facts are asked. The promotion
 *  guard's refusal ("Resolve identity before promotion") is toasted and the dialog stays open. */
export function PromoteModal({ personId, onClose }: { personId: string | null; onClose: () => void }) {
  const { data } = useFr();
  const p = data.people.find((x) => x.id === personId);
  return (
    <Modal open={!!personId} onClose={onClose} title={`Add to Network — ${p?.name || ""}`} width={640}>
      {personId && <PromoteBody key={personId} id={personId} states={data.network_states ?? []} onDone={onClose} />}
    </Modal>
  );
}

function PromoteBody({ id, states, onDone }: { id: string; states: string[]; onDone: () => void }) {
  const promote = usePromote();
  const [f, setF] = useState<PromoteForm>({
    how: "",
    introduced_by: "",
    stage: states[0] ?? "",
    last_interaction: "",
    next_action: "",
    next_action_date: "",
    channel: "",
    notes: "",
  });
  const set = (k: keyof PromoteForm) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));
  return (
    <form
      className={styles.askForm}
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          const r = await promote.mutateAsync({ id, ...f });
          if (r.ok) onDone();
        } catch {
          /* guard refusal toasted (e.g. "Resolve identity before promotion") */
        }
      }}
    >
      <Callout tone="blue">
        State transition on the same record: identity, sources, evidence, why-surfaced, links, notes, judgments and history are all kept. Only relationship
        facts are asked for.
      </Callout>
      <Field label="How do you know them?">
        <input value={f.how} onChange={set("how")} placeholder="met at KIT demo day / warm intro / cold outreach" />
      </Field>
      <Field label="Introduced by">
        <input value={f.introduced_by} onChange={set("introduced_by")} />
      </Field>
      <div className={styles.twoCol}>
        <Field label="Relationship stage">
          <select value={f.stage} onChange={set("stage")}>
            {states.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </Field>
        <Field label="Last interaction">
          <input type="date" value={f.last_interaction} onChange={set("last_interaction")} />
        </Field>
        <Field label="Next follow-up">
          <input value={f.next_action} onChange={set("next_action")} placeholder="what" />
        </Field>
        <Field label="Follow-up date">
          <input type="date" value={f.next_action_date} onChange={set("next_action_date")} />
        </Field>
      </div>
      <Field label="Preferred channel">
        <input value={f.channel} onChange={set("channel")} placeholder="email / WhatsApp / LinkedIn message (manual)" />
      </Field>
      <Field label="Private notes">
        <textarea rows={3} value={f.notes} onChange={set("notes")} />
      </Field>
      <div>
        <Button variant="primary" type="submit" busy={promote.isPending}>
          Add to Network
        </Button>
      </div>
    </form>
  );
}
