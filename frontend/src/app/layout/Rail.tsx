import { NavLink } from "react-router-dom";

import { Icon } from "@/components/Icon";
import { Logo } from "@/components/Logo";
import { cx } from "@/lib/format";
import { NAV } from "../nav";
import styles from "./Layout.module.css";

type RailProps = {
  /** icons with tooltips (desktop) */
  compact: boolean;
  /** open as a drawer (narrow screens) */
  open: boolean;
  onToggleCompact: () => void;
};

/** The left navigation rail: brand, the nav sections, the collapse toggle. Its own scroll owner, always reachable. */
export function Rail({ compact, open, onToggleCompact }: RailProps) {
  return (
    <aside className={cx(styles.rail, open && styles.railOpen)} aria-label="Main navigation">
      <div className={styles.brand}>
        <span className={styles.brandMark}>
          <Logo size={26} />
        </span>
        <div className={styles.brandText}>
          <div className={styles.brandName}>Project Zero</div>
          <div className={styles.brandSub}>VC scouting &amp; intelligence</div>
        </div>
      </div>
      <nav className={styles.nav}>
        {NAV.map((section) => (
          <div key={section.title ?? "top"} className={styles.section}>
            {section.title && <div className={styles.sectionTitle}>{section.title}</div>}
            {section.items.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === "/"}
                className={({ isActive }) => cx(styles.navItem, isActive && styles.navItemOn)}
                data-view={item.legacyView}
                title={compact ? item.label : undefined}
                aria-label={compact ? item.label : undefined}
              >
                <Icon name={item.icon} size={16} />
                <span className={styles.navLabel}>{item.label}</span>
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <button
        type="button"
        className={styles.collapse}
        onClick={onToggleCompact}
        aria-pressed={compact}
        title={compact ? "Expand the navigation" : "Collapse the navigation"}
      >
        <Icon name={compact ? "chevron" : "chevronLeft"} size={14} />
        <span className={styles.navLabel}>Collapse</span>
      </button>
    </aside>
  );
}
