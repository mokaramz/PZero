/** The small Founder Radar pieces the cards and drawers share: band pills, UNKNOWN, text-link buttons, external links. */
import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import { NEI } from "../model/logic";
import styles from "../FounderRadar.module.css";

export function Pill({ tone, children, title }: { tone: "hi" | "mid" | "lo" | "na"; children: ReactNode; title?: string }) {
  return (
    <span className={cx(styles.pill, styles[`pill_${tone}`])} title={title}>
      {children}
    </span>
  );
}

export function BandPill({ label, value }: { label: string; value?: string }) {
  const v = value || NEI;
  return <Pill tone={v === "HIGH" ? "hi" : v === "MEDIUM" ? "mid" : v === "LOW" ? "lo" : "na"}>{`${label}: ${v}`}</Pill>;
}

/** An access kind as a pill tone. */
export function AccessPill({ kind, children }: { kind?: string; children: ReactNode }) {
  return <Pill tone={kind === "warm" ? "hi" : kind === "cold" ? "lo" : "na"}>{children}</Pill>;
}

export function Unk({ v }: { v?: unknown }) {
  return v && v !== "UNKNOWN" ? <>{String(v)}</> : <span className={styles.unk}>UNKNOWN</span>;
}

/** A text-link button inside a clickable card: the click never reaches the card. */
export function LinkBtn({ onClick, children, title, disabled }: { onClick?: () => void; children: ReactNode; title?: string; disabled?: boolean }) {
  return (
    <button
      type="button"
      className={styles.linkBtn}
      title={title}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
    >
      {children}
    </button>
  );
}

/** An external link (new tab, no referrer). */
export function Ext({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={cx(styles.ext, className)} onClick={(e) => e.stopPropagation()}>
      {children}
    </a>
  );
}

/** One "label: value" line of a card. */
export function Row({ children, sub, tone }: { children: ReactNode; sub?: boolean; tone?: "amber" }) {
  return <div className={cx(styles.row, sub && styles.sub, tone === "amber" && styles.amberText)}>{children}</div>;
}
