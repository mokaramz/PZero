import { Badge, Callout, Panel } from "@/components/ui";
import { useFr } from "../context";
import type { Health } from "../model/types";
import styles from "../FounderRadar.module.css";

/** Diagnostics: Source coverage + Founder source health (v1 renderCoverage / renderFounderHealth). Before the first scan
 *  the health panel shows the server's note ("No founder scan yet — …"). */
export function Diagnostics() {
  const { data } = useFr();
  return (
    <div data-testid="fr-diag">
      <Panel
        id="frCoverage"
        title="Source coverage"
        aside="live discovery · enrichment · manual/authorized · configuration required · failed · not attempted"
      >
        <Coverage />
      </Panel>
      <Panel id="frHealth" title="Founder source health" aside="separate from company and event sources · no LinkedIn scraping, no automation, no cookies">
        <HealthBody h={data.health ?? {}} />
      </Panel>
    </div>
  );
}

function Coverage() {
  const { data } = useFr();
  const c = data.coverage;
  if (!c) return null;
  return (
    <div className={styles.coverage}>
      {Object.entries(c).map(([g, rows]) => (
        <div key={g}>
          <b>{g}</b> <span className={styles.subInline}>({rows.length})</span>
          {rows.length ? (
            <div className={styles.sub}>
              {rows.slice(0, 12).map((r, i) => (
                <div key={i}>
                  {r.name} — {r.role || ""}
                  {r.status ? " · " + r.status : ""}
                  {r.note ? " · " + r.note.slice(0, 80) : ""}
                </div>
              ))}
              {rows.length > 12 && <div>… {rows.length - 12} more</div>}
            </div>
          ) : (
            <div className={styles.sub}>—</div>
          )}
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ s }: { s: string }) {
  return s === "ok" ? <Badge tone="green">OK</Badge> : s === "failed" ? <Badge tone="red">FAILED</Badge> : <Badge tone="amber">REQUIRES CONFIGURATION</Badge>;
}

function HealthBody({ h }: { h: Health }) {
  const t = h.totals ?? {};
  if (!h.scan_time) return <span className={styles.sub}>{h.note || ""}</span>;
  const tot: Array<[string, number | undefined, string?]> = [
    ["attempted", t.attempted],
    ["successful", t.ok, styles.green],
    ["failed", t.failed, styles.red],
    ["configuration required", t.config_required, styles.amber],
    ["raw people/signals", t.raw],
    ["identities resolved", t.identities_resolved],
    ["unresolved", t.identities_unresolved],
    ["duplicates merged", t.merged],
    ["eligible for assessment", t.eligible_for_assessment],
    ["watchlisted", t.watchlisted],
    ["promoted to Network", t.promoted_to_network],
  ];
  return (
    <div data-testid="fr-health">
      <div className={styles.healthSum}>
        {tot.map(([l, v, cls]) => (
          <span key={l}>
            <b className={cls}>{v || 0}</b> {l}
          </span>
        ))}
        <span className={styles.sub}>
          scan {h.scan_time} · {t.seconds || 0}s
        </span>
      </div>
      {h.note && <Callout tone="amber">{h.note}</Callout>}
      <h4 className={styles.hd}>
        Europe-wide coverage — rotating batches of {h.batch?.size || 0} cities per scan (registry {h.batch?.registry_size || 0} cities)
      </h4>
      <div className={styles.tableWrap}>
        <table>
          <thead>
            <tr>
              <th>Region</th>
              <th>This scan</th>
              <th>OK / failed</th>
              <th>Cities ever retrieved</th>
              <th>Cities</th>
            </tr>
          </thead>
          <tbody>
            {(h.regions ?? []).map((r) => (
              <tr key={r.region}>
                <td>
                  <b>{r.region}</b>
                </td>
                <td>{r.attempted ? <Badge tone="green">{r.attempted} attempted</Badge> : <Badge>not attempted</Badge>}</td>
                <td>
                  {r.ok ?? 0} / {r.failed ?? 0}
                </td>
                <td>
                  {r.ever_ok ?? 0}/{r.cities.length}
                </td>
                <td className={styles.sub}>
                  {r.cities.map((c, i) => (
                    <span key={c.city} title={`${c.status} · last attempt ${c.last_attempt || "never"} · last ok ${c.last_ok || "never"} · ${c.next || ""}`}>
                      {i > 0 && ", "}
                      {c.city}
                      {c.attempted ? (c.status === "ok" ? " ✓" : " ✕") : " ·"}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={styles.sub}>✓ retrieved this scan · ✕ failed this scan · unmarked = not attempted this scan (waits for its batch; never reported as covered)</div>
      <h4 className={styles.hd}>Sources this scan</h4>
      <div className={styles.tableWrap}>
        <table>
          <thead>
            <tr>
              <th>Source</th>
              <th>Kind</th>
              <th>Status</th>
              <th>Raw</th>
              <th>New</th>
              <th>Merged</th>
              <th>Last successful</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {(h.sources ?? []).map((s, i) => (
              <tr key={(s.id || s.name) + i}>
                <td>{s.name}</td>
                <td className={styles.sub}>{s.kind || ""}</td>
                <td>
                  <StatusBadge s={s.status} />
                </td>
                <td>{s.raw || 0}</td>
                <td>{s.new || 0}</td>
                <td>{s.merged || 0}</td>
                <td className={styles.sub}>{s.last_ok || "never"}</td>
                <td className={styles.sub}>{s.note || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
