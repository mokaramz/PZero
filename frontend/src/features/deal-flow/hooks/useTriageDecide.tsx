import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { useToast } from "@/components/Toast";
import { useConfirm } from "@/components/useConfirm";
import { ApiError } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import type { Verdict } from "../model/triage";
import {
  BATCH_PREVIEW_LABEL,
  batchToast,
  decidedToast,
  NO_OBVIOUS_REJECTS,
  patchTriaged,
  skippedLine,
  TRIAGE_BATCH_REJECT,
  TRIAGE_DECIDE,
  TRIAGE_LABEL,
  triageDecideBody,
  type BatchApplied,
  type BatchBody,
  type BatchPreview,
  type TriageDecideAnswer,
  type TriageDecideBody,
  type TriageMode,
} from "../model/triageDecide";
import type { Candidate, InboxPayload } from "../model/types";
import { INBOX, INBOX_KEY, TRIAGE } from "./useDealFlowData";

/**
 * What a triage decision makes stale — the old `triage`, inbox (review_queue / sources / feedback), `home` and `today`
 * invalidations in the new keys. The source feedback lives in the inbox and on Sources; Validation reads the decision
 * log's triage metrics (035a) so it is read again too. The Agent Review Queue is not ported.
 */
export const TRIAGE_INVALIDATES = [TRIAGE, INBOX, "sources", "home", "today", "validation"] as const;

/** The server refused a decision on a candidate that changed (or moved company) meanwhile. */
const isStale = (e: unknown) => e instanceof ApiError && e.status === 409;

function useRefresh() {
  const qc = useQueryClient();
  return useCallback(
    (keys: readonly string[] = TRIAGE_INVALIDATES) => {
      for (const k of keys) void qc.invalidateQueries({ queryKey: [k] });
    },
    [qc],
  );
}

/**
 * Accept or override one machine proposal (the old `TriagePanel` `onDecide`).
 * - success: the cached row is patched with the applied decision, every view above is read again, and either the Keep
 *   form opens (`open_keep`, a KEEP — the Conviction save sets `kept`) or the old toast says what was done;
 * - an error is the action's error toast (the server's own text: a 400 names the rule, a 409 says to reload); a 409 also
 *   reads the inbox and the triage again, so the panel shows the server's state. Nothing is applied optimistically.
 */
export function useTriageDecide(onKeep: (id: string) => void) {
  const qc = useQueryClient();
  const toast = useToast();
  const refresh = useRefresh();
  const { mutate, isPending } = useAction<TriageDecideBody, TriageDecideAnswer>(TRIAGE_DECIDE, { invalidates: [], label: TRIAGE_LABEL, quiet: true });
  const decide = useCallback(
    (c: Candidate, verdict: Verdict, mode: TriageMode) =>
      mutate(triageDecideBody(c, verdict, mode), {
        onSuccess: (r) => {
          if (!r.ok) return; // the same click already in flight
          const applied = r.inbox_decision;
          if (applied) qc.setQueryData<InboxPayload>(INBOX_KEY, (old) => old && patchTriaged(old, [c.id], applied));
          refresh();
          if (r.open_keep) onKeep(c.id);
          else toast.show(decidedToast(verdict, mode), "ok");
        },
        onError: (e) => {
          if (isStale(e)) refresh([INBOX, TRIAGE]);
        },
      }),
    [mutate, qc, refresh, onKeep, toast],
  );
  return { decide, busy: isPending };
}

/**
 * "Accept obvious REJECTs…" (the old batch): nothing is sent for an empty view; otherwise the server previews which of
 * the ids are eligible, the old confirm dialog asks to "Reject N" of them, and only a confirm applies the batch. Render
 * `dialog` once.
 */
export function useBatchReject() {
  const qc = useQueryClient();
  const toast = useToast();
  const refresh = useRefresh();
  const [confirm, dialog] = useConfirm();
  const preview = useAction<BatchBody, BatchPreview>(TRIAGE_BATCH_REJECT, { invalidates: [], label: BATCH_PREVIEW_LABEL, quiet: true });
  const apply = useAction<BatchBody, BatchApplied>(TRIAGE_BATCH_REJECT, { invalidates: [], label: TRIAGE_LABEL, quiet: true });
  const { mutateAsync: ask } = preview;
  const { mutate: run } = apply;

  const batchReject = useCallback(
    async (ids: string[]) => {
      if (!ids.length) return toast.show(NO_OBVIOUS_REJECTS);
      let p: BatchPreview;
      try {
        p = await ask({ ids });
      } catch {
        return; // the action's error toast
      }
      if (!p.ok) return;
      if (!p.eligible) return toast.show(NO_OBVIOUS_REJECTS);
      const skipped = skippedLine(p.skipped ?? {});
      const ok = await confirm(
        <>
          Accept <b>{p.eligible}</b> machine REJECT proposals where both models agreed on a supported reason (or the record is junk)? Portfolio / conflict-flagged
          and changed candidates are excluded. Each becomes <b>rejected</b> in Deal Flow and is logged as your decision — Undo works per candidate.
          {skipped && <div className="faint small" data-testid="batch-skipped">Left out: {skipped}.</div>}
        </>,
        { title: "Batch-accept obvious REJECTs", ok: `Reject ${p.eligible}` },
      );
      if (!ok) return;
      run(
        { ids, confirm: true },
        {
          onSuccess: (r) => {
            if (!r.ok) return;
            // every id was applied: patch them now; otherwise the refetch below shows which ones were
            if (!Object.keys(r.skipped ?? {}).length) qc.setQueryData<InboxPayload>(INBOX_KEY, (old) => old && patchTriaged(old, ids, "rejected"));
            refresh();
            toast.show(batchToast(r), "ok");
          },
          onError: (e) => {
            if (isStale(e)) refresh([INBOX, TRIAGE]);
          },
        },
      );
    },
    [ask, run, confirm, qc, refresh, toast],
  );
  return { batchReject, busy: preview.isPending || apply.isPending, dialog };
}
