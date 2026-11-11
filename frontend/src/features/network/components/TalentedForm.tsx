import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui";
import { useAction } from "@/lib/hooks";
import { NETWORK_KEYS, TALENTED, type TalentedResult } from "../api";
import { firstName } from "../model/peopleUtil";
import type { Person, TalentedBody } from "../model/types";
import styles from "../Network.module.css";

type Row = { name: string; note: string };

const empty = (): Row[] => [
  { name: "", note: "" },
  { name: "", note: "" },
  { name: "", note: "" },
];

/**
 * The ritual: "Who are the three most talented people you know?" — each answer becomes a linked person with the
 * chain preserved (POST network/talented). `inline` is the compact profile version, `ritual` the drawer version.
 */
export function TalentedForm({ person, variant, onDone }: { person: Person; variant: "inline" | "ritual"; onDone?: () => void }) {
  const toast = useToast();
  const [rows, setRows] = useState<Row[]>(empty);
  const save = useAction<TalentedBody, TalentedResult>(TALENTED, {
    invalidates: NETWORK_KEYS,
    label: "Creating linked people",
    success: (r) => `${r.created.length} people created & linked`,
  });

  const submit = async () => {
    const persons = rows.filter((x) => x.name.trim());
    if (!persons.length) {
      toast.show("Enter at least one name", "error");
      return;
    }
    const r = await save.mutateAsync({ id: person.id, persons }).catch(() => null);
    if (!r) return;
    setRows(empty());
    onDone?.();
  };

  const set = (i: number, k: keyof Row, v: string) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const inline = variant === "inline";

  return (
    <div className={inline ? undefined : styles.ritual} data-testid={inline ? "talented-inline" : "talented-ritual"}>
      {!inline && (
        <p>
          <b>The ritual: "Who are the three most talented people you know?"</b>
          <br />
          Log {person.name}'s answers - each becomes a linked person with the chain preserved.
        </p>
      )}
      <div className={styles.pairGrid}>
        {rows.map((r, i) => {
          const namePh = inline ? (i === 0 ? `Ask ${firstName(person.name)}: person 1` : `person ${i + 1}`) : `Person ${i + 1} - name`;
          const whyPh = inline ? (i === 0 ? "why talented" : "why") : "why talented (optional)";
          return (
            <div key={i} className={styles.pairRow}>
              <input aria-label={namePh} placeholder={namePh} value={r.name} onChange={(e) => set(i, "name", e.target.value)} />
              <input aria-label={`${namePh} — ${whyPh}`} placeholder={whyPh} value={r.note} onChange={(e) => set(i, "note", e.target.value)} />
            </div>
          );
        })}
      </div>
      <Button variant={inline ? "default" : "primary"} busy={save.isPending} onClick={() => void submit()}>
        {inline ? "Create linked people" : "Create the three linked people"}
      </Button>
    </div>
  );
}
