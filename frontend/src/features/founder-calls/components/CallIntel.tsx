import { useState } from "react";

import { DeferredButton } from "@/components/Deferred";
import { Button, Panel } from "@/components/ui";
import { NotPortedPart } from "@/features/conviction/components/parts";
import { NOT_PORTED } from "../model/deferred";

/** Founder-call intelligence: a targeted prep card before the call, and what needs public verification after it. Both
 *  tabs keep their place, but their content reads the Claim Index, identity and registries, which arrive with a later
 *  port — so each says why instead, and nothing is requested (review 023, decision b). */
export function CallIntel() {
  const [tab, setTab] = useState<"prep" | "after">("prep");
  return (
    <Panel
      title="Call intelligence"
      data-testid="call-intel"
      aside={
        <span className="row">
          <Button size="sm" variant={tab === "prep" ? "primary" : "default"} onClick={() => setTab("prep")} aria-pressed={tab === "prep"}>
            Prep card
          </Button>
          <Button size="sm" variant={tab === "after" ? "primary" : "default"} onClick={() => setTab("after")} aria-pressed={tab === "after"} data-testid="call-after-tab">
            After the call
          </Button>
        </span>
      }
    >
      {tab === "prep" ? (
        <NotPortedPart title="Prep card" reason={NOT_PORTED.intel} testId="call-prep" />
      ) : (
        <>
          <NotPortedPart title="After the call" reason={NOT_PORTED.intel} testId="post-call" />
          <DeferredButton size="sm" variant="ghost" reason={NOT_PORTED.bridge} data-testid="call-bridge">
            Approve paid research (Scout Bridge, capped)
          </DeferredButton>
        </>
      )}
    </Panel>
  );
}
