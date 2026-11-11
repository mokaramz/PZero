import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "@/lib/format";
import type { Tone } from "./Badge";
import styles from "./ui.module.css";

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx(styles.card, className)} {...rest} />;
}

export type PanelProps = Omit<HTMLAttributes<HTMLElement>, "title"> & { title?: ReactNode; aside?: ReactNode };

/** A titled section: a quiet header band (title + optional right-hand aside) over the body. */
export function Panel({ title, aside, children, className, ...rest }: PanelProps) {
  return (
    <section className={cx(styles.panel, className)} {...rest}>
      {(title || aside) && (
        <header className={styles.panelHead}>
          <h3>{title}</h3>
          {aside && <div className={styles.panelAside}>{aside}</div>}
        </header>
      )}
      <div className={styles.panelBody}>{children}</div>
    </section>
  );
}

export function Callout({ tone = "blue", className, ...rest }: HTMLAttributes<HTMLDivElement> & { tone?: Tone }) {
  return <div className={cx(styles.callout, styles[`callout_${tone}`], className)} {...rest} />;
}
