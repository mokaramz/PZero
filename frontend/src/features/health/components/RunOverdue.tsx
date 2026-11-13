import { Button } from "@/components/ui";
import { NOT_PORTED } from "../model/deferred";
import { DeferredAction, Reason } from "./bits";
import type { RunOverdueState } from "./useRunOverdueNow";

/** "Run overdue now" in one of its two places (./useRunOverdueNow): enabled with the live runner, deferred with its
 *  reason without it. */
export function RunOverdue({ r }: { r: RunOverdueState }) {
  if (!r.live)
    return (
      <DeferredAction reason={NOT_PORTED.runner} testId="health-run-overdue" noteTestId="health-run-overdue-note">
        Run overdue now
      </DeferredAction>
    );
  return (
    <>
      <Button size="sm" busy={r.pending} onClick={r.start} data-testid="health-run-overdue">
        Run overdue now
      </Button>
      {r.why && (
        <>
          {" "}
          <Reason testId="health-run-overdue-result">{r.why}</Reason>
        </>
      )}
    </>
  );
}
