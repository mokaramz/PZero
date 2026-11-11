import { useState } from "react";

import { Button, Callout } from "@/components/ui";
import { useAction } from "@/lib/hooks";
import { DEBRIEF, DEBRIEF_KEYS, LABEL, refusedLeadOf, type DebriefResult } from "../api";
import styles from "../Events.module.css";

type Pair = { name: string; note: string; url?: string };
const blank = (n: number): Pair[] => Array.from({ length: n }, () => ({ name: "", note: "" }));
const blankLeads = (n: number): Pair[] => Array.from({ length: n }, () => ({ name: "", note: "", url: "" }));
const LEAD_URL = "Evidence URL (optional — the event's URL is used otherwise)";

/**
 * After attending: people met become Person records (event as source), startup leads land in Deal Flow as
 * pre-company candidates (v1 openDebrief / saveDebrief → POST event_debrief). Review 016: each startup lead may carry
 * its own public evidence URL (else the event's URL is the evidence); a lead with neither is refused — nothing is
 * saved — and the reason is shown at that lead's row.
 */
export function DebriefForm({ eventId, onDone }: { eventId: string; onDone: () => void }) {
  const [people, setPeople] = useState<Pair[]>(blank(5));
  const [leads, setLeads] = useState<Pair[]>(blankLeads(3));
  const [notes, setNotes] = useState("");
  const [refused, setRefused] = useState<{ row: number; message: string } | null>(null);
  const save = useAction<object, DebriefResult>(DEBRIEF, {
    invalidates: DEBRIEF_KEYS,
    label: LABEL.debrief,
    success: (r) => `${r.people.length} people added, ${r.leads} startup leads → Deal Flow`,
  });

  const submit = async () => {
    setRefused(null);
    const sent = leads.map((l, row) => ({ l, row })).filter(({ l }) => l.name.trim());
    const r = await save
      .mutateAsync({
        id: eventId,
        people_met: people.filter((p) => p.name.trim()).map((p) => ({ name: p.name, note: p.note })),
        leads: sent.map(({ l }) => ({ name: l.name, desc: l.note, url: l.url ?? "" })),
        notes,
      })
      .catch((err: unknown) => {
        const x = refusedLeadOf(err);
        const at = x ? sent[x.index] : undefined;
        if (x && at) setRefused({ row: at.row, message: x.message });
        return null;
      });
    if (r) onDone();
  };

  const grid = (rows: Pair[], set: (r: Pair[]) => void, a: (i: number) => string, b: string, prefix: string) => (
    <div className={styles.pairGrid}>
      {rows.map((r, i) => (
        <div key={i} className={styles.pairRow}>
          <input
            aria-label={`${a(i + 1)}`}
            placeholder={a(i + 1)}
            value={r.name}
            name={`${prefix}${i + 1}n`}
            onChange={(e) => set(rows.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
          />
          <input
            aria-label={`${a(i + 1)} — ${b}`}
            placeholder={b}
            value={r.note}
            name={`${prefix}${i + 1}w`}
            onChange={(e) => set(rows.map((x, j) => (j === i ? { ...x, note: e.target.value } : x)))}
          />
          {r.url !== undefined && (
            <input
              aria-label={`${a(i + 1)} — ${LEAD_URL}`}
              placeholder={LEAD_URL}
              value={r.url}
              name={`${prefix}${i + 1}u`}
              className={styles.fullCol}
              inputMode="url"
              onChange={(e) => set(rows.map((x, j) => (j === i ? { ...x, url: e.target.value } : x)))}
            />
          )}
          {refused && r.url !== undefined && refused.row === i && (
            <Callout tone="red" role="alert" className={styles.fullCol} data-testid="debrief-lead-error">
              {refused.message}
            </Callout>
          )}
        </div>
      ))}
    </div>
  );

  return (
    <div className="stack" data-testid="debrief-form">
      <Callout tone="blue">
        <b>The loop: Event → Person → Talent Graph → Founder → Startup.</b> Two minutes, while it's fresh. People become records with the event as
        source; startup leads land in your Deal Flow as pre-company candidates.
      </Callout>
      <div>
        <b>People met</b> <span className="muted">(name — why interesting)</span>
        {grid(people, setPeople, (i) => `Person ${i}`, "why interesting / what they do", "dp")}
      </div>
      <div>
        <b>Startup leads discovered</b> <span className="muted">(company/team — what they do)</span>
        {grid(leads, setLeads, (i) => `Startup/team ${i}`, "what they do", "dl")}
      </div>
      <label className={styles.block}>
        <b>Notes / promised follow-ups / introductions</b>
        <textarea rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div>
        <Button variant="success" size="lg" busy={save.isPending} onClick={() => void submit()}>
          Save debrief
        </Button>
      </div>
    </div>
  );
}
