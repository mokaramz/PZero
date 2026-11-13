import { DisclosureGroup } from "@/components/attention";
import { Disclosure } from "@/components/focus";
import { Badge, Callout, Stat, type Tone } from "@/components/ui";
import { plainSourceProblem, plainText } from "@/lib/activity";
import { JOBS_SNAPSHOT, ported, reasonOf } from "../model/deferred";
import { isPortedJob, JOB_NOT_PORTED, JOBS_LIVE, JOBS_UNPORTED, runnerLive, unportedJobs } from "../model/jobs";
import type { Health } from "../model/types";
import { Reason } from "./bits";
import { Hardening } from "./Hardening";
import { NewSources } from "./NewSources";

const COV: Record<string, Tone> = { HEALTHY: "green", PARTIAL: "amber", GAP: "red", UNKNOWN: "neutral" };
const usd = (n: number) => `$${n.toFixed(2)}`;

/** "feed: HTTPError: HTTP Error 403" → "feed — refused automated access — not bypassed" (no raw exception text). */
function plainSourceProblemLine(line: string): string {
  const [name, ...rest] = line.split(": ");
  return rest.length ? `${name} — ${plainSourceProblem(rest.join(": "))}` : line;
}

/**
 * Level 3: every diagnostic the System Health page has always offered — one section open at a time (ported from the
 * old `Diagnostics.tsx`, review 032a). What changed:
 * - Background jobs (032c, read from the payload): while the server sends the runner lock deferred, the old catch-up
 *   line ("… these catch up when the app opens …") is the snapshot line (decision e) and the lock's reason replaces
 *   "busy / idle" (d). With the real lock, the line says where the jobs run in the new app and the lock is the old
 *   "busy / idle" again. A job with `ported: false` says "not ported yet" in place of "overdue" or its next run;
 * - Build and self-check: deferred, each shows its reason (d); WATCH's failing page checks too (d);
 * - News: no "catch-up" promise when there is no refresh yet (revision 2);
 * - Sources → New sources and Data integrity & backups: the 032b panels, with no request (./NewSources, ./Hardening).
 */
export function Diagnostics({ d }: { d: Health }) {
  const lock = d.job_runner ? d.job_runner.lock : undefined;
  const held = ported(lock);
  const live = runnerLive(d);
  const unported = unportedJobs(d.jobs);
  const build = ported(d.build);
  const selfcheck = ported(d.selfcheck);
  const failingChecks = ported(d.watch.failing_checks);
  return (
    <section aria-label="Diagnostics" data-testid="health-details">
      <DisclosureGroup>
        <Disclosure title="At a glance" icon="pulse" hint={`${d.sources.counts.HEALTHY || 0}/${d.sources.sources.length} sources healthy`} testId="health-glance">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 14 }}>
            <Stat label="healthy sources" value={`${d.sources.counts.HEALTHY || 0}/${d.sources.sources.length}`} />
            <Stat label="waiting for machine triage" value={d.triage_pending} />
            <Stat label="research questions open" value={d.research.open || 0} />
            <Stat label="WATCH triggers to review" value={d.watch.open_triggers} />
            <Stat label="overdue background jobs" value={d.overdue} />
            <Stat label={`Model spend this month (cap ${usd(d.spend.limits.monthly_usd || 0)})`} value={usd(d.spend.month)} />
            <Stat label="Validation snapshots" value={d.validation.snapshots} />
          </div>
        </Disclosure>
        <Disclosure title="Sources" icon="list" hint={d.sources.rule} testId="health-sources">
          <div className="small faint">
            {Object.entries(d.sources.counts)
              .map(([k, v]) => `${k.toLowerCase().replace(/_/g, " ")} ${v}`)
              .join(" · ")}
          </div>
          {!d.sources.sources.some((s) => s.repair) && <div className="small">No source needs repair.</div>}
          <NewSources />
        </Disclosure>
        {d.coverage.available && d.coverage.priority && (
          <Disclosure title="Coverage of priority ecosystems" icon="globe" testId="health-coverage">
            <p className="small faint">
              What Project Zero can SEE in each ecosystem, per signal family — never a judgment of the ecosystem itself. Details on the Ecosystems page.
            </p>
            <div style={{ overflowX: "auto" }}>
              <table style={{ fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>Ecosystem</th>
                    {Object.entries(d.coverage.family_labels || {}).map(([k, v]) => (
                      <th key={k} title={v}>
                        {v.split(" / ")[0]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {d.coverage.priority.map((e) => (
                    <tr key={e.city}>
                      <td>
                        <b>{e.city}</b>
                      </td>
                      {Object.keys(d.coverage.family_labels || {}).map((f) => (
                        <td key={f}>
                          <Badge tone={COV[e.families[f] || "UNKNOWN"]}>{(e.families[f] || "UNKNOWN").toLowerCase()}</Badge>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Disclosure>
        )}
        <Disclosure title="Background jobs" icon="clock" hint={d.overdue ? `${d.overdue} overdue` : "on schedule"} testId="health-jobs">
          <p className="small faint" data-testid="health-jobs-note">
            {live ? JOBS_LIVE : JOBS_SNAPSHOT}
          </p>
          {live && unported.length > 0 && (
            <p className="small faint" data-testid="health-jobs-unported-note">
              {JOBS_UNPORTED}
            </p>
          )}
          {d.job_runner && (
            <p className="small" data-testid="health-job-runner">
              Job runner:{" "}
              {held ? (
                held.held ? (
                  `busy — ${held.source} (pid ${held.pid}) since ${held.since}${held.alive ? "" : " · process gone, recovered on the next run"}`
                ) : (
                  "idle"
                )
              ) : (
                <Reason>{reasonOf(lock)}</Reason>
              )}
              {(["background", "app", "cli"] as const)
                .filter((k) => d.job_runner?.runners[k])
                .map((k) => {
                  const r = d.job_runner!.runners[k];
                  return (
                    <span key={k}>
                      {" "}
                      · last {k === "cli" ? "manual" : k} run {(r.finished || r.at || "").slice(0, 16).replace("T", " ")}{" "}
                      {r.outcome === "skipped" ? "(skipped — another run was in progress)" : r.outcome ? `(${r.outcome.replace("_", " ")})` : ""}
                    </span>
                  );
                })}
            </p>
          )}
          <ul className="small">
            {d.jobs.map((j) => (
              <li key={j.id} data-testid="health-job" data-job-id={j.id} data-ported={isPortedJob(j) ? undefined : "false"}>
                <b>{j.label}</b> every {j.interval_h >= 48 ? `${Math.round(j.interval_h / 24)} days` : `${j.interval_h} h`} · last ok {j.last_ok || "never"} ·{" "}
                {!isPortedJob(j) ? (
                  <Badge tone="neutral" data-testid="health-job-not-ported">
                    {JOB_NOT_PORTED}
                  </Badge>
                ) : j.overdue ? (
                  <Badge tone="amber">overdue</Badge>
                ) : (
                  `next ${j.next_due}`
                )}{" "}
                {j.state !== "ok" && j.state !== "never_run" && <Badge tone="red">{j.state}</Badge>}
                {j.outcome_label && j.state === "ok" && (
                  <Badge tone={j.outcome === "budget_blocked" || j.outcome === "partial" || j.outcome === "waiting_external" ? "amber" : "neutral"}>{j.outcome_label}</Badge>
                )}
                {(j.fails_in_row ?? 0) >= 2 && <Badge tone="red">fails {j.fails_in_row}× in a row</Badge>}
                {j.source && <span className="faint"> · via {j.source === "cli" ? "manual run" : j.source}</span>}
                {j.last_note && <span className="faint"> — {plainText(j.last_note)}</span>}
                {j.error && j.state !== "ok" && <span className="faint"> · {plainText(j.error)}</span>}
              </li>
            ))}
          </ul>
        </Disclosure>
        <Disclosure title="Models and budget" icon="funding" hint={`${usd(d.spend.month)} this month`} testId="health-ai">
          <div className="small">
            Spend today {usd(d.spend.day)} / {usd(d.spend.limits.daily_usd || 0)} · this week {usd(d.spend.week)} / {usd(d.spend.limits.weekly_usd || 0)} · this month{" "}
            {usd(d.spend.month)} / {usd(d.spend.limits.monthly_usd || 0)}. Caps stop paid calls automatically and are never overridden by the system.
            {d.spend.kill_switch && <b> Paid model calls are switched off ({d.spend.kill_switch}).</b>}
          </div>
          <ul className="small">
            {d.providers.map((p) => (
              <li key={p.role}>
                <b>{p.role}</b>: {p.enabled ? `${p.provider} · ${p.model}` : "disabled"}{" "}
                {p.enabled && (p.key ? <Badge tone="green">key set</Badge> : <Badge tone="red">key missing</Badge>)}
              </li>
            ))}
          </ul>
        </Disclosure>
        <Disclosure title="News & Learning feeds" icon="news" testId="health-news">
          {d.news?.last_run ? (
            <div className="small">
              Last refresh {(d.news.last_run.completed_at || d.news.last_run.at).slice(0, 16).replace("T", " ")}
              {d.news.last_run.status && <b> · {d.news.last_run.status.toUpperCase()}</b>} · {d.news.last_run.sources_ok} feed(s) ok
              {d.news.last_run.sources_failed.length
                ? ` · ${d.news.last_run.sources_failed.length} failed (${d.news.last_run.sources_failed.map((f) => plainSourceProblemLine(f)).join("; ")})`
                : ""}{" "}
              · {d.news.last_run.new} new event(s) · {d.news.last_run.merged + d.news.last_run.duplicates_skipped} duplicate article(s) collapsed · {d.news.events} events stored ·{" "}
              {d.news.backcasts_pending} important stor{d.news.backcasts_pending === 1 ? "y" : "ies"} without a backcast · AI cost so far ${d.news.usd_total.toFixed(4)}. News
              failures never affect sourcing.
            </div>
          ) : (
            <div className="small faint">No news refresh yet — it runs from the News page.</div>
          )}
          {d.news?.sources && !d.news.sources.error && (
            <div className="small" data-testid="health-news-sources">
              <b>News sources:</b> {d.news.sources.feeds_healthy ?? 0}/{d.news.sources.sources ?? 0} healthy
              {d.news.sources.feeds_failing?.length ? ` · failing: ${d.news.sources.feeds_failing.join(", ")}` : ""}
              {d.news.sources.degraded?.length ? ` · degraded: ${d.news.sources.degraded.join(", ")}` : ""}
              {d.news.sources.probation?.length ? ` · on probation: ${d.news.sources.probation.join(", ")}` : ""}
              {d.news.sources.candidates?.length ? ` · new publication candidates: ${d.news.sources.candidates.join(", ")}` : ""} · {d.news.sources.benchmark_events ?? 0} material
              events measured (90 days) · last measured {d.news.sources.evaluated_at ? d.news.sources.evaluated_at.replace("T", " ").slice(0, 16) : "not yet"}. Details: News &amp;
              Learning → News sources.
            </div>
          )}
        </Disclosure>
        <Disclosure title="Data integrity & backups" icon="shield" testId="health-hardening">
          <Hardening />
        </Disclosure>
        <Disclosure title="Build, self-check & validation data" icon="layers" level={3} testId="health-build-d">
          {d.build &&
            (build ? (
              <p className="small faint" data-testid="health-build">
                Running build {build.commit} (v{build.version}) · started {build.started_at.replace("T", " ").slice(0, 16)} · interface built{" "}
                {(build.frontend.built_at || "?").replace("T", " ").slice(0, 16)}
                {build.frontend.commit ? ` from ${build.frontend.commit}` : ""}
              </p>
            ) : (
              <p className="small faint" data-testid="health-build">
                Running build: <Reason>{reasonOf(d.build)}</Reason>
              </p>
            ))}
          {d.selfcheck && (
            <p className="small faint" data-testid="health-selfcheck">
              Startup self-check:{" "}
              {selfcheck ? (
                selfcheck.running ? (
                  "running…"
                ) : selfcheck.at ? (
                  `${selfcheck.ok}/${selfcheck.total} subsystems OK at ${selfcheck.at.replace("T", " ").slice(0, 16)}` +
                  (selfcheck.degraded.length ? ` · DEGRADED: ${selfcheck.degraded.map((x) => x.name).join(", ")} (see the issues above)` : "")
                ) : (
                  "not run in this session"
                )
              ) : (
                <Reason>{reasonOf(d.selfcheck)}</Reason>
              )}
            </p>
          )}
          <Callout tone="blue" data-testid="health-validation-data">
            Validation data: {d.validation.snapshots} daily snapshot(s), last {d.validation.last_snapshot || "never"}, {d.validation.data_issues} data warning(s). WATCH:{" "}
            {d.watch.companies} company(ies),{" "}
            {failingChecks !== undefined ? `${failingChecks} failing page check(s).` : <Reason>{reasonOf(d.watch.failing_checks)}</Reason>}
          </Callout>
        </Disclosure>
      </DisclosureGroup>
    </section>
  );
}
