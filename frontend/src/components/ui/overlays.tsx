import { useEffect, useId, useRef, type ReactNode } from "react";

import { cx } from "@/lib/format";
import { Button } from "./Button";
import { useEscape } from "./useEscape";
import styles from "./ui.module.css";

type OverlayProps = {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  width?: number;
};

/** A right-hand panel over the page (role=dialog). Escape or a click on the backdrop closes it. */
export function Drawer({ open, onClose, title, actions, children, width = 880 }: OverlayProps & { actions?: ReactNode }) {
  useEscape(open, onClose);
  const id = useId();
  if (!open) return null;
  return (
    <div className={styles.overlay} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className={styles.drawer} style={{ width: `min(${width}px, 100vw)` }} role="dialog" aria-modal aria-labelledby={id}>
        <header className={styles.drawerHead}>
          <h2 id={id}>{title}</h2>
          <div className="row">
            {actions}
            <Button variant="ghost" onClick={onClose} aria-label="Close">
              ✕
            </Button>
          </div>
        </header>
        <div className={styles.drawerBody}>{children}</div>
      </aside>
    </div>
  );
}

/** A centred dialog; it takes focus when it opens. Escape or a click on the backdrop closes it. */
export function Modal({ open, onClose, title, children, footer, width = 640 }: OverlayProps & { footer?: ReactNode }) {
  useEscape(open, onClose);
  const id = useId();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) ref.current?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <div className={cx(styles.overlay, styles.overlayCenter)} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        ref={ref}
        tabIndex={-1}
        className={styles.modal}
        style={{ width: `min(${width}px, calc(100vw - 32px))` }}
        role="dialog"
        aria-modal
        aria-labelledby={id}
      >
        <header className={styles.drawerHead}>
          <h2 id={id}>{title}</h2>
          <Button variant="ghost" onClick={onClose} aria-label="Close">
            ✕
          </Button>
        </header>
        <div className={styles.modalBody}>{children}</div>
        {footer && <footer className={styles.modalFoot}>{footer}</footer>}
      </div>
    </div>
  );
}
