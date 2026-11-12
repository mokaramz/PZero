import { Button } from "@/components/ui";
import { SOURCES_SHOWN, sourceLine } from "../model/coverage";
import type { CovCandidate, CovEcosystem, FamilyDef } from "../model/types";
import styles from "../Ecosystems.module.css";
import { CovTag } from "./CovTag";

/** The selected ecosystem: its state and covered / missing families, the audit opinion (reference only), then per family
 *  its state, why, configured sources and the audit's candidate watchers, each adoptable on its own. */
export function CoverageDetail({ e, families, onAdopt }: { e: CovEcosystem; families: FamilyDef[]; onAdopt: (c: CovCandidate) => void }) {
  return (
    <div className={styles.covDetail} data-testid="coverage-detail">
      <div>
        <b>{e.city}</b> — <CovTag st={e.overall} /> {e.label} · covered: {e.families_covered.join(", ") || "none"} · missing:{" "}
        {e.families_missing.join(", ") || "none"}
      </div>
      {e.audit?.status && (
        <div className="muted small">
          Chief Scout coverage audit ({e.audit.source}) — {e.audit.ecosystem}: opinion <CovTag st={e.audit.status} /> · biggest blind spot: {e.audit.blind_spot} —
          reference only; the states above are computed from configured sources and recorded runs.
        </div>
      )}
      {families.map(([id, l]) => {
        const f = e.families[id];
        if (!f) return null;
        return (
          <div key={id} className={styles.fam} data-testid={`family-${id}`}>
            <b>{l}</b> <CovTag st={f.state} /> <span className="muted small">{f.why}</span>
            {f.sources.length > 0 && (
              <div className="muted small">
                {f.sources.slice(0, SOURCES_SHOWN).map((s) => (
                  <div key={s.id}>{sourceLine(s)}</div>
                ))}
                {f.sources.length > SOURCES_SHOWN && <div>… {f.sources.length - SOURCES_SHOWN} more</div>}
              </div>
            )}
            {!!f.candidates?.length && (
              <div className="small">
                <b>Candidate watchers (audit, not activated):</b>
                {f.candidates.map((c) => (
                  <div key={c.id} className={styles.cand}>
                    •{" "}
                    <a href={c.url} target="_blank" rel="noopener noreferrer">
                      {c.name}
                    </a>{" "}
                    — {c.source_type} · access {c.access_mode}
                    {c.access_limitations ? ` · ${c.access_limitations}` : ""}{" "}
                    <Button size="sm" onClick={() => onAdopt(c)}>
                      Adopt as watcher
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
