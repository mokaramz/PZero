/**
 * The Sources endpoints (review 021) — the ONE place their paths live.
 *
 * - `GET sources` → the old `/api/sources` payload plus `ws_geos`, `report`, `manual_sources`, `pages` and `feeds`
 *   (the old page read those from `/api/inbox`; it is one call now).
 * - `POST sources/toggle {id, enabled}` → `{ok: true}`.
 */
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { useAction, useApi } from "@/lib/hooks";
import type { SourcesPayload } from "./model/types";

export const SOURCES = "sources";
export const TOGGLE = "sources/toggle";

/** What a toggle makes stale: the registry (the coverage matrix is part of the same payload). */
export const SOURCES_KEYS = [SOURCES];

/** The old action label (Background activity and the "✓ … — done" / "✕ … failed" toasts). */
export const LABEL = { toggle: "Switching the source" } as const;

export function useSources() {
  return useApi<SourcesPayload>(SOURCES);
}

/** Enable / disable a source. The row flips at once (optimistic) and the refetch after success confirms it; a failure
 *  refetches the registry, so the row shows what the server holds. */
export function useToggleSource() {
  const qc = useQueryClient();
  const toast = useToast();
  const action = useAction<{ id: string; enabled: boolean }, { ok: boolean }>(TOGGLE, { invalidates: SOURCES_KEYS, label: LABEL.toggle });
  const toggle = (id: string, enabled: boolean) => {
    qc.setQueryData<SourcesPayload>([SOURCES, {}], (old) => old && { ...old, sources: old.sources.map((s) => (s.id === id ? { ...s, enabled } : s)) });
    action.mutate(
      { id, enabled },
      {
        onSuccess: () => toast.show(enabled ? "Source enabled" : "Source disabled", "ok"),
        onError: () => void qc.invalidateQueries({ queryKey: [SOURCES] }),
      },
    );
  };
  return { toggle, isPending: action.isPending };
}
