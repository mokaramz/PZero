/**
 * "Your context" (ported from the old page): the operating profile's fields as the server lists them (six, each up to
 * 1,200 characters), read only while the drawer is open and saved with `POST associate/profile`.
 */
import { useState } from "react";

import { Button, Drawer, ErrorBox, Field, Spinner } from "@/components/ui";
import { useAction } from "@/lib/hooks";
import { cx } from "@/lib/format";
import { ASSOCIATE, useProfile } from "../api";
import styles from "../Associate.module.css";

export function ProfileDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const q = useProfile(open);
  const [vals, setVals] = useState<Record<string, string>>({});
  // each read of the profile fills the form (adjusted while rendering, not in an effect)
  const [read, setRead] = useState<typeof q.data>(undefined);
  if (q.data !== read) {
    setRead(q.data);
    if (q.data) setVals(Object.fromEntries(q.data.fields.map((f) => [f.key, q.data!.profile[f.key] ?? ""])));
  }
  const save = useAction<Record<string, string>>(ASSOCIATE.profile, { label: "Saving your context", success: "Your context is saved", invalidates: [ASSOCIATE.profile] });
  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={560}
      title="Your context"
      actions={
        <Button variant="primary" size="sm" busy={save.isPending} onClick={() => save.mutate(vals)}>
          Save
        </Button>
      }
    >
      <p className={styles.modalNote}>
        How you like to work — PZ Associate reads this as your preferences. It never changes Project Zero's methodology, scoring or schedules.
      </p>
      {q.isLoading && <Spinner />}
      {q.error && <ErrorBox error={q.error} onRetry={() => q.refetch()} />}
      {q.data?.fields.map((f) => (
        <Field key={f.key} label={f.label}>
          <textarea className={cx(styles.field, styles.fieldArea)} rows={3} maxLength={1200} value={vals[f.key] ?? ""} onChange={(e) => setVals((v) => ({ ...v, [f.key]: e.target.value }))} />
        </Field>
      ))}
    </Drawer>
  );
}
