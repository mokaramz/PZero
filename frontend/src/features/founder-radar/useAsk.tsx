import { useCallback, useState } from "react";

import { AskModal } from "./components/AskModal";
import type { AskSpec, Values } from "./model/ask";

type Pending = { spec: AskSpec; resolve: (v: Values | null) => void };

/**
 * A promise-based form dialog (the old `useAsk`): `const v = await ask(spec); if (!v) return;`. Render `dialog` once.
 */
export function useAsk() {
  const [pending, setPending] = useState<Pending | null>(null);
  const ask = useCallback((spec: AskSpec) => new Promise<Values | null>((resolve) => setPending({ spec, resolve })), []);
  const close = (v: Values | null) => {
    pending?.resolve(v);
    setPending(null);
  };
  const dialog = pending ? <AskModal key={pending.spec.title} spec={pending.spec} onDone={close} /> : null;
  return { ask, dialog };
}
