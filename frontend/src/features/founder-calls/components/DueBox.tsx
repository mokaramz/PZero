import { Button } from "@/components/ui";
import type { Call } from "../model/types";
import { DueTag } from "./bits";
import styles from "../FounderCalls.module.css";

/** Due follow-ups: overdue, due today and due soon, each with Mark done. */
export function DueBox({ rows, onOpen, onDone }: { rows: Call[]; onOpen: (id: string) => void; onDone: (id: string) => void }) {
  return (
    <section className={styles.dueBox} data-testid="calls-due" aria-label="Due follow-ups">
      <h3 className={styles.boxHead}>Due follow-ups</h3>
      <div className={styles.boxBody}>
        {rows.length ? (
          rows.map((r) => (
            <div key={r.id} className={styles.dueRow} data-testid="due-row">
              <DueTag state={r.due_state} />
              <button type="button" className={styles.nameBtn} onClick={() => onOpen(r.id)}>
                {r.founder_name}
              </button>
              <span className={styles.sub}>{r.company_name}</span>
              <span>{r.next_action?.text ?? ""}</span>
              <span className={styles.sub}>
                {r.next_action?.owner ?? ""}
                {r.next_action?.due ? ` · due ${r.next_action.due}` : ""}
              </span>
              <span className="grow" />
              <Button size="sm" onClick={() => onDone(r.id)}>
                Mark done
              </Button>
            </div>
          ))
        ) : (
          <span className={styles.sub}>No follow-ups due. Every next action with a date shows here when it is due.</span>
        )}
      </div>
    </section>
  );
}
