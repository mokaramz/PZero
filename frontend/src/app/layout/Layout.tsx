import { Suspense, useCallback, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { Spinner } from "@/components/ui";
import { CatchUpBanner } from "@/features/jobs/CatchUpBanner";
import { cx } from "@/lib/format";
import { ActivityDock } from "../ActivityDock";
import { CommandPalette } from "../CommandPalette";
import { ErrorBoundary } from "../ErrorBoundary";
import { Rail } from "./Rail";
import { Topbar } from "./Topbar";
import { useLegacyHashRedirect } from "./useLegacyHashRedirect";
import { useShellShortcuts } from "./useShellShortcuts";
import { useStoredFlag } from "./useStoredFlag";
import { useTheme } from "./useTheme";
import styles from "./Layout.module.css";

/** Remembered per browser (localStorage). */
export const COMPACT_KEY = "pz.rail.compact";
export const FOCUS_KEY = "pz.focus";

/**
 * The app shell: navigation rail, top bar, catch-up banner, the routed view (inside an error boundary keyed by the
 * pathname and a Suspense for lazy pages), the background activity dock and the Ctrl+K palette.
 * FOCUS MODE (desktop): the rail and secondary chrome step aside; "F" toggles it.
 */
export function Layout() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [compact, toggleCompact] = useStoredFlag(COMPACT_KEY);
  const [focus, toggleFocus] = useStoredFlag(FOCUS_KEY);
  const [dark, toggleTheme] = useTheme();
  const location = useLocation();
  // narrow screens: the rail is a drawer; moving to another page closes it (adjusted during render, not in an effect)
  const [navOpen, setNavOpen] = useState(false);
  const [navPath, setNavPath] = useState(location.pathname);
  if (navPath !== location.pathname) {
    setNavPath(location.pathname);
    setNavOpen(false);
  }

  const openPalette = useCallback(() => setPaletteOpen(true), []);
  useShellShortcuts({ onFocusKey: toggleFocus, onSearchKey: openPalette });
  useLegacyHashRedirect();

  return (
    <div className={cx(styles.app, compact && styles.compact, focus && styles.focusMode)} data-focus-mode={focus || undefined}>
      <Rail compact={compact} open={navOpen} onToggleCompact={toggleCompact} />

      <div className={styles.main}>
        <Topbar
          focus={focus}
          onToggleFocus={toggleFocus}
          dark={dark}
          onToggleTheme={toggleTheme}
          onToggleNav={() => setNavOpen((v) => !v)}
          onOpenSearch={openPalette}
        />
        <CatchUpBanner />
        <main className={styles.content}>
          <ErrorBoundary key={location.pathname}>
            <Suspense fallback={<Spinner />}>
              <div className="pz-page">
                <Outlet />
              </div>
            </Suspense>
          </ErrorBoundary>
        </main>
        {!focus && <ActivityDock />}
      </div>

      {navOpen && <div className={styles.scrim} onClick={() => setNavOpen(false)} />}
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
