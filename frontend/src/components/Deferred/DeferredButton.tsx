import type { ReactNode } from "react";

import { Button, type ButtonProps } from "@/components/ui";
import { cx } from "@/lib/format";
import { useDeferred } from "./useDeferred";

/** A `Button` whose action is not ported yet (see `useDeferred`): same look and text, disabled with a reason. */
export function DeferredButton({ reason, className, ...rest }: Omit<ButtonProps, "onClick" | "disabled" | "busy"> & { reason: string }) {
  const d = useDeferred(reason);
  return (
    <>
      <Button {...rest} {...d.props} className={cx(d.props.className, className)} />
      {d.note}
    </>
  );
}

/** A text-link button (`className` gives its look) whose action is not ported yet. */
export function DeferredLink({ reason, className, children }: { reason: string; className?: string; children: ReactNode }) {
  const d = useDeferred(reason);
  return (
    <>
      <button type="button" {...d.props} className={cx(d.props.className, className)}>
        {children}
      </button>
      {d.note}
    </>
  );
}
