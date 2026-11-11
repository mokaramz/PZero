import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import { Icon } from "../Icon";
import { Capped } from "./Capped";
import { Kicker } from "./Kicker";
import { MoveButton, type Move } from "./MoveButton";
import styles from "./focus.module.css";

export type DecisionCardProps = {
  why: ReactNode[];
  risks: ReactNode[];
  unknowns: ReactNode[];
  pzView: ReactNode;
  move: Move | null;
  /** the decision buttons, shown with the move */
  decisions?: ReactNode;
  /** anything below the card body */
  extra?: ReactNode;
  testId?: string;
  /** small heading of the card (default "PZ Review") */
  title?: ReactNode;
  /** quiet right-hand element of the heading (e.g. a score) */
  aside?: ReactNode;
  /** "editorial" (opt-in, Deal Flow): key takeaways with a slim navy edge, risk | unknown side by side, PZ view | your
   *  move side by side — same content, same move. Every other caller keeps the default look. */
  variant?: "default" | "editorial";
};

/** On screen: max 2 reasons, 1 risk, 1 unknown — the rest behind "N more". */
const CAP = { why: 2, risks: 1, unknowns: 1 } as const;
const EMPTY = { why: "No reason on record yet.", risks: "None on record.", unknowns: "Nothing open." } as const;

/** LEVEL 1 — the decision card (the core of the product). Why it matters · Biggest risk · Top unknown; PZ VIEW as an
 *  investment judgment; YOUR MOVE as the strongest operational element with ONE primary action. */
export function DecisionCard(props: DecisionCardProps) {
  return props.variant === "editorial" ? <EditorialCard {...props} /> : <DefaultCard {...props} />;
}

function CardHead({ title = "PZ Review", aside, editorial }: { title?: ReactNode; aside?: ReactNode; editorial?: boolean }) {
  return (
    <header className={styles.decisionHead}>
      <h3 className={cx(styles.decisionTitle, editorial && styles.edTitle)}>{title}</h3>
      {aside && <span className={styles.decisionAside}>{aside}</span>}
    </header>
  );
}

/** Three quiet tonal cells, the PZ view row and the move row. */
function DefaultCard({ why, risks, unknowns, pzView, move, decisions, extra, testId, title, aside }: DecisionCardProps) {
  return (
    <section className={styles.decision} aria-label="Operator view" data-testid={testId ?? "operator-view"}>
      <CardHead title={title} aside={aside} />
      <div className={styles.cells}>
        <div className={styles.cell} data-tone="why">
          <Kicker>
            <Icon name="trend" size={14} /> Why it matters
          </Kicker>
          <Capped items={why} max={CAP.why} more="more" empty={EMPTY.why} />
        </div>
        <div className={styles.cell} data-tone="risk">
          <Kicker tone="risk">
            <Icon name="warning" size={14} /> Biggest risk
          </Kicker>
          <Capped items={risks} max={CAP.risks} more="more" empty={EMPTY.risks} />
        </div>
        <div className={styles.cell} data-tone="unknown">
          <Kicker>
            <Icon name="question" size={14} /> Top unknown
          </Kicker>
          <Capped items={unknowns} max={CAP.unknowns} more="more" empty={EMPTY.unknowns} />
        </div>
      </div>
      <div className={styles.pzRow}>
        <span className={styles.pzLabel}>
          <Icon name="signal" size={15} /> PZ view
        </span>
        <div className={styles.pzState}>{pzView}</div>
      </div>
      {move && (
        <div className={styles.moveRow}>
          <div className={styles.moveLead}>
            <span className={styles.moveLabel}>Your move</span>
            <div className={styles.moveText}>{move.why ?? move.label}</div>
            {move.detail && <div className={styles.moveDetail}>{move.detail}</div>}
          </div>
          {move.label && <MoveButton move={move} />}
          {decisions && <div className={styles.decisionsRow}>{decisions}</div>}
        </div>
      )}
      {extra}
    </section>
  );
}

/** Key takeaways, risk | unknown, PZ view | your move (Deal Flow). */
function EditorialCard({ why, risks, unknowns, pzView, move, decisions, extra, testId, title, aside }: DecisionCardProps) {
  return (
    <section className={cx(styles.decision, styles.ed)} aria-label="Operator view" data-testid={testId ?? "operator-view"} data-variant="editorial">
      <CardHead title={title} aside={aside} editorial />
      <div className={styles.edTakeaways}>
        <span className={styles.edLabel}>Key takeaways</span>
        <Capped items={why} max={CAP.why} more="more" empty={EMPTY.why} />
      </div>
      <div className={styles.edPair}>
        <div className={styles.edCell} data-tone="risk">
          <span className={styles.edLabel}>
            <Icon name="warning" size={12} /> Biggest risk
          </span>
          <Capped items={risks} max={CAP.risks} more="more" empty={EMPTY.risks} />
        </div>
        <div className={styles.edCell} data-tone="unknown">
          <span className={styles.edLabel}>
            <Icon name="question" size={12} /> Top unknown
          </span>
          <Capped items={unknowns} max={CAP.unknowns} more="more" empty={EMPTY.unknowns} />
        </div>
      </div>
      <div className={styles.edPair}>
        <div className={styles.edView}>
          <span className={styles.edLabel}>PZ view</span>
          <div className={styles.edViewText}>{pzView}</div>
        </div>
        {move && (
          <div className={styles.edMove}>
            <span className={styles.edLabel}>Your move</span>
            <div className={styles.edMoveText}>{move.why ?? move.label}</div>
            {move.detail && <div className={styles.moveDetail}>{move.detail}</div>}
            {move.label && <MoveButton move={move} className={styles.edMoveBtn} />}
          </div>
        )}
      </div>
      {move && decisions && <div className={styles.decisionsRow}>{decisions}</div>}
      {extra}
    </section>
  );
}
