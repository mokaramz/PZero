/**
 * SYSTEM HEALTH (v1 view `health`, review 032a) — is Project Zero healthy? One answer first, then the systems, the
 * history, the money, and every detail one click away. Two reads (./api): `system_health` decides the page (its
 * loading and error states are the page's), `system_health_overview` fills the history, models, spend, pipeline and
 * backups panels as it arrives (its error is shown above the panels, with a retry). Nothing here writes: every action
 * control is deferred with its visible reason (decision h), and Refresh re-reads both GETs.
 */
import { Async } from "@/components/ui";
import { useHealthReads } from "./api";
import { Dashboard } from "./components/Dashboard";

export default function HealthPage() {
  const { health: q, overview: ov } = useHealthReads();
  return (
    <Async q={q} label="Checking…">
      {(d) => (
        <Dashboard
          d={d}
          o={ov.data}
          oErr={ov.error}
          oLoading={ov.isLoading}
          refresh={() => void Promise.all([q.refetch(), ov.refetch()])}
          refreshing={q.isFetching || ov.isFetching}
        />
      )}
    </Async>
  );
}
