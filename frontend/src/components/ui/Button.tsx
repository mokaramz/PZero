import { useEffect, useState, type ButtonHTMLAttributes } from "react";

import { cx } from "@/lib/format";
import styles from "./ui.module.css";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "success" | "danger" | "ghost";
  size?: "sm" | "md" | "lg";
  /** shows a small spinner and disables the button while the action runs */
  busy?: boolean;
};

export function Button({ variant = "default", size = "md", busy, className, children, disabled, type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(styles.btn, styles[`btn_${variant}`], styles[`btn_${size}`], className)}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {busy && <span className={styles.spinnerSm} aria-hidden />}
      {children}
    </button>
  );
}

const ARM_MS = 6000;

/** Two-step button for actions that change TRUSTED state (confirm an outcome, promote a source): the first click arms
 *  it and says what will happen, the second click within 6 s does it. Routine actions never use this. */
export function ConfirmButton({
  confirmText,
  onConfirm,
  children,
  ...rest
}: Omit<ButtonProps, "onClick"> & { confirmText: string; onConfirm: () => void }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = window.setTimeout(() => setArmed(false), ARM_MS);
    return () => window.clearTimeout(t);
  }, [armed]);
  return (
    <Button
      {...rest}
      data-armed={armed || undefined}
      onClick={() => {
        if (armed) {
          setArmed(false);
          onConfirm();
        } else setArmed(true);
      }}
    >
      {armed ? `Click again to confirm — ${confirmText}` : children}
    </Button>
  );
}
