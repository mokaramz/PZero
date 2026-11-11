import { useId, type SyntheticEvent } from "react";

import type { NotPortedReason } from "../model/deferred";
import styles from "../DealFlow.module.css";

const inert = (e: SyntheticEvent) => {
  e.preventDefault();
  e.stopPropagation();
};

/**
 * An entry point that is not ported yet: it stays in place, focusable and named, says why (title + aria-describedby),
 * and does nothing — a click, Enter or Space never reaches a handler, so it can never send a request.
 * Spread `props` on the control (merge `className`) and render `note` next to it.
 */
export function useDeferred(reason: NotPortedReason) {
  const id = useId();
  return {
    props: {
      "aria-disabled": true,
      title: reason,
      "aria-describedby": id,
      "data-deferred": "",
      className: styles.off,
      onClick: inert,
    },
    note: (
      <span id={id} className="sr-only">
        {reason}
      </span>
    ),
  } as const;
}
