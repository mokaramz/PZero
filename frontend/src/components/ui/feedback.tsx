import type { ReactNode } from "react";

import { cx } from "@/lib/format";
import { Button } from "./Button";
import { Callout } from "./surfaces";
import styles from "./ui.module.css";

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className={styles.loading} role="status">
      <span className={styles.spinner} aria-hidden />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx(styles.empty, className)}>{children}</div>;
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <Callout tone="red" role="alert">
      <div className="row">
        <span className="grow">{msg}</span>
        {onRetry && (
          <Button size="sm" onClick={onRetry}>
            Retry
          </Button>
        )}
      </div>
    </Callout>
  );
}

/** The part of a react-query result that Async reads. */
export type AsyncQuery<T> = { data?: T; error: unknown; isLoading: boolean; refetch: () => unknown };

/** Renders loading / error / content for a react-query result. */
export function Async<T>({ q, children, label }: { q: AsyncQuery<T>; children: (d: T) => ReactNode; label?: string }) {
  if (q.isLoading) return <Spinner label={label} />;
  if (q.error) return <ErrorBox error={q.error} onRetry={() => q.refetch()} />;
  if (q.data === undefined) return null;
  return <>{children(q.data)}</>;
}
