import { useState, type ReactNode } from "react";

import { cx } from "@/lib/format";
import { Icon } from "../Icon";
import styles from "./attention.module.css";

export type GroupedFiltersProps = {
  /** PRIMARY VIEW — the scope (role=group "View") */
  view?: ReactNode;
  /** ATTENTION — the 2–4 everyday filters (role=group "Attention") */
  attention: ReactNode;
  /** MORE FILTERS — everything else, collapsed behind one button */
  more?: ReactNode;
  /** label of the active filter(s) inside More (shown on the closed button) */
  activeMore?: string;
  testId?: string;
  /** no padding / rule — for filters that sit on the canvas rather than inside a panel */
  flush?: boolean;
};

/**
 * Filters by purpose: PRIMARY VIEW (the scope) · ATTENTION (2–4 everyday filters) · MORE FILTERS (everything else,
 * collapsed). When the active filter lives under More, it is still named on the closed button — state is never hidden.
 */
export function GroupedFilters({ view, attention, more, activeMore, testId, flush }: GroupedFiltersProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className={cx(styles.filters, flush && styles.flush)} data-testid={testId ?? "grouped-filters"}>
      <div className={styles.filterRow}>
        {view && (
          <div className={styles.filterView} role="group" aria-label="View">
            {view}
          </div>
        )}
        <div className={styles.filterAttention} role="group" aria-label="Attention">
          {attention}
        </div>
        {more && (
          <button
            type="button"
            className={cx(styles.moreFilters, (open || activeMore) && styles.moreFiltersOn)}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            data-testid="more-filters"
          >
            <Icon name="filter" size={13} />
            {activeMore ? <span>More filters · {activeMore}</span> : <span>More filters</span>}
            <Icon name="chevron" size={12} className={cx(styles.moreChevron, open && styles.moreChevronOpen)} />
          </button>
        )}
      </div>
      {more && open && (
        <div className={cx(styles.morePanelInline, "pz-reveal")} data-testid="more-filters-panel">
          {more}
        </div>
      )}
    </div>
  );
}
