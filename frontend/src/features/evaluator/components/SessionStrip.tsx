/** The sessions strip: one card per evaluation (the old `session_row`), the selected one outlined; the empty line names
 *  the two ways to start one. */
import { Badge } from "@/components/ui";
import { cx } from "@/lib/format";
import { rowLine } from "../model/view";
import type { SessionRow } from "../model/types";
import styles from "../Evaluator.module.css";

export function SessionStrip({ sessions, selected, onSelect }: { sessions: SessionRow[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <div className={styles.sessions} role="list" aria-label="Evaluations" data-testid="eval-sessions">
      {sessions.length ? (
        sessions.map((s) => (
          <button
            type="button"
            role="listitem"
            key={s.id}
            className={cx(styles.session, selected === s.id && styles.sessionSel)}
            onClick={() => onSelect(s.id)}
            aria-current={selected === s.id || undefined}
            data-session={s.id}
          >
            <div>
              <b>{s.subject.name || "UNKNOWN"}</b> <Badge tone={s.status === "ended" ? "neutral" : "blue"}>{s.status}</Badge>
            </div>
            <div className={styles.sub} title="ledger items = founder-reported claims + deck claims + UNKNOWNs + contradictions + evidence-backed claims">
              {rowLine(s)}
              {s.contradictions ? <span className={styles.red}> · {s.contradictions} contradiction(s)</span> : null}
            </div>
            <div className={styles.sub}>{s.created}</div>
          </button>
        ))
      ) : (
        <div className={styles.sessionsEmpty}>
          No evaluation yet. Start one from a Conviction company (<b>Start Active Evaluator</b>) or <b>New external evaluation</b>.
        </div>
      )}
    </div>
  );
}
