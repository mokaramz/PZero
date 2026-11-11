import { Button, type ButtonProps } from "@/components/ui";
import { cx } from "@/lib/format";
import type { NotPortedReason } from "../model/deferred";
import { useDeferred } from "./Deferred";

/** A `Button` whose action is not ported yet (see `useDeferred`): same look and text, disabled with a reason. */
export function DeferredButton({ reason, className, ...rest }: Omit<ButtonProps, "onClick" | "disabled" | "busy"> & { reason: NotPortedReason }) {
  const d = useDeferred(reason);
  return (
    <>
      <Button {...rest} {...d.props} className={cx(d.props.className, className)} />
      {d.note}
    </>
  );
}
