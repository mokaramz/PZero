/** "Record dated why-now trigger" (v1 imqTrigger prompts, review 024): the kind, the date, the public source and the
 *  dated fact, then a second step that shows exactly what is recorded before `POST imq_trigger` with `confirm: true`.
 *  A refusal keeps the dialog open on its confirmation step (failure toast); a success closes it and refreshes the set. */
import { useState } from "react";

import { Button, Callout, Field, Modal } from "@/components/ui";
import { useImqTrigger } from "../api";
import type { WhyNow } from "../model/case";
import { TRIGGER_KINDS } from "../model/logic";
import styles from "../Conviction.module.css";

export function TriggerModal({
  slug,
  onClose,
  init,
}: {
  slug: string;
  onClose: () => void;
  /** prefilled from a prepared case (a dated public source Project Zero found) — the operator still reviews and confirms */
  init?: Partial<WhyNow>;
}) {
  const [kind, setKind] = useState(init?.kind ?? "trigger");
  const [date, setDate] = useState(init?.date ?? "");
  const [url, setUrl] = useState(init?.url ?? "");
  const [fact, setFact] = useState(init?.fact ?? "");
  const [confirming, setConfirming] = useState(false);
  const act = useImqTrigger();
  const ready = kind && date && url;

  return (
    <Modal
      open
      onClose={onClose}
      title="Record dated why-now trigger"
      footer={
        confirming ? (
          <>
            <Button onClick={() => setConfirming(false)}>Back</Button>
            <Button
              variant="primary"
              busy={act.isPending}
              onClick={() =>
                act
                  .mutateAsync({ slug, kind, date, url, fact, confirm: true })
                  .then(onClose)
                  .catch(() => undefined)
              }
            >
              Record trigger
            </Button>
          </>
        ) : (
          <>
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" disabled={!ready} onClick={() => setConfirming(true)}>
              Review
            </Button>
          </>
        )
      }
    >
      {confirming ? (
        <Callout tone="amber" data-testid="trigger-review">
          <b>Record why-now trigger:</b>
          <div>
            {kind} · {date}
          </div>
          <div>“{fact}”</div>
          <div>{url}</div>
        </Callout>
      ) : (
        <div className={styles.inputs}>
          <Field label="Trigger kind">
            <select value={kind} onChange={(ev) => setKind(ev.target.value)}>
              {TRIGGER_KINDS.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </Field>
          <Field label="Date of the trigger (YYYY-MM-DD) — when it happened, not today">
            <input value={date} onChange={(ev) => setDate(ev.target.value)} placeholder="YYYY-MM-DD" />
          </Field>
          <Field label="Public source URL that documents it (not LinkedIn, not a search result)">
            <input value={url} onChange={(ev) => setUrl(ev.target.value)} />
          </Field>
          <Field label="The dated fact as the source states it">
            <textarea rows={2} value={fact} onChange={(ev) => setFact(ev.target.value)} />
          </Field>
        </div>
      )}
    </Modal>
  );
}
