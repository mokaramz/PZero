import { useId, type ReactNode } from "react";

import { useDeferred } from "@/components/Deferred";
import { Button, type ButtonProps } from "@/components/ui";
import { cx } from "@/lib/format";
import { usd, type Mark, type Tone } from "../model/dashboard";
import styles from "../Health.module.css";

/** A status mark: a dot and its words. */
export function St({ m }: { m: Mark | [Tone, string] }) {
  return (
    <span className={cx(styles.st, styles[`st_${m[0]}`])}>
      <i aria-hidden />
      {m[1]}
    </span>
  );
}

export function KV({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl className={styles.kv}>
      {rows.map(([a, b]) => (
        <div key={a} className={styles.kvRow}>
          <dt>{a}</dt>
          <dd>{b ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Kpi({ k, mark, v, f, spark, onClick }: { k: string; mark: Mark; v: ReactNode; f: string[]; spark?: ReactNode; onClick: () => void }) {
  return (
    <button type="button" className={styles.kpi} onClick={onClick} data-testid="health-kpi">
      <span className={styles.kpiK}>{k}</span>
      <St m={mark} />
      <span className={styles.kpiV}>{v}</span>
      {f.filter(Boolean).map((x) => (
        <span key={x} className={styles.kpiF}>
          {x}
        </span>
      ))}
      {spark}
    </button>
  );
}

export function Meter({ label, v, cap, navy }: { label: string; v: number; cap: number | undefined; navy?: boolean }) {
  return (
    <div className={styles.meter}>
      <span>{label}</span>
      <span className={styles.bar} role="img" aria-label={`${label}: ${usd(v, 3)} of ${cap != null ? usd(cap) : "no cap"}`}>
        <i style={{ width: `${cap ? Math.min(100, (100 * v) / cap) : 0}%`, background: navy ? "var(--navy)" : undefined }} />
      </span>
      <span>
        {usd(v, 3)} / {cap != null ? usd(cap, cap < 1 ? 2 : 0) : "—"}
      </span>
    </div>
  );
}

export function StackRow({ label, n, parts }: { label: string; n: string; parts: Array<[string, number, string]> }) {
  return (
    <div className={styles.srow}>
      <span>{label}</span>
      <div className={styles.stack} role="img" aria-label={`${label}: ${parts.map((p) => `${p[1]} ${p[0]}`).join(", ")}`}>
        {parts
          .filter((p) => p[1])
          .map((p) => (
            <i key={p[0]} style={{ flex: p[1], background: p[2] }} title={`${p[1]} ${p[0]}`} />
          ))}
      </div>
      <span className={styles.ms}>{n}</span>
    </div>
  );
}

/** The visible reason of a deferred subsystem or control (decisions d and h). */
export function Reason({ id, children, testId }: { id?: string; children: ReactNode; testId?: string }) {
  return (
    <span id={id} className={styles.ms} data-reason="" data-testid={testId}>
      {children}
    </span>
  );
}

type ControlProps = Omit<ButtonProps, "onClick" | "disabled" | "busy" | "aria-describedby"> & { reason: string; testId?: string };

/**
 * An action control that is not ported yet (decision h): same place, label and look, disabled through the shared
 * `useDeferred` (focusable, named, a click, Enter or Space never reaches a handler, so no navigation and no request),
 * and described by the VISIBLE reason note `noteId` (the desk's Review queue pattern, 031a revision 2).
 */
export function DeferredControl({ reason, noteId, testId, size = "sm", className, ...rest }: ControlProps & { noteId: string }) {
  const d = useDeferred(reason);
  return <Button size={size} {...rest} {...d.props} className={cx(d.props.className, className)} aria-describedby={noteId} data-testid={testId} />;
}

/** A deferred control with its own visible reason right after it. */
export function DeferredAction({ reason, noteTestId, ...rest }: ControlProps & { noteTestId?: string }) {
  const id = useId();
  return (
    <>
      <DeferredControl reason={reason} noteId={id} {...rest} />{" "}
      <Reason id={id} testId={noteTestId}>
        {reason}
      </Reason>
    </>
  );
}
