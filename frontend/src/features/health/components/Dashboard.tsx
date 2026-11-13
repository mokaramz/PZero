import { useMemo, useState } from "react";

import { Button, Drawer, ErrorBox } from "@/components/ui";
import { cx } from "@/lib/format";
import { asRole } from "@/lib/roles";
import {
  GROUPS,
  RANGES,
  STATE_LABEL,
  STATUS_TONE,
  activeSources,
  ago,
  attention,
  groupOf,
  lanes,
  lastDays,
  modelSuccess,
  shortModel,
  sourceFamilies,
  usd,
  type Mark,
  type Range,
} from "../model/dashboard";
import { JOBS_SNAPSHOT, NOT_PORTED, ported, reasonOf } from "../model/deferred";
import { detailTitle, type Detail } from "../model/detail";
import { fmt } from "../model/format";
import type { Health, Overview } from "../model/types";
import { DeferredAction, Kpi, Meter, Reason, St, StackRow } from "./bits";
import { JobMatrix, Spark, SpendChart } from "./Charts";
import { DetailBody } from "./DetailBody";
import { Diagnostics } from "./Diagnostics";
import styles from "../Health.module.css";

/**
 * Is Project Zero healthy? One answer first, then the systems, the history, the money — and every detail one click
 * away (ported from the old `HealthPage.tsx`, review 032a). Removed with the retired Scout parts (decision c): the
 * Scouting KPI, the Scout 00 and Native Scout lanes, the Grok search bridge chart, pool and KPI line, and "Prepare
 * repair research". The deferred subsystems show their reason where their data was (decision d); "Run overdue now"
 * keeps both of its places, disabled with its visible reason (decision h); the job panels say the jobs are the
 * imported snapshot (decision e). Refresh is the only control that acts: it re-reads the two GETs.
 */
export function Dashboard({ d, o, oErr, oLoading, refresh, refreshing }: { d: Health; o?: Overview; oErr: unknown; oLoading: boolean; refresh: () => void; refreshing: boolean }) {
  const now = useMemo(() => (d.at ? new Date(d.at) : new Date()), [d.at]);
  const [range, setRange] = useState<Range>("30d");
  const [detail, setDetail] = useState<Detail>(null);
  const [q, setQ] = useState("");

  const status = d.status ?? { key: "unknown" as const, label: "Status unknown", sentence: "This server does not report an overall status yet.", groups: { need: 0, auto: 0, ext: 0, info: 0 }, last_job_report: "", report_age_h: null };
  const issues = d.issues.map((i) => ({ ...i, group: groupOf(i) }));
  const fam = sourceFamilies(d);
  const att = attention(d);
  const days30 = lastDays(now, 30);
  const runs = o?.jobs.runs ?? [];
  const ms = modelSuccess(o);
  const backups = ported(o?.backups);
  const integrity = ported(o?.integrity);
  const releases = ported(o?.releases);
  const backupsWhy = reasonOf(o?.backups);
  const integrityWhy = reasonOf(o?.integrity);
  const releasesWhy = reasonOf(o?.releases);
  const rel = releases?.[0];
  const lastRunsDay = days30.map((x) => runs.filter((r) => r.at.slice(0, 10) === x).length);
  const spendDay = days30.map((x) => Object.values(o?.models.spend_by_day[x] ?? {}).reduce((a, b) => a + b, 0));
  const failed30 = runs.filter((r) => r.state === "failed" || r.state === "interrupted").length;
  const partial30 = runs.filter((r) => r.state === "partial").length;
  const lastBk = backups?.latest;
  const verified = backups?.last_verified;
  const att2 = att.filter((s) => !q || `${s.name} ${s.last_error} ${s.repair?.cause ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  const overdueAction = d.overdue > 0;
  const go = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  const integrityMark: Mark = !integrity ? ["unk", "Not ported yet"] : integrity.status === "ok" ? ["ok", "No issues"] : integrity.status === "unknown" ? ["unk", "Not checked"] : ["warn", `${integrity.issues} issue(s)`];

  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div>
          <h1 className={styles.title}>System health</h1>
          <p className={styles.sub}>Infrastructure, intelligence pipelines, model spending and operational issues.</p>
        </div>
        <div className={styles.fresh} data-testid="health-freshness">
          Updated <b>{fmt(d.at, { hour: "2-digit", minute: "2-digit" })}</b> · latest job report {status.last_job_report ? ago(status.last_job_report, now) : "none yet"}
          {rel && (
            <>
              <br />
              release <b>{rel.tag}</b> · deployed {fmt(rel.at)}
            </>
          )}
          {releasesWhy && (
            <>
              <br />
              <Reason testId="health-release-reason">{releasesWhy}</Reason>
            </>
          )}
          <br />
          <Button size="sm" busy={refreshing} onClick={refresh}>
            Refresh
          </Button>
        </div>
      </header>

      <section className={styles.verdict} data-testid="health-verdict" aria-label="Overall status">
        <span className={cx(styles.vbadge, styles[`v_${STATUS_TONE[status.key]}`])}>
          <i aria-hidden />
          {status.label}
        </span>
        <p className={styles.vtext} data-testid="health-action">
          {asRole(status.sentence)}
        </p>
      </section>

      {oErr ? <ErrorBox error={oErr} onRetry={refresh} /> : null}

      <div className={styles.kpis} aria-label="Key health indicators">
        <Kpi k="Background jobs" onClick={() => go("hp-jobs")} mark={failed30 ? ["bad", `${failed30} failed`] : d.overdue ? ["lim", `${d.overdue} overdue`] : ["ok", "On schedule"]}
          v={<>{d.jobs.length} <small>jobs</small></>} f={[o ? `${runs.length} runs / ${o.jobs.days} d · ${failed30} failed · ${partial30} partial` : ""]}
          spark={o ? <Spark values={lastRunsDay} color="var(--dot-sage)" label="runs per day, last 30 days" /> : null} />
        <Kpi k="Data sources" onClick={() => go("hp-sources")} mark={att.length ? ["lim", `${att.length} need${att.length === 1 ? "s" : ""} a look`] : ["ok", "All healthy"]}
          v={<>{fam.dealFlow.healthy} <small>/ {activeSources(d)} active</small></>}
          f={[`${fam.dealFlow.disabled} disabled by you${fam.news ? ` · news ${fam.news.healthy}/${fam.news.healthy + fam.news.failing} feeds` : ""}`]} />
        <Kpi k="AI models" onClick={() => go("hp-models")} mark={ms.rate == null ? ["unk", "No calls in 7 d"] : ms.rate >= 0.9 ? ["ok", "Responding"] : ["warn", "Error rate high"]}
          v={<>{ms.rate == null ? "—" : (100 * ms.rate).toFixed(1)}<small>% ok · 7 d</small></>} f={[`${ms.calls} calls · ${ms.used} model${ms.used === 1 ? "" : "s"} used`]} />
        <Kpi k="Model spend · month" onClick={() => go("hp-spend")} mark={d.spend.kill_switch ? ["lim", "Paid AI off"] : d.spend.month >= 0.8 * (d.spend.limits.monthly_usd || Infinity) ? ["warn", "Near the cap"] : ["ok", "Within budget"]}
          v={<>{usd(d.spend.month)} <small>/ {usd(d.spend.limits.monthly_usd, 0)}</small></>}
          f={[]}
          spark={o ? <Spark values={spendDay} color="var(--blue)" label="model spend per day, last 30 days" /> : null} />
        <Kpi k="Backups & integrity" onClick={() => go("hp-backups")} mark={!o ? ["unk", "Loading"] : !integrity ? ["unk", "Not ported yet"] : integrity.status === "ok" ? ["ok", "Integrity ok"] : integrity.status === "unknown" ? ["unk", "Not checked"] : ["warn", `${integrity.issues} integrity issue(s)`]}
          v={<>{lastBk ? ago(lastBk.at, now).replace(" ago", "") : "—"} <small>since backup</small></>}
          f={[backups ? (verified ? `Last verified restore ${fmt(verified.restore_at, { day: "numeric", month: "short" })}` : "No verified restore yet") : (backupsWhy ?? ""), integrityWhy && integrityWhy !== backupsWhy ? integrityWhy : ""]} />
      </div>

      <section className={styles.pipe} id="hp-pipeline" aria-labelledby="hp-pipe-h" data-testid="health-pipeline">
        <div className={styles.sh}>
          <h2 id="hp-pipe-h">Intelligence pipeline</h2>
          <span className={styles.d}>Where data is moving, where it waits, and where only you decide. Select a step for details.</span>
        </div>
        {!o ? (
          <div className={styles.pipeEmpty}>{oLoading ? "Loading the pipeline…" : "Pipeline data unavailable right now."}</div>
        ) : (
          lanes(d, o).map((l) => (
            <div key={l.id} className={styles.lane} style={{ ["--n" as string]: l.nodes.length }}>
              <div className={styles.lname}>
                {l.name}
                <small>{l.sub}</small>
              </div>
              {l.nodes.map((n, i) => (
                <div key={n.id} className={styles.step}>
                  {i > 0 && <span className={cx(styles.arrow, n.human && styles.arrowWait)} aria-hidden />}
                  <button
                    type="button"
                    className={cx(styles.node, n.human && styles.nodeHuman, n.external && styles.nodeExt, detail?.kind === "node" && detail.node.id === n.id && styles.nodeSel)}
                    data-node={n.id}
                    onClick={() => setDetail({ kind: "node", node: n, lane: l.name })}
                  >
                    <span className={styles.nm}>{n.name}</span>
                    <span className={styles.nf}>{asRole(n.fact)}</span>
                    <span className={styles.ns}>
                      <St m={n.mark} />
                    </span>
                  </button>
                </div>
              ))}
            </div>
          ))
        )}
        <div className={styles.plegend}>
          <St m={["ok", "operating"]} /> <St m={["lim", "limited / waiting"]} /> <St m={["warn", "needs attention"]} /> <St m={["bad", "failing"]} /> <St m={["unk", "no data"]} />
          <span>◆ dashed = a human decision — nothing passes it automatically</span>
          <span>dotted = outside Project Zero</span>
        </div>
      </section>

      <div className={styles.grid2}>
        <section className={styles.panel} id="hp-jobs" aria-labelledby="hp-jobs-h" data-testid="health-job-history">
          <div className={styles.sh}>
            <h2 id="hp-jobs-h">Background jobs</h2>
            <span className={styles.d}>result of every scheduled run</span>
            <span className="grow" />
            <span className={styles.seg} role="group" aria-label="Time range">
              {(Object.keys(RANGES) as Range[]).map((k) => (
                <button key={k} type="button" aria-pressed={range === k} className={cx(range === k && styles.segOn)} onClick={() => setRange(k)}>
                  {k}
                </button>
              ))}
            </span>
          </div>
          {!o ? (
            <div className={styles.empty}>{oLoading ? "Loading job history…" : "History unavailable."}</div>
          ) : runs.length === 0 ? (
            <div className={styles.empty}>History unavailable — no scheduled run is recorded in the imported snapshot. The plan below is still current.</div>
          ) : (
            <JobMatrix jobs={d.jobs} runs={runs} range={range} now={now} onCell={(jobId, rs) => setDetail({ kind: "runs", jobId, runs: rs })} />
          )}
          <div className={styles.legend}>
            {["completed", "no_findings", "partial", "failed", "budget_blocked", "waiting_external", "skipped"].map((k) => (
              <span key={k}>
                <i className={styles[`c_${k}`]} />
                {STATE_LABEL[k]}
              </span>
            ))}
          </div>
          <p className={styles.note} data-testid="health-jobs-snapshot">
            {JOBS_SNAPSHOT}
          </p>
          <p className={styles.note}>
            {o?.jobs.outcomes_recorded_since ? `Runs before ${fmt(o.jobs.outcomes_recorded_since)} recorded only success or failure; "nothing new" and "partial" are distinguished from then on. ` : ""}A
            completed run is not necessarily new intelligence.
          </p>
          {overdueAction && (
            <p className={styles.note}>
              <b>{d.overdue} job(s) overdue.</b>{" "}
              <DeferredAction reason={NOT_PORTED.runner} testId="health-run-overdue" noteTestId="health-run-overdue-note">
                Run overdue now
              </DeferredAction>
            </p>
          )}
        </section>

        <section className={styles.panel} id="hp-spend" aria-labelledby="hp-spend-h" data-testid="health-spend">
          <div className={styles.sh}>
            <h2 id="hp-spend-h">Model spending</h2>
            <span className={styles.d}>US$ per day · last 30 days · general model budget</span>
          </div>
          {o ? <SpendChart byDay={o.models.spend_by_day} days={days30} /> : <div className={styles.empty}>{oLoading ? "Loading spend…" : "Spend history unavailable."}</div>}
          <div className={styles.meters}>
            <div className={styles.pool} data-testid="pool-general">
              <h4>General model budget</h4>
              <div className={styles.pd}>triage, analysis, news — every model in the table below</div>
              {([["Today", d.spend.day, d.spend.limits.daily_usd], ["Week", d.spend.week, d.spend.limits.weekly_usd], ["Month", d.spend.month, d.spend.limits.monthly_usd]] as const).map(([l, v, c]) => (
                <Meter key={l} label={l} v={v} cap={c} />
              ))}
              {d.spend.kill_switch && <div className={styles.pd}>Paid model calls are switched off ({d.spend.kill_switch}).</div>}
            </div>
          </div>
        </section>
      </div>

      <section className={styles.panel} id="hp-models" aria-labelledby="hp-models-h" data-testid="health-models">
        <div className={styles.sh}>
          <h2 id="hp-models-h">Models</h2>
          <span className={styles.d}>every model Project Zero actually called (inference ledger) · select a row for errors</span>
        </div>
        {!o?.models.rows.length ? (
          <div className={styles.empty}>{oLoading ? "Loading…" : "No model call recorded yet."}</div>
        ) : (
          <div className={styles.tw}>
            <table className={styles.tbl}>
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Used for</th>
                  <th className={styles.num}>Calls · 7 d</th>
                  <th className={styles.num}>Success · 7 d</th>
                  <th className={styles.num}>Median latency</th>
                  <th>Last success</th>
                  <th className={styles.num}>Cost · all time</th>
                  <th>Errors (all time)</th>
                </tr>
              </thead>
              <tbody>
                {o.models.rows.map((m) => {
                  const r = m.calls_7d ? m.ok_7d / m.calls_7d : null;
                  return (
                    <tr key={m.model} className={styles.rowb} tabIndex={0} onClick={() => setDetail({ kind: "model", m })} onKeyDown={(e) => e.key === "Enter" && setDetail({ kind: "model", m })} data-model={m.model}>
                      <td>
                        <div className={styles.mn}>{shortModel(m.model)}</div>
                        <div className={styles.ms}>{m.provider}</div>
                      </td>
                      <td className={styles.ms}>{m.roles.join(", ") || "—"}</td>
                      <td className={styles.num}>{m.calls_7d}</td>
                      <td className={styles.num}>{r == null ? <span className={styles.ms}>no calls</span> : <St m={[r >= 0.95 ? "ok" : r >= 0.8 ? "lim" : "bad", `${(100 * r).toFixed(0)}%`]} />}</td>
                      <td className={styles.num}>{m.p50_ms_7d ? `${(m.p50_ms_7d / 1000).toFixed(1)} s` : "—"}</td>
                      <td>{m.last_ok ? ago(m.last_ok, now) : "never"}</td>
                      <td className={styles.num}>{usd(m.usd, 3)}</td>
                      <td className={styles.ms}>{Object.entries(m.error_kinds).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", ") || "none"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className={styles.note}>
          Configured roles: {d.providers.map((p) => `${p.role} ${p.enabled ? shortModel(p.model) : "off"}${p.enabled && p.key === false ? " (key missing)" : ""}`).join(" · ")}. Models
          called under other configurations (e.g. shadow triage) appear here because the ledger records every call.
        </p>
      </section>

      <div className={styles.grid2}>
        <section className={styles.panel} id="hp-sources" aria-labelledby="hp-src-h" data-testid="health-source-status">
          <div className={styles.sh}>
            <h2 id="hp-src-h">Sources</h2>
            <span className={styles.d}>retrieval health · health is about retrieval, not volume</span>
          </div>
          <StackRow label="Deal Flow sources" n={`${fam.dealFlow.healthy} / ${fam.dealFlow.total}`} parts={[["healthy", fam.dealFlow.healthy, "var(--green)"], ["failing", fam.dealFlow.failing, "var(--dot-sand)"], ["never successful", fam.dealFlow.never, "var(--amber)"], ["disabled", fam.dealFlow.disabled, "var(--stone)"]]} />
          {fam.news && <StackRow label="News feeds" n={`${fam.news.healthy} / ${fam.news.healthy + fam.news.failing}`} parts={[["healthy", fam.news.healthy, "var(--green)"], ["failing", fam.news.failing, "var(--dot-sand)"]]} />}
          <div className={styles.legend}>
            <span>
              <i style={{ background: "var(--green)" }} />
              healthy
            </span>
            <span>
              <i style={{ background: "var(--dot-sand)" }} />
              failing
            </span>
            <span>
              <i style={{ background: "var(--amber)" }} />
              never successful
            </span>
            <span>
              <i style={{ background: "var(--stone)" }} />
              disabled
            </span>
          </div>
          <input className={styles.find} placeholder="Search sources needing attention…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search sources needing attention" />
          <div className={styles.tw}>
            <table className={styles.tbl} data-testid="health-attention">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Problem</th>
                  <th>Last success</th>
                  <th className={styles.num}>In a row</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {att2.length ? (
                  att2.map((s) => (
                    <tr key={s.id} className={styles.rowb} tabIndex={0} onClick={() => setDetail({ kind: "source", src: s })} onKeyDown={(e) => e.key === "Enter" && setDetail({ kind: "source", src: s })} data-testid="health-source-problem">
                      <td>
                        <div className={styles.mn}>{s.name.split(" (")[0]}</div>
                        <div className={styles.ms}>{s.state.toLowerCase().replace(/_/g, " ")}</div>
                      </td>
                      <td>
                        {s.repair?.external ? "External access restriction" : s.repair ? "Fixable on the Project Zero side" : "Failing"}
                        <div className={styles.ms}>{(s.last_error.match(/HTTP Error \d+/) || [s.last_error.split(":")[0]])[0]}</div>
                      </td>
                      <td>{s.last_ok ? fmt(s.last_ok, { day: "numeric", month: "short" }) : "never"}</td>
                      <td className={styles.num}>{s.failures_in_row}</td>
                      <td>{s.repair?.external ? <span className={styles.ms}>None — handled safely</span> : <St m={["warn", "Look at it"]} />}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className={styles.ms}>
                      {att.length ? "No source matches." : "No source needs attention."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className={styles.panel} id="hp-backups" aria-labelledby="hp-bk-h" data-testid="health-backup-status">
          <div className={styles.sh}>
            <h2 id="hp-bk-h">Data integrity &amp; backups</h2>
          </div>
          {!o ? (
            <div className={styles.empty}>{oLoading ? "Loading…" : "Unavailable."}</div>
          ) : (
            <>
              <div className={styles.bk}>
                <div>
                  <div className={styles.bkK}>Last backup</div>
                  <div className={styles.bkV}>{backups ? (lastBk ? fmt(lastBk.at) : "none yet") : "—"}</div>
                  <div className={styles.bkF}>
                    {backups ? (
                      lastBk ? (
                        `${ago(lastBk.at, now)} · ${(lastBk.bytes / 1e6).toFixed(1)} MB · checksum ${lastBk.checksum ? "✓" : "missing"}`
                      ) : (
                        "Back up from Diagnostics → Data integrity & backups."
                      )
                    ) : (
                      <Reason testId="health-backups-reason">{backupsWhy}</Reason>
                    )}
                  </div>
                </div>
                <div>
                  <div className={styles.bkK}>Last verified restore</div>
                  <div className={styles.bkV}>{backups ? (verified ? fmt(verified.restore_at) : "none yet") : "—"}</div>
                  <div className={styles.bkF}>{backups ? (verified ? `${verified.name} restored and checked` : "No backup has been restore-tested.") : <Reason>{backupsWhy}</Reason>}</div>
                </div>
                <div>
                  <div className={styles.bkK}>Integrity check</div>
                  <div className={styles.bkV}>
                    <St m={integrityMark} />
                  </div>
                  <div className={styles.bkF}>
                    {integrity ? (
                      <>
                        {integrity.files_checked ?? "?"} files · {fmt(integrity.checked_at, { hour: "2-digit", minute: "2-digit" })}
                      </>
                    ) : (
                      <Reason testId="health-integrity-reason">{integrityWhy}</Reason>
                    )}
                  </div>
                </div>
                <div>
                  <div className={styles.bkK}>Backups kept</div>
                  <div className={styles.bkV}>{backups ? backups.count : "—"}</div>
                  <div className={styles.bkF}>{backups ? backups.dir : <Reason>{backupsWhy}</Reason>}</div>
                </div>
              </div>
              {lastBk && !lastBk.restore_ok && (
                <p className={styles.note} data-testid="backup-not-verified">
                  <b className={styles.amber}>Latest backup not yet restore-tested.</b> A backup proves a copy exists; only a restore test proves it can be brought back
                  (Diagnostics → Data integrity &amp; backups → Test latest backup).
                </p>
              )}
              <h3 className={styles.h3} style={{ marginTop: 16 }}>
                Releases
              </h3>
              {releases ? (
                releases.length ? (
                  releases.slice(0, 3).map((r) => (
                    <div key={r.at} className={styles.rel}>
                      <b>{r.tag}</b>
                      <span className={styles.ms}>{(r.commit || "").slice(0, 7)}</span>
                      <span className="grow" />
                      <span className={styles.ms}>{fmt(r.at)}</span>
                    </div>
                  ))
                ) : (
                  <div className={styles.ms}>No release deployed to the background runtime yet.</div>
                )
              ) : (
                <div className={styles.ms}>
                  <Reason testId="health-releases-reason">{releasesWhy}</Reason>
                </div>
              )}
            </>
          )}
        </section>
      </div>

      <section aria-labelledby="hp-iss-h" className={styles.section} data-testid="health-issues">
        <div className={styles.sh}>
          <h2 id="hp-iss-h">Operational issues</h2>
          <span className={styles.d}>each issue appears once, in the group that says who handles it</span>
        </div>
        <div className={styles.issues}>
          {GROUPS.map(([g, t, desc]) => {
            const list = issues.filter((i) => i.group === g);
            const runNow = g === "auto" && overdueAction;
            return (
              <div key={g} className={cx(styles.ig, styles[`ig_${g}`])} data-testid={`issues-${g}`}>
                <h3>
                  {t}
                  <span className={styles.igN}>{list.length}</span>
                </h3>
                <div className={styles.gd}>{desc}</div>
                {list.map((i) => (
                  <button key={i.what} type="button" className={styles.it} onClick={() => setDetail({ kind: "issue", i })} data-testid="health-issue">
                    {asRole(i.what).replace(/ — handled safely, not bypassed/, "")}
                    <span className={styles.itDo}>{asRole(i.do)}</span>
                  </button>
                ))}
                {runNow && (
                  <div className={styles.runNow}>
                    <DeferredAction reason={NOT_PORTED.runner} testId="health-run-overdue" noteTestId="health-run-overdue-note">
                      Run overdue now
                    </DeferredAction>
                  </div>
                )}
                {!list.length && (g === "need" ? <div className={styles.clear}>✓ Nothing needs you right now.</div> : <div className={styles.ms}>None.</div>)}
              </div>
            );
          })}
        </div>
      </section>

      <section aria-labelledby="hp-diag-h" className={styles.section}>
        <div className={styles.sh}>
          <h2 id="hp-diag-h">Diagnostics</h2>
          <span className={styles.d}>every detail the page has always offered — one section open at a time</span>
        </div>
        <Diagnostics d={d} />
      </section>

      <Drawer open={!!detail} onClose={() => setDetail(null)} title={detailTitle(detail, d)} width={560}>
        {detail && <DetailBody detail={detail} d={d} now={now} />}
      </Drawer>
    </div>
  );
}
