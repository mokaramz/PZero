import { useId } from "react";

import { Badge, Panel, type Tone } from "@/components/ui";
import { NOT_PORTED } from "../model/deferred";
import { DeferredControl, Reason } from "./bits";

type Check = { id: string; label: string; ok: boolean; detail: string; hard: boolean };
type Via = { kind: string; ref: string; company: string | null; evidence_url?: string; signal_date?: string; headline?: string };
type NewsPerf = {
  kind: "news";
  runs: number;
  fetch_reliability: number | null;
  articles: number;
  relevant: number;
  unique_events: number;
  first_reports: number;
  noise_rate: number | null;
  syndicated_rate: number | null;
  early_companies: number;
};
type Perf = {
  kind?: undefined;
  scans: number;
  fetch_reliability: number | null;
  candidates: number;
  unique: number;
  noise_rate: number | null;
  precision: number | null;
  machine_keep_research: number;
  mohamed_accepted: number;
  strong: number;
  median_lead_days: number | null;
};
export type Cand = {
  id: string;
  url: string;
  name: string;
  family: string;
  state: string;
  why_interesting: string;
  discovered_via: Via[];
  validation: { at: string; quality: string; checks: Check[] } | null;
  performance: Perf | NewsPerf | null;
  eligibility: { eligible: boolean; requirements: Array<{ ok: boolean; text: string }> } | null;
  early_examples: Array<{ company: string; signal_date: string; lead_days: number | null }>;
};
/** The 032b `source_network` read, when it exists. */
export type Net = {
  candidates: Cand[];
  counts: Record<string, number>;
  monitored_evidence: Array<{ name: string; url: string; evidence: Via[] }>;
  alpha_sources: Array<{ source_id: string; source: string; early_catches: number; strong: number; discoveries: number; note: string }>;
  coverage_gaps: Array<{ ecosystem: string; family: string; label: string; state: string; potential_sources: string[] }>;
  note: string;
};

const STATE: Record<string, Tone> = {
  DISCOVERED: "neutral",
  VALIDATING: "blue",
  REJECTED: "red",
  PROBATION: "amber",
  TRUSTED: "green",
  DEGRADED: "amber",
  DISABLED: "neutral",
};
const VIA: Record<string, string> = { news_backcast: "News backcast", news_source: "News source intelligence", miss_audit: "Miss audit", manual: "Added by you" };
const pct = (n: number | null) => (n === null ? "—" : `${Math.round(n * 100)}%`);

/** One candidate's decisions (old order and labels), each deferred with the row's visible reason. */
function Decisions({ c }: { c: Cand }) {
  const note = useId();
  const why = NOT_PORTED.sourceNetwork;
  const probation = c.state === "PROBATION";
  const validate = ["DISCOVERED", "REJECTED"].includes(c.state);
  const reject = ["DISCOVERED", "PROBATION", "DEGRADED", "TRUSTED"].includes(c.state);
  if (!probation && !validate && !reject) return null;
  return (
    <>
      <div className="row" style={{ marginTop: 4 }} data-testid="source-decisions">
        {probation && (
          <>
            <DeferredControl reason={why} noteId={note} variant="primary">
              Promote to trusted
            </DeferredControl>
            <DeferredControl reason={why} noteId={note}>
              Keep in probation
            </DeferredControl>
          </>
        )}
        {validate && (
          <DeferredControl reason={why} noteId={note}>
            {c.state === "REJECTED" ? "Validate again" : "Validate now"}
          </DeferredControl>
        )}
        {reject && (
          <DeferredControl reason={why} noteId={note} variant="ghost">
            Reject
          </DeferredControl>
        )}
      </div>
      <Reason id={note}>{why}</Reason>
    </>
  );
}

/**
 * Adaptive source network: new sources are proposed and tested; only the Smooth Operator promotes one to TRUSTED. The
 * old panel read `source_network` and wrote `source_network_run` and `source_decision`; all of them are the hardening
 * port (032b). Until then the page makes NO request (`net` is undefined): the panel shows the reason in place of its
 * data, and "Look for new sources" and the source decisions keep their place and label, disabled with that visible
 * reason (decision h). The retired Scout 00 evidence kind is dropped from the "Found through" names (decision c).
 */
export function NewSources({ net: d }: { net?: Net }) {
  const runNote = useId();
  const why = NOT_PORTED.sourceNetwork;
  return (
    <Panel
      title="New sources"
      data-testid="health-new-sources"
      aside={
        <DeferredControl reason={why} noteId={runNote} testId="source-network-run">
          Look for new sources
        </DeferredControl>
      }
    >
      <p className="small">
        <Reason id={runNote} testId="new-sources-reason">
          {why}
        </Reason>
      </p>
      {d && (
        <>
          <p className="small faint">
            Where do exceptional companies appear before everyone else knows? Project Zero proposes sources it saw in evidence (news backcasts, miss audits), tests them
            (safe, public, original, early-signal, not spam) and runs the good ones on <b>probation</b>. {d.note}
          </p>
          <div className="small faint" data-testid="new-sources-counts">
            {Object.entries(d.counts)
              .map(([k, v]) => `${k.toLowerCase()} ${v}`)
              .join(" · ") || "No source candidates yet."}
          </div>
        </>
      )}
      {d?.candidates.map((c) => (
        <div key={c.id} className="small" style={{ borderTop: "1px solid var(--hair)", padding: "8px 0" }} data-testid="new-source">
          <div className="row">
            <Badge tone={STATE[c.state]}>{c.state}</Badge> <b>{c.name}</b>
            <a href={c.url} target="_blank" rel="noreferrer" className="faint">
              {c.url}
            </a>
          </div>
          <div>
            <b>Found through:</b> {[...new Set(c.discovered_via.map((v) => VIA[v.kind] || v.kind))].join(", ")}
            {c.discovered_via[0]?.company && <> ({c.discovered_via.map((v) => v.company).filter(Boolean).slice(0, 3).join(", ")})</>} · <b>type:</b>{" "}
            {c.family.replace(/_/g, " ")}
            {c.validation && <> · quality: {c.validation.quality.toLowerCase()}</>}
          </div>
          {c.why_interesting && (
            <div>
              <b>Why interesting:</b> {c.why_interesting}
            </div>
          )}
          {c.early_examples.length > 0 && (
            <div>
              <b>Early-signal examples:</b>{" "}
              {c.early_examples.map((e) => `${e.company}${e.signal_date ? ` (${e.signal_date}${e.lead_days !== null ? `, ${e.lead_days} days before the news` : ""})` : ""}`).join("; ")}
            </div>
          )}
          {c.validation && (
            <details>
              <summary>Validation checks</summary>
              <ul>
                {c.validation.checks.map((x) => (
                  <li key={x.id}>
                    {x.ok ? "✓" : x.hard ? "✗" : "○"} {x.label}
                    {x.detail && <span className="faint"> — {x.detail}</span>}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {c.performance?.kind === "news" && (
            <div>
              <b>Probation evidence (news feed):</b> {c.performance.runs} run(s) · fetch {pct(c.performance.fetch_reliability)} · {c.performance.articles} articles ·{" "}
              {c.performance.relevant} relevant · {c.performance.unique_events} unique material events · {c.performance.first_reports} first reports ·{" "}
              {c.performance.early_companies} early companies · noise {pct(c.performance.noise_rate)} · syndicated {pct(c.performance.syndicated_rate)}
            </div>
          )}
          {c.performance && c.performance.kind !== "news" && (
            <div>
              <b>Probation evidence:</b> {c.performance.scans} scan(s) · fetch {pct(c.performance.fetch_reliability)} · {c.performance.unique} unique companies of{" "}
              {c.performance.candidates} · noise {pct(c.performance.noise_rate)} · entity precision {pct(c.performance.precision)} · machine KEEP/RESEARCH{" "}
              {c.performance.machine_keep_research} · your decisions {c.performance.mohamed_accepted} · strong {c.performance.strong}
              {c.performance.median_lead_days !== null && <> · median lead {c.performance.median_lead_days} days</>}
            </div>
          )}
          {c.eligibility && (
            <div>
              {c.eligibility.eligible ? <Badge tone="green">eligible for TRUSTED</Badge> : <Badge>not eligible yet</Badge>}{" "}
              <span className="faint">{c.eligibility.requirements.map((r) => `${r.ok ? "✓" : "✗"} ${r.text}`).join(" · ")}</span>
            </div>
          )}
          <Decisions c={c} />
        </div>
      ))}
      {d && d.alpha_sources.length > 0 && (
        <div className="small" style={{ borderTop: "1px solid var(--hair)", paddingTop: 8 }} data-testid="sourcing-alpha">
          <b>Sources demonstrating sourcing alpha</b> (evidence only — no weight is changed):
          <ul>
            {d.alpha_sources.map((a) => (
              <li key={a.source_id}>
                {a.source}: {a.early_catches} early catch(es) in the news · {a.strong} strong outcome(s) · {a.discoveries} discoveries
              </li>
            ))}
          </ul>
        </div>
      )}
      {d && d.coverage_gaps.length > 0 && (
        <details className="small" style={{ borderTop: "1px solid var(--hair)", paddingTop: 8 }}>
          <summary>Coverage gaps and documented candidate sources ({d.coverage_gaps.length})</summary>
          <ul>
            {d.coverage_gaps.map((g) => (
              <li key={g.ecosystem + g.family}>
                {g.ecosystem} · {g.label}: {g.potential_sources.length ? g.potential_sources.join(", ") : <span className="faint">no evidence-based candidate yet</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {d && d.monitored_evidence.length > 0 && (
        <div className="small faint">
          Already monitored, new evidence attached: {d.monitored_evidence.map((m) => `${m.name} (${m.evidence.length})`).join(", ")}
        </div>
      )}
    </Panel>
  );
}
