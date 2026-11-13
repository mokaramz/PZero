import { Link } from "react-router-dom";

import { asRole } from "@/lib/roles";
import { GROUPS, STATE_LABEL, activeSources, ago, groupOf, stateTone, usd } from "../model/dashboard";
import { JOBS_SNAPSHOT, NOT_PORTED } from "../model/deferred";
import type { Detail } from "../model/detail";
import { ERR_KIND, fmt } from "../model/format";
import { isPortedJob, JOB_NOT_PORTED, JOB_TEXT, runnerLive } from "../model/jobs";
import type { Health } from "../model/types";
import { KV, St } from "./bits";
import styles from "../Health.module.css";

/**
 * The detail drawer's body (ported from the old `HealthPage.tsx`). What changed: a background job's "Retry" and
 * "Downstream effect" no longer promise a run while no runner exists (revision 2) and the drawer shows the snapshot
 * line (decision e). With the live runner (032c, read from the payload), a ported job has the old texts again and an
 * unported one (`ported: false`) says it is not ported and that its history is the imported snapshot; a source no longer offers "Prepare repair research (Scout Bridge)" — that action is retired
 * (decision c), the diagnosis stays.
 */
export function DetailBody({ detail: x, d, now }: { detail: NonNullable<Detail>; d: Health; now: Date }) {
  if (x.kind === "node")
    return (
      <div data-testid="health-detail">
        <div className={styles.dLab}>
          {x.lane}
          {x.node.human ? " · a human decision" : x.node.external ? " · outside Project Zero" : ""}
        </div>
        <St m={x.node.mark} />
        <div className={styles.dSec}>
          <KV rows={x.node.details.map(([a, b]) => [a, asRole(b)])} />
        </div>
        {x.node.link && (
          <p className={styles.note}>
            <Link to={x.node.link}>Open {x.node.link.replace("/", "").split("?")[0].replace("-", " ")} →</Link>
          </p>
        )}
      </div>
    );
  if (x.kind === "runs") {
    const j = d.jobs.find((y) => y.id === x.jobId);
    const unported = !!j && !isPortedJob(j);
    const live = runnerLive(d) && !unported; // the old texts: the runner runs this job
    const snapshot = unported ? (runnerLive(d) ? JOB_TEXT.snapshotUnported : JOBS_SNAPSHOT) : live ? null : JOBS_SNAPSHOT;
    return (
      <div data-testid="health-detail">
        <div className={styles.dLab}>Background job</div>
        <KV
          rows={[
            ["Interval", j ? `${j.interval_h} h` : "—"],
            ["Next run", unported ? JOB_NOT_PORTED : j?.overdue ? "overdue" : fmt(j?.next_due)],
            ["Failures in a row", String(j?.fails_in_row ?? 0)],
            ["Retry", (j?.fails_in_row ?? 0) > 0 ? (live ? JOB_TEXT.retryLive : unported && runnerLive(d) ? JOB_TEXT.retryUnported : NOT_PORTED.runner) : "not needed"],
          ]}
        />
        {snapshot && (
          <p className={styles.note} data-testid="health-runs-snapshot">
            {snapshot}
          </p>
        )}
        <div className={styles.dSec}>
          <h4>Runs in this period ({x.runs.length})</h4>
          {x.runs.map((r) => (
            <div key={r.at} className={styles.runRow}>
              <div className={styles.runHead}>
                <St m={[stateTone(r.state), STATE_LABEL[r.state] ?? r.state]} />
                <span className="grow" />
                <span className={styles.ms}>
                  {fmt(r.at)} · {r.seconds ?? "?"} s · {r.source || "app"}
                </span>
              </div>
              <div className={styles.raw}>{r.note || "no note recorded"}</div>
            </div>
          ))}
        </div>
        {x.runs.some((r) => r.state === "partial" || r.state === "failed" || r.state === "budget_blocked") && (
          <div className={styles.dSec}>
            <h4>Downstream effect</h4>
            <p className={styles.note}>
              {live
                ? JOB_TEXT.downstreamLive
                : unported && runnerLive(d)
                  ? JOB_TEXT.downstreamUnported
                  : "Work that did not complete is not run again until the background-job runner is ported; nothing already stored was changed. Spending caps are never overridden."}
            </p>
          </div>
        )}
      </div>
    );
  }
  if (x.kind === "source") {
    const s = x.src;
    return (
      <div data-testid="health-detail">
        <St m={s.repair?.external ? ["lim", "External limitation — no action required"] : ["warn", "Fixable on the Project Zero side"]} />
        <div className={styles.dSec}>
          <KV
            rows={[
              ["In plain words", s.repair?.cause ?? "—"],
              ["What to do", s.repair?.suggestion ?? "—"],
              ["Last success", s.last_ok ? fmt(s.last_ok) : "never"],
              ["Failures in a row", String(s.failures_in_row)],
              ["Candidates found so far", String(s.candidates)],
              ["Last useful discovery", s.last_useful_discovery || "—"],
              ["Impact on Project Zero", `One of ${activeSources(d)} active Deal Flow sources; the others keep working.`],
            ]}
          />
        </div>
        <div className={styles.dSec}>
          <h4>Diagnostic detail</h4>
          <div className={styles.raw}>
            {s.last_error.slice(0, 400)}
            {"\n"}
            {s.url}
          </div>
        </div>
        <p className={styles.note}>Project Zero never tries to get around an access restriction.</p>
      </div>
    );
  }
  if (x.kind === "model") {
    const m = x.m;
    return (
      <div data-testid="health-detail">
        <div className={styles.dLab}>Model · {m.provider}</div>
        <KV
          rows={[
            ["Identifier", m.model],
            ["Used for", m.roles.join(", ") || "—"],
            ["All calls", `${m.calls} · ${m.ok} ok · ${m.errors} errors · ${m.cache_hits} cache hits · ${m.blocked} budget-blocked`],
            ["Last 7 days", `${m.ok_7d} of ${m.calls_7d} ok`],
            ["Median latency (7 d)", m.p50_ms_7d ? `${(m.p50_ms_7d / 1000).toFixed(1)} s` : "—"],
            ["Last success", m.last_ok ? `${fmt(m.last_ok)} (${ago(m.last_ok, now)})` : "never"],
            ["Last error", fmt(m.last_error)],
            ["Cost (all time)", usd(m.usd, 4)],
          ]}
        />
        <div className={styles.dSec}>
          <h4>Errors by kind</h4>
          {Object.keys(m.error_kinds).length ? (
            Object.entries(m.error_kinds).map(([k, n]) => (
              <div key={k} className={styles.errRow}>
                {n} × <b>{k}</b> — {ERR_KIND[k] ?? "see the inference ledger"}
              </div>
            ))
          ) : (
            <div className={styles.ms}>No errors recorded.</div>
          )}
        </div>
      </div>
    );
  }
  const i = x.i;
  return (
    <div data-testid="health-detail">
      <div className={styles.dLab}>{GROUPS.find((g) => g[0] === groupOf(i))?.[1]}</div>
      <KV rows={[["What", asRole(i.what)], ["What to do", asRole(i.do)], ["Severity", i.level === "warn" ? "needs attention" : "information only"]]} />
    </div>
  );
}
