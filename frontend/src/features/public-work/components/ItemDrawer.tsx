/** Add or edit one public-work item. An edit sends `{id, …fields}` (`saveBody`: a non-text stored value the operator
 *  did not touch is left out, so it survives), a new item only the fields; a save or a delete closes the drawer, a
 *  refused one keeps it open (the failure is the standard action-error toast). */
import { useState, type FormEvent } from "react";

import { useToast } from "@/components/Toast";
import { Button, Callout, Drawer, Field } from "@/components/ui";
import { useDeleteItem, useSaveItem } from "../api";
import { fieldsOf, KINDS, PLATFORMS, saveBody, type Item, type ItemFields } from "../model/item";
import styles from "../PublicWork.module.css";

export function ItemDrawer({ item, onClose }: { item: Item | null; onClose: () => void }) {
  const [f, setF] = useState<ItemFields>(() => fieldsOf(item));
  const toast = useToast();
  const save = useSaveItem();
  const del = useDeleteItem();
  const [touched, setTouched] = useState<ReadonlySet<keyof ItemFields>>(() => new Set());
  const set = (k: keyof ItemFields) => (e: { target: { value: string } }) => {
    setF((x) => ({ ...x, [k]: e.target.value }));
    setTouched((t) => new Set(t).add(k));
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate(saveBody(item, f, touched), { onSuccess: onClose });
  };

  const remove = (id: string) =>
    del.mutate(
      { id },
      {
        onSuccess: () => {
          toast.show("Deleted", "ok");
          onClose();
        },
      },
    );

  return (
    <Drawer open onClose={onClose} title={item ? "Edit item" : "New public-work item"} width={640}>
      <Callout tone="amber">
        <b>Before publishing, check:</b> does this describe you as a Project A Scout? It must not. Porsche / automotive / engineering positioning only.
      </Callout>
      <form className={styles.form} onSubmit={submit} aria-label="Public work item">
        <Field label="Title / topic" className={styles.full}>
          <input name="title" required value={f.title} onChange={set("title")} />
        </Field>
        <Field label="Platform">
          <select name="platform" value={f.platform} onChange={set("platform")}>
            {PLATFORMS.map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </Field>
        <Field label="Status">
          <select name="kind" value={f.kind} onChange={set("kind")}>
            {KINDS.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </Field>
        <Field label="URL (once published)" className={styles.full}>
          <input name="url" value={f.url} onChange={set("url")} />
        </Field>
        <Field label="Inbound it generated (people, DMs, comments worth following)" className={styles.full}>
          <input name="inbound" value={f.inbound} onChange={set("inbound")} />
        </Field>
        <Field label="Notes" className={styles.full}>
          <textarea name="notes" rows={2} value={f.notes} onChange={set("notes")} />
        </Field>
        <div className={`${styles.full} row`}>
          <Button type="submit" variant="success" busy={save.isPending}>
            Save
          </Button>
          {item && (
            <Button variant="danger" busy={del.isPending} onClick={() => remove(item.id)}>
              Delete
            </Button>
          )}
        </div>
      </form>
    </Drawer>
  );
}
