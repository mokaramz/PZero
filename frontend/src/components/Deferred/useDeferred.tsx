import { useId, type SyntheticEvent } from "react";

import styles from "./Deferred.module.css";

const inert = (e: SyntheticEvent) => {
  e.preventDefault();
  e.stopPropagation();
};

/**
 * An entry point that is not ported yet (review 009, deviation a — generalised for every view): it stays in place,
 * focusable and named, says why (title + aria-describedby), and does nothing — a click, Enter or Space never reaches a
 * handler, so it can never send a request. Spread `props` on the control (merge `className`) and render `note` next
 * to it.
 */
export function useDeferred(reason: string) {
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
