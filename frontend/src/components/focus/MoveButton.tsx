import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useDeferred } from "@/components/Deferred";
import { cx } from "@/lib/format";
import styles from "./focus.module.css";

/** The operator's next move: a link (`to`) or an action (`onClick`). */
export type Move = {
  label: string;
  to?: string;
  onClick?: () => void;
  /** the move as a sentence (shown instead of the label when present) */
  why?: ReactNode;
  /** one short line under the move (e.g. why this move, when it is due) */
  detail?: ReactNode;
  busy?: boolean;
  testId?: string;
  /** the move's action is not ported yet: the button stays in place, disabled with this reason (see `useDeferred`) */
  deferred?: string;
};

/** The one primary action of a decision card (filled navy). */
export function MoveButton({ move, className }: { move: Move; className?: string }) {
  if (move.deferred) return <DeferredMove move={move} reason={move.deferred} className={className} />;
  if (move.to)
    return (
      <Link className={cx(styles.moveBtn, className)} to={move.to} data-testid={move.testId}>
        {move.label}
      </Link>
    );
  return (
    <button type="button" className={cx(styles.moveBtn, className)} onClick={move.onClick} disabled={move.busy} data-testid={move.testId}>
      {move.label}
    </button>
  );
}

function DeferredMove({ move, reason, className }: { move: Move; reason: string; className?: string }) {
  const d = useDeferred(reason);
  return (
    <>
      <button type="button" {...d.props} className={cx(styles.moveBtn, d.props.className, className)} data-testid={move.testId}>
        {move.label}
      </button>
      {d.note}
    </>
  );
}
