import { useId } from "react";

import { Badge, Panel } from "@/components/ui";
import { NOT_PORTED } from "../model/deferred";
import { DeferredControl, Reason } from "./bits";

export type Backup = { archive: string; name: string; bytes: number; has_checksum: boolean; restore_test: { ok: boolean; tested_at: string; problems: string[] } | null };
export type IntegrityReport = { status: "ok" | "warn" | "error"; issues: Array<{ level: string; kind: string; what: string; safe_repair: string }>; files_checked: number };
export type Gov = {
  calls: number;
  by_purpose: Array<{ purpose: string; calls: number; usd: number; models: Record<string, number>; prompt_versions: number; last: string }>;
  roles: Record<string, { provider: string; model: string; enabled: boolean }>;
  field_completeness: Record<string, number | null>;
  experiments: Array<{ id: string; name: string; kind: string; at: string; n: number; status: string; delta: Record<string, number> }>;
  note: string;
};
/** The three 032b reads (`backups`, `integrity`, `governance`), when they exist. */
export type HardeningData = { backups?: { backups: Backup[]; dir: string }; integrity?: IntegrityReport; governance?: Gov };

const mb = (n: number) => `${(n / 1_048_576).toFixed(1)} MB`;

/**
 * Protect the operating history: backups, integrity checks, AI provenance. The old panels read `backups`,
 * `integrity` and `governance` and wrote `backup`, `backup_restore_test` and `integrity_repair`; all of them are the
 * hardening port (032b, redesigned for hosted Supabase). Until then the page makes NO request for them (`data` is
 * undefined): each panel shows the reason in place of its data, and "Back up now", "Test latest backup" and "Safe
 * repair" keep their place and label, disabled with that visible reason (decision h).
 */
export function Hardening({ data }: { data?: HardeningData }) {
  const bk = data?.backups;
  const iq = data?.integrity;
  const gq = data?.governance;
  const backupNote = useId();
  const repairNote = useId();
  const why = NOT_PORTED.hardening;
  return (
    <>
      <Panel
        title="Backups"
        data-testid="health-backups"
        aside={
          <span className="row">
            <DeferredControl reason={why} noteId={backupNote} variant="primary" testId="backup-now">
              Back up now
            </DeferredControl>
            <DeferredControl reason={why} noteId={backupNote} testId="backup-test">
              Test latest backup
            </DeferredControl>
          </span>
        }
      >
        <p className="small">
          <Reason id={backupNote} testId="backup-reason">
            {why}
          </Reason>
        </p>
        {bk &&
          (bk.backups.length ? (
            <ul className="small">
              {bk.backups.slice(0, 5).map((b) => (
                <li key={b.name}>
                  {b.name} · {mb(b.bytes)} {b.has_checksum && <Badge>checksum</Badge>}{" "}
                  {b.restore_test ? (
                    <Badge tone={b.restore_test.ok ? "green" : "red"}>{b.restore_test.ok ? `restore tested ${b.restore_test.tested_at.slice(0, 10)}` : "restore test failed"}</Badge>
                  ) : (
                    <Badge tone="amber">not restore-tested yet</Badge>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <div className="small">No backup yet.</div>
          ))}
      </Panel>

      <Panel title="Data integrity" data-testid="health-integrity">
        {iq ? (
          <>
            <div className="small">
              <Badge tone={iq.status === "ok" ? "green" : iq.status === "warn" ? "amber" : "red"}>{iq.status.toUpperCase()}</Badge> {iq.files_checked} files checked:
              malformed files, duplicate ids, broken links between stores, impossible dates, stuck jobs. Report only — nothing is repaired automatically.
            </div>
            <ul className="small">
              {iq.issues.map((i) => (
                <li key={i.what}>
                  <Badge tone={i.level === "error" ? "red" : i.level === "warn" ? "amber" : "neutral"}>{i.kind.replace(/_/g, " ")}</Badge> {i.what}{" "}
                  {i.safe_repair && (
                    <DeferredControl reason={why} noteId={repairNote} variant="ghost" testId="safe-repair">
                      Safe repair
                    </DeferredControl>
                  )}
                </li>
              ))}
            </ul>
            {iq.issues.some((i) => i.safe_repair) && (
              <p className="small">
                <Reason id={repairNote} testId="safe-repair-reason">
                  {why}
                </Reason>
              </p>
            )}
          </>
        ) : (
          <p className="small">
            <Reason testId="integrity-reason">{why}</Reason>
          </p>
        )}
      </Panel>

      <Panel title="Model provenance & experiments" data-testid="health-governance">
        {gq ? (
          <>
            <p className="small faint">
              Every model output is recorded with provider, model, role, prompt version, time, cost and outcome — so a change in quality can be traced to a model or prompt
              change. {gq.note}
            </p>
            <div style={{ overflowX: "auto" }}>
              <table style={{ fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>What it is used for</th>
                    <th>Calls</th>
                    <th>Cost</th>
                    <th>Model(s)</th>
                    <th>Prompt versions</th>
                    <th>Last</th>
                  </tr>
                </thead>
                <tbody>
                  {gq.by_purpose.map((p) => (
                    <tr key={p.purpose}>
                      <td>{p.purpose.replace(/_/g, " ")}</td>
                      <td>{p.calls}</td>
                      <td>${p.usd.toFixed(3)}</td>
                      <td>{Object.keys(p.models).join(", ")}</td>
                      <td>{p.prompt_versions || "—"}</td>
                      <td>{String(p.last || "").slice(0, 16)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="small" style={{ marginTop: 6 }}>
              <b>Shadow experiments</b> (a new model / prompt / extraction / routing rule is tested side by side before anything changes — production is never switched
              automatically): {gq.experiments.length ? gq.experiments.map((e) => `${e.name} (${e.status})`).join(" · ") : "none yet"}
            </div>
          </>
        ) : (
          <p className="small">
            <Reason testId="governance-reason">{why}</Reason>
          </p>
        )}
      </Panel>
    </>
  );
}
