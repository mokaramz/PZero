/**
 * "Save as a draft" (ported from the old page): the answer's text, editable, saved to the Associate's OWN drafts only
 * when Save draft is clicked — `POST associate/draft` with `confirm: true`. Cancel, Escape or the close button send
 * nothing.
 */
import { useState } from "react";

import { Button, Field, Modal } from "@/components/ui";
import { useAction } from "@/lib/hooks";
import { cx } from "@/lib/format";
import { ASSOCIATE } from "../api";
import type { DraftBody, Ref } from "../model/types";
import styles from "../Associate.module.css";

export type DraftSeed = { title: string; body: string; ref?: Ref };

export function DraftModal({ draft, conversationId, onClose }: { draft: DraftSeed | null; conversationId: string | null; onClose: () => void }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  // a new answer to save fills the form (adjusted while rendering, not in an effect)
  const [seed, setSeed] = useState<DraftSeed | null>(null);
  if (draft !== seed) {
    setSeed(draft);
    if (draft) {
      setTitle(draft.title);
      setBody(draft.body);
    }
  }
  const save = useAction<DraftBody>(ASSOCIATE.draft, {
    label: "Saving draft",
    success: "Draft saved to your PZ Associate drafts — nothing was sent",
    invalidates: [ASSOCIATE.drafts],
  });
  return (
    <Modal
      open={!!draft}
      onClose={onClose}
      title="Save as a draft"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            busy={save.isPending}
            disabled={!body.trim()}
            onClick={() => save.mutate({ title, body, ref: draft?.ref, conversation_id: conversationId, confirm: true }, { onSuccess: onClose })}
          >
            Save draft
          </Button>
        </>
      }
    >
      <p className={styles.modalNote}>Saved only to your PZ Associate drafts in the Project Zero database. It is not sent to anyone and changes no record.</p>
      <Field label="Title">
        <input className={styles.field} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} />
      </Field>
      <Field label="Text">
        <textarea className={cx(styles.field, styles.fieldArea)} value={body} onChange={(e) => setBody(e.target.value)} rows={10} />
      </Field>
    </Modal>
  );
}
