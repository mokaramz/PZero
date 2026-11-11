import { useCallback, useRef, useState, type ReactNode } from "react";

import { Button, Modal } from "@/components/ui";

type Ask = { title: string; message: ReactNode; ok: string };
export type ConfirmOptions = { title?: string; ok?: string };
export type Confirm = (message: ReactNode, opts?: ConfirmOptions) => Promise<boolean>;

/**
 * Explicit human confirmation (instead of window.confirm). Returns `[confirm, element]`; render `element` once and
 * `await confirm(...)` → true only when the operator clicks the confirm button (Cancel, Escape or the backdrop → false).
 */
export function useConfirm(): [Confirm, ReactNode] {
  const [ask, setAsk] = useState<Ask | null>(null);
  const resolver = useRef<((v: boolean) => void) | null>(null);
  const confirm = useCallback<Confirm>((message, opts = {}) => {
    setAsk({ title: opts.title ?? "Please confirm", message, ok: opts.ok ?? "Confirm" });
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);
  const done = (answer: boolean) => {
    resolver.current?.(answer);
    resolver.current = null;
    setAsk(null);
  };
  const element = (
    <Modal
      open={!!ask}
      onClose={() => done(false)}
      title={ask?.title}
      width={520}
      footer={
        <>
          <Button onClick={() => done(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => done(true)} data-testid="confirm-ok">
            {ask?.ok}
          </Button>
        </>
      }
    >
      <div>{ask?.message}</div>
    </Modal>
  );
  return [confirm, element];
}
