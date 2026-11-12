import { useState } from "react";

import { Async, Badge, Button, Segmented } from "@/components/ui";
import { useEvaluateSources, useNewsSources } from "../api";
import {
  authorityLine,
  biasLine,
  collecting,
  coverageLine,
  DEFAULT_WINDOW,
  earlyLine,
  fmtAt,
  originalityLine,
  pct,
  ranked,
  relevanceLine,
  sourceMeta,
  speedLine,
  statusTone,
  technical,
  uniqueLine,
  WINDOWS,
} from "../model/sources";
import type { SourceRow as Src, Window } from "../model/types";
import styles from "../News.module.css";

/**
 * Which news sources are best FOR WHICH PURPOSE — measured, never one universal score. The window is local state and
 * becomes `GET news/sources?window=`. "Re-measure now" runs the source evaluation (028c) inside its request; when it
 * returns, every window is read again.
 */
export function NewsSources() {
  const [win, setWin] = useState<Window>(DEFAULT_WINDOW);
  const q = useNewsSources(win);
  const evaluate = useEvaluateSources();
  return (
    <div className={styles.list} data-testid="news-sources">
      <div className={styles.row} style={{ marginTop: 0 }}>
        <Segmented value={win} onChange={setWin} options={WINDOWS} label="Time window" />
        <Button size="sm" variant="ghost" busy={evaluate.isPending} onClick={() => evaluate.mutate()}>
          Re-measure now
        </Button>
      </div>
      <Async q={q} label="Measuring sources…">
        {(d) => (
          <>
            <div className={styles.introCard}>
              <div className={styles.kicker}>How to read this</div>
              <p>
                A news source has several jobs: some confirm facts, some cover Europe broadly, some see local companies months earlier. Each job is measured
                separately on <b>{d.benchmark_events}</b> material European events in this window. {d.note}
              </p>
            </div>

            <div className={styles.bestGrid} data-testid="news-sources-best">
              {ranked(d.best).map((b) => (
                <div key={b.id} className={styles.introCard}>
                  <div className={styles.kicker}>{b.label}</div>
                  <b>{b.leader.source}</b> <Badge>{b.confidence?.toLowerCase()}</Badge>
                  <p className={styles.faint}>{b.leader.why}</p>
                  {b.runner_up && <p className={styles.faint}>Next: {b.runner_up.source}</p>}
                  {b.warning && <p className={styles.faint}>⚠ {b.warning}</p>}
                </div>
              ))}
              {collecting(d.best).map(([need, labels]) => (
                <div key={need} className={styles.introCard}>
                  <div className={styles.kicker}>Best for {labels.join(" · ")}</div>
                  <Badge>COLLECTING DATA</Badge>
                  <p className={styles.faint}>{need}</p>
                </div>
              ))}
            </div>

            <div className={styles.check} data-testid="news-sources-bias">
              <b>How fair is this benchmark?</b> {biasLine(d.bias)}
              <ul className={styles.sources}>
                {d.bias.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>

            <div className={styles.card} data-testid="news-sources-missing">
              <div className={styles.kicker}>Are we missing a publication?</div>
              {d.candidates.length > 0 && (
                <p>
                  Being tested by the source network:{" "}
                  {d.candidates.map((c) => (
                    <span key={c.id}>
                      <b>{c.name}</b> <Badge tone={c.state === "PROBATION" ? "amber" : "neutral"}>{c.state}</Badge>{" "}
                    </span>
                  ))}
                  — decide in System health → New sources.
                </p>
              )}
              {d.missing.length ? (
                <ul className={styles.sources}>
                  {d.missing.slice(0, 6).map((m) => (
                    <li key={m.domain}>
                      <b>{m.name}</b> — seen on {m.n} material event(s){" "}
                      {m.database ? (
                        <span className={styles.faint}>(startup database, not a news source)</span>
                      ) : m.ready ? (
                        <Badge tone="amber">handed to source network</Badge>
                      ) : (
                        <span className={styles.faint}>(needs 3 before it becomes a candidate)</span>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className={styles.faint}>No unmonitored publication shows up repeatedly yet.</p>
              )}
            </div>

            {d.declining.length > 0 && (
              <div className={styles.card} data-testid="news-sources-declining">
                <div className={styles.kicker}>Declining sources</div>
                <ul className={styles.sources}>
                  {d.declining.map((x) => (
                    <li key={x.name}>
                      <b>{x.name}</b>: {x.reasons.join("; ")}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className={styles.kicker}>All sources</div>
            {d.sources.map((s) => (
              <SourceRow key={s.name} s={s} scopes={d.scopes} />
            ))}
            <p className={styles.faint}>Last measured: {fmtAt(d.evaluated_at)} (daily after the news refresh).</p>
          </>
        )}
      </Async>
    </div>
  );
}

function SourceRow({ s, scopes }: { s: Src; scopes: Record<string, string> }) {
  const [open, setOpen] = useState(false);
  const tech = technical(s);
  return (
    <div className={styles.card} data-testid="news-source-row">
      <div className={styles.chips}>
        <b>{s.name}</b>
        <Badge tone={statusTone(s.status)}>{s.status.toLowerCase()}</Badge>
        {s.roles.map((r) => (
          <Badge key={r.role} tone="blue">
            {r.role.toLowerCase()}
          </Badge>
        ))}
        <span className={styles.meta}>{sourceMeta(s, scopes)}</span>
      </div>
      <p className={styles.more}>
        <b>Best use:</b> {s.best_use}
        {s.not_for && (
          <>
            {" "}
            · <b>Not designed for:</b> {s.not_for}
          </>
        )}
      </p>
      <Button size="sm" variant="ghost" onClick={() => setOpen(!open)}>
        {open ? "Hide details" : "Details"}
      </Button>
      {open && (
        <ul className={styles.sources} data-testid="news-source-detail">
          <li>
            <b>Coverage</b> (of events other sources reported): {coverageLine(s, scopes)}
          </li>
          <li>
            <b>Speed</b> behind the first report: {speedLine(s)}
          </li>
          <li>
            <b>Early signal</b>: {earlyLine(s)}
          </li>
          <li>
            <b>Unique value</b>: {uniqueLine(s)}
          </li>
          <li>
            <b>Relevance</b>: {relevanceLine(s)} · <b>noise</b> {pct(s.articles.noise)}
          </li>
          <li>
            <b>Originality</b> ({s.originality.confidence}): {originalityLine(s)}
          </li>
          <li>
            <b>Authority</b>: {authorityLine(s)}
          </li>
          <li data-testid={tech.deferred ? "news-source-health-deferred" : undefined}>
            <b>Technical</b>: {tech.text}
          </li>
          {s.hypothesis && (
            <li>
              <b>Hypothesis to test</b>: {s.hypothesis}
            </li>
          )}
          {s.status_reasons.length > 0 && (
            <li>
              <b>Why {s.status.toLowerCase()}</b>: {s.status_reasons.join("; ")}
            </li>
          )}
          {s.limitations.length > 0 && <li className={styles.faint}>Limits: {s.limitations.join("; ")}</li>}
        </ul>
      )}
    </div>
  );
}
