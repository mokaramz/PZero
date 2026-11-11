import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import { Icon } from "../Icon";
import styles from "./attention.module.css";

export type ContextInspectorProps = {
  /** accessible name of the aside ("Candidate detail"); the close button says "Close <label>" */
  label: string;
  children?: ReactNode;
  /** shown when nothing is selected (no children) */
  empty?: ReactNode;
  /** adds a close button while something is selected */
  onClose?: () => void;
  className?: string;
  testId?: string;
};

/** Layer 2: the selected item's context, on the right, on demand — never a modal, never a blur. On narrow screens it
 *  stacks under the list. */
export function ContextInspector({ label, children, empty, onClose, className, testId }: ContextInspectorProps) {
  return (
    <aside className={cx(styles.inspector, className)} aria-label={label} data-inspector data-testid={testId ?? "context-inspector"}>
      {onClose && children && (
        <button type="button" className={styles.inspectorClose} onClick={onClose} aria-label={`Close ${label.toLowerCase()}`}>
          <Icon name="close" size={14} />
        </button>
      )}
      {children ?? <p className={styles.inspectorEmpty}>{empty ?? "Select an item to see its context."}</p>}
    </aside>
  );
}
