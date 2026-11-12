/**
 * Project A Radar — Top 10 (v1 view `radar`, review 019): 8 high-confidence + 1 emerging + 1 wildcard, fully verified
 * only. Empty slots stay empty on purpose; the research queue, the conflict-gated (for Manager) and the watchlist
 * follow, each only when it has a company. The Radar is computed by the Conviction backend (`GET conviction/radar`).
 */
import { useState } from "react";

import { Disclosure } from "@/components/focus";
import { Async, PageHeader } from "@/components/ui";
import { useMeta, useRadar } from "@/features/conviction/api";
import { useNewKeys } from "@/lib/motion";
import type { CardPick } from "./components/RadarCard";
import { RadarSection } from "./components/RadarSection";
import styles from "./Radar.module.css";

export default function RadarPage() {
  const radar = useRadar();
  const meta = useMeta();
  const [sel, setSel] = useState<string | null>(null);
  const d = radar.data;
  const fresh = useNewKeys(d ? [...d.high, ...d.emerging, ...d.wildcard, ...d.research_queue, ...d.gated, ...d.watch].map((e) => e.slug) : []);
  const pick: CardPick = { sel, onSelect: (slug) => setSel((s) => (s === slug ? null : slug)), fresh };
  const m = meta.data;
  return (
    <>
      <PageHeader
        title="PROJECT A RADAR — TOP 10"
        subtitle="Fully verified companies only, ranked by Verified score — empty slots stay empty on purpose."
      />
      {/* the method recedes: one click below, never in the way of the companies */}
      <Disclosure title="How the radar is built" icon="question" level={3} testId="radar-method" className={styles.method}>
        <p className="small">
          8 high-confidence + 1 emerging/adjacent + 1 wildcard (outlier route) — <b>fully verified companies only, ranked by Verified score</b>.
          Unverified companies with Provisional ≥ 65 sit in the Research Queue until you verify founders, traction and funding. Empty slots stay
          empty. Conflict-gated companies are listed for Manager, never forwarded.
        </p>
      </Disclosure>
      <Async q={radar} label="Loading radar…">
        {(r) => (
          <>
            <RadarSection title="High-confidence (8 slots) — fully verified only" list={r.high} slots={8} meta={m} pick={pick} />
            <RadarSection title="Emerging / adjacent thesis (1 slot) — fully verified only" list={r.emerging} slots={1} meta={m} pick={pick} />
            <RadarSection title="Wildcard — outlier route (1 slot) — fully verified only" list={r.wildcard} slots={1} meta={m} pick={pick} />
            {r.research_queue.length > 0 && (
              <RadarSection
                title="Research Queue — promising (Provisional ≥ 65) but NOT verified; do the 10-minute checks to promote"
                list={r.research_queue}
                meta={m}
                pick={pick}
              />
            )}
            {r.gated.length > 0 && <RadarSection title="Conflict-gated — for Manager, not for forwarding" list={r.gated} gated meta={m} pick={pick} />}
            {r.watch.length > 0 && <RadarSection title="Watchlist (50–64)" list={r.watch} meta={m} pick={pick} />}
          </>
        )}
      </Async>
    </>
  );
}
