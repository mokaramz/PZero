import { useState } from "react";

import { Button, Callout, Drawer, Field } from "@/components/ui";
import { useCopy } from "@/lib/hooks";
import { useWeekly } from "../api";
import styles from "../Conviction.module.css";

/** v1 openWeekly/genWeekly — POST weekly {insight, question} → {text}, with a Copy button. */
export function WeeklyDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [insight, setInsight] = useState("");
  const [question, setQuestion] = useState("");
  const gen = useWeekly();
  const copy = useCopy();
  return (
    <Drawer open={open} onClose={onClose} title="Weekly Sourcing Update" width={760}>
      <Callout tone="blue">
        Assembled from real activity this week (found, sent, pipeline moves, people added). No filler - if nothing cleared the bar, it says so honestly.
      </Callout>
      <div className={styles.inputs}>
        <Field label={<b>Optional: one sourcing insight</b>}>
          <input value={insight} onChange={(e) => setInsight(e.target.value)} />
        </Field>
        <Field label={<b>Optional: one question for Manager</b>}>
          <input value={question} onChange={(e) => setQuestion(e.target.value)} />
        </Field>
      </div>
      <Button variant="primary" busy={gen.isPending} onClick={() => gen.mutate({ insight, question })}>
        Generate
      </Button>
      {gen.data && (
        <>
          <pre className={styles.weeklyOut} data-testid="weekly-text">
            {gen.data.text}
          </pre>
          <Button onClick={() => copy(gen.data.text)}>Copy</Button>
        </>
      )}
    </Drawer>
  );
}
