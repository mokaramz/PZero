/**
 * INVESTMENT DESK (v1 view `home`, review 031a) — the bridge of Project Zero: an orientation / command page, not a
 * dashboard. In seconds it answers: what needs the Smooth Operator today, the best current opportunity, what needs the
 * Manager, which new signals matter, and what the machine is handling. Every number and line comes from existing PZ
 * state (home · inbox · pipeline · today · sources, ./api); nothing is scored, generated or sent here — every action
 * opens the specialist page. Today is the place to execute; this page orients.
 */
import { useState } from "react";

import { ErrorBox, Spinner } from "@/components/ui";
import { WeeklyDrawer } from "@/features/conviction/components/WeeklyDrawer";
import { REVIEW_ROWS, useDeskReads } from "./api";
import { Desk } from "./components/Desk";

export default function HomePage() {
  const { home, inbox, pipe, today, sources } = useDeskReads();
  const [weekly, setWeekly] = useState(false);

  if (home.isLoading || inbox.isLoading || (pipe.isPending && !inbox.error)) return <Spinner label="Loading the desk…" />;
  if (home.error || !home.data) return <ErrorBox error={home.error ?? "No data"} onRetry={() => home.refetch()} />;
  return (
    <>
      <Desk
        h={home.data}
        ib={inbox.data}
        pipe={pipe.data}
        today={today.data}
        rows={REVIEW_ROWS}
        sources={sources.data}
        onWeekly={() => setWeekly(true)}
      />
      <WeeklyDrawer open={weekly} onClose={() => setWeekly(false)} />
    </>
  );
}
