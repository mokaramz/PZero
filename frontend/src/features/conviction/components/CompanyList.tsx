import { Monogram } from "@/components/focus";
import { EmptyState } from "@/components/ui";
import { cx } from "@/lib/format";
import { useChanged } from "@/lib/motion";
import { asRole } from "@/lib/roles";
import { currentState, type pipeGroups, type Seg } from "../model/logic";
import type { Signal } from "../model/types";
import styles from "../Conviction.module.css";

type Groups = ReturnType<typeof pipeGroups>;

const TITLES = {
  inv: "Investigate & research",
  watch: "Watch",
  gated: "Conflict-gated · Manager first",
} as const;

/** The left rail: the segment's groups (Investigate · Watch · Conflict-gated), each a list of company rows. */
export function CompanyList({ groups, seg, selected, onSelect }: { groups: Groups; seg: Seg; selected: string | null; onSelect: (slug: string) => void }) {
  const keys = (["inv", "watch", "gated"] as const).filter((k) => seg === "all" || seg === k);
  const shown = keys.filter((k) => groups[k].length);
  return (
    <nav className={styles.list} aria-label="Conviction companies">
      {shown.length === 0 && <EmptyState>No matches.</EmptyState>}
      {shown.map((k) => (
        <div key={k} role="group" aria-label={TITLES[k]}>
          <div className={styles.groupHead}>
            {TITLES[k]} <span className={styles.groupN}>{groups[k].length}</span>
          </div>
          {groups[k].map((e) => (
            <Row key={e.slug} e={e} on={selected === e.slug} onSelect={onSelect} />
          ))}
        </div>
      ))}
    </nav>
  );
}

/** Navigation + fast status scan: name, a quiet verified score, ONE state word, ONE next-action line. */
function Row({ e, on, onSelect }: { e: Signal; on: boolean; onSelect: (slug: string) => void }) {
  const st = currentState(e);
  const changed = useChanged(st.label);
  const next = e.op && e.op.source !== "score band" ? e.op.action : e.next_action;
  return (
    <button type="button" className={cx(styles.item, on && styles.itemOn)} aria-current={on || undefined} onClick={() => onSelect(e.slug)} data-slug={e.slug}>
      <Monogram name={e.company} size={32} />
      <div className={styles.itemBody}>
        <div className={styles.l1}>
          <span className={styles.name}>{e.company}</span>
          <span className={styles.rowScore} data-testid="row-score" title={`Verified ${e.sc.verified} · provisional ${e.sc.provisional}`}>
            {e.sc.verified}
          </span>
        </div>
        <div key={st.label} className={cx(styles.rowState, styles[`st_${st.tone}`], changed && "pz-enter")} data-testid="row-state">
          {st.label}
          {e.sent_to_omar && <span className={styles.rowFaint}> · {e.omar_feedback ? "Manager feedback" : "sent to Manager"}</span>}
        </div>
        {next ? (
          <div className={styles.na} data-testid="row-op">
            → {asRole(next)}
          </div>
        ) : (
          <div className={cx(styles.na, styles.warnText)}>no next action</div>
        )}
      </div>
    </button>
  );
}
