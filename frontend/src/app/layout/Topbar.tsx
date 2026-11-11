import { Icon } from "@/components/Icon";
import { cx } from "@/lib/format";
import { ROLE } from "@/lib/roles";
import styles from "./Layout.module.css";

type TopbarProps = {
  focus: boolean;
  onToggleFocus: () => void;
  dark: boolean;
  onToggleTheme: () => void;
  /** narrow screens: opens / closes the rail drawer */
  onToggleNav: () => void;
  onOpenSearch: () => void;
};

/** The sticky header: menu (narrow), the search field that opens the palette, focus mode, theme, release, operator. */
export function Topbar({ focus, onToggleFocus, dark, onToggleTheme, onToggleNav, onOpenSearch }: TopbarProps) {
  return (
    <header className={styles.topbar}>
      <button type="button" className={styles.menuBtn} onClick={onToggleNav} aria-label="Toggle navigation">
        <Icon name="list" size={18} />
      </button>
      <button type="button" className={styles.search} onClick={onOpenSearch} aria-label="Search">
        <Icon name="search" size={15} />
        <span className={styles.searchText}>Search companies, people, topics…</span>
        <kbd>Ctrl K</kbd>
      </button>
      <span className="grow" />
      <button
        type="button"
        className={cx(styles.focusBtn, focus && styles.focusOn)}
        onClick={onToggleFocus}
        aria-pressed={focus}
        title={focus ? "Leave focus mode (F)" : "Focus mode — hide the navigation (F)"}
        data-testid="focus-mode"
      >
        <Icon name="focus" size={15} />
        <span className={styles.focusLabel}>{focus ? "Leave focus" : "Focus"}</span>
      </button>
      <ThemeSwitch dark={dark} onToggle={onToggleTheme} />
      <span className={styles.who}>
        <span className={styles.release}>v2</span> · Taste Map v2.2 · data stays local
      </span>
      <span className={styles.operator} title={`${ROLE.operator} — the final human decision owner`} aria-label={ROLE.operator}>
        SO
      </span>
    </header>
  );
}

/** sun · track · moon; navy marks "on" (dark). */
function ThemeSwitch({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={dark}
      aria-label="Dark mode"
      className={styles.themeSwitch}
      onClick={onToggle}
      title={dark ? "Switch to light mode" : "Switch to dark mode"}
      data-testid="theme-toggle"
    >
      <Icon name="sun" size={13} className={styles.themeIcon} />
      <span className={styles.themeTrack} aria-hidden>
        <span className={styles.themeThumb} />
      </span>
      <Icon name="moon" size={13} className={styles.themeIcon} />
    </button>
  );
}
