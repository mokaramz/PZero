import { useState, type ReactNode } from "react";

import styles from "./focus.module.css";

export type CappedProps = {
  items: ReactNode[];
  /** how many are shown before "+ N more" (default 3) */
  max?: number;
  /** the word after the count ("+ 2 more") */
  more?: string;
  render?: (x: ReactNode, i: number) => ReactNode;
  /** shown (as a quiet line) when there are no items */
  empty?: ReactNode;
};

/** A list shown capped (default 3); the remainder is one click away, never dropped. */
export function Capped({ items, max = 3, more = "more", render, empty }: CappedProps) {
  const [open, setOpen] = useState(false);
  if (!items.length) return empty ? <p className={styles.empty}>{empty}</p> : null;
  const shown = open ? items : items.slice(0, max);
  return (
    <>
      <ul className={styles.list}>
        {shown.map((x, i) => (
          <li key={i}>{render ? render(x, i) : x}</li>
        ))}
      </ul>
      {items.length > max && (
        <button type="button" className={styles.moreBtn} onClick={() => setOpen(!open)} aria-expanded={open}>
          {open ? "Show less" : `+ ${items.length - max} ${more}`}
        </button>
      )}
    </>
  );
}
