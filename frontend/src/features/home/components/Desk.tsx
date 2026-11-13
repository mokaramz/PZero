import { Link, useNavigate } from "react-router-dom";

import { StatusChip } from "@/components/focus";
import { Icon } from "@/components/Icon";
import { sentence, short } from "@/features/today/missions";
import { cx } from "@/lib/format";
import { useNewKeys } from "@/lib/motion";
import { asRole } from "@/lib/roles";
import { att, attWhy } from "../model/attention";
import { candidateLink, companyLink, deskView, type DeskInput, tierL, timeOf } from "../model/desk";
import { contextLine, greeting } from "../model/greeting";
import { Card } from "./Card";
import { DecisionFlow } from "./DecisionFlow";
import { Machine } from "./Machine";
import { Tile } from "./Tile";
import { UpcomingEvent } from "./UpcomingEvent";
import styles from "../Home.module.css";

/**
 * The desk once `home` (and the inbox) have loaded: the brief with the flow graphic, four tiles, Priority missions,
 * Manager decisions and the best opportunity, then the promising signals, the upcoming event and the recent activity,
 * and the machine work folded. Every action opens the specialist page; nothing here is sent.
 */
export function Desk({ onWeekly, ...input }: DeskInput & { onWeekly: () => void }) {
  const navigate = useNavigate();
  const { h, ib } = input;
  const { C, news, sig, human, shownMissions, gated, awaiting, pr, prSig, att6, activity, done, warn, summary } = deskView(input);
  const thn = (t: string) => ib?.themes?.[t] ?? t;
  const pg = h.progress ?? {};
  const now = new Date();
  const newSignals = useNewKeys(att6.map((c) => c.id));
  const newActivity = useNewKeys(activity.map((a) => a.key));

  return (
    <div className={styles.desk}>
      <section className={styles.brief} aria-label="Executive brief">
        <div className={styles.briefText}>
          <div className={styles.eyebrow} data-testid="desk-context">
            {contextLine(now)}
          </div>
          <h1 className={styles.hello}>{greeting(now)}</h1>
          <p className={styles.lead} data-testid="desk-summary">
            {summary}
          </p>
        </div>
        <DecisionFlow candidates={C} review={human.length} manager={gated.length} decided={sig.length} />
      </section>

      <div className={styles.tiles} role="list" aria-label="Orientation">
        <Tile icon="layers" n={human.length} label={human.length === 1 ? "Priority mission" : "Priority missions"} to="/today" tone="blue" />
        <Tile icon="approval" n={gated.length} label={gated.length === 1 ? "Manager decision" : "Manager decisions"} to="/conviction?seg=gated" tone="cocoa" />
        <Tile icon="people" n={awaiting.length} label="Awaiting founder reply" to="/conviction" tone="slate" />
        <Tile icon="funding" n={news.length} label="Candidates to decide" to="/deal-flow" tone="forest" />
      </div>

      <div className={styles.row1}>
        <Card title="Priority missions" icon="target" sub="What needs your judgment" label="Priority missions" testId="desk-missions" className={styles.missionsCard} tone="focus">
          {shownMissions.length ? (
            <ol className={styles.list}>
              {shownMissions.map((r) => (
                <li key={r.key} className={styles.mRow} data-testid="desk-job">
                  <div className={styles.mName}>
                    <b>{asRole(r.name)}</b>
                    <span>{asRole(r.reason)}</span>
                  </div>
                  <div className={styles.mUnknown}>
                    {r.unknown && (
                      <>
                        <em>Top unknown</em>
                        <span>{asRole(r.unknown)}</span>
                      </>
                    )}
                  </div>
                  <StatusChip tone={r.tone}>{asRole(r.state)}</StatusChip>
                  <Link className={styles.rowBtn} to={r.to}>
                    {r.action} <Icon name="arrow" size={12} />
                  </Link>
                </li>
              ))}
            </ol>
          ) : (
            <p className={styles.none}>Nothing waits on your judgment.</p>
          )}
          {human.length > shownMissions.length && (
            <Link className={styles.more} to="/today">
              View remaining {human.length - shownMissions.length} <Icon name="arrow" size={12} />
            </Link>
          )}
        </Card>

        <Card title="Manager decisions" icon="approval" sub="Blocked until the Manager answers" label="Manager decisions" testId="desk-manager" tone="decision">
          {gated.length ? (
            <ol className={styles.list}>
              {gated.slice(0, 3).map((e) => (
                <li key={e.slug} className={styles.dRow}>
                  <div className={styles.mName}>
                    <b>{e.company}</b>
                    <span>{e.twin ? `Possible overlap with ${e.twin}` : "Possible portfolio conflict"}</span>
                  </div>
                  <div className={styles.dFoot}>
                    <StatusChip tone="attention">Decision due</StatusChip>
                    <Link className={styles.rowBtn} to={companyLink(e.slug)}>
                      Open <Icon name="arrow" size={12} />
                    </Link>
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <p className={styles.none}>Nothing waits on the Manager.</p>
          )}
          {gated.length > 3 && (
            <Link className={styles.more} to="/conviction?seg=gated">
              View all {gated.length} <Icon name="arrow" size={12} />
            </Link>
          )}
        </Card>

        <section className={cx(styles.card, styles.best)} aria-label="Best opportunity" data-testid="desk-best">
          <div className={styles.cardHead}>
            <Icon name="signal" size={18} className={styles.headIcon} />
            <h2>Best opportunity</h2>
          </div>
          {pr ? (
            <>
              <div className={styles.bestTop}>
                <button type="button" className={styles.bestName} onClick={() => navigate(companyLink(pr.slug))}>
                  {pr.company}
                </button>
                <StatusChip tone={pr.verified ? "progress" : "attention"}>{pr.verified ? "Verified" : "Provisional"}</StatusChip>
              </div>
              {prSig?.one_liner && <p className={styles.bestThesis}>{short(prSig.one_liner, 16)}</p>}
              <dl className={styles.bestFacts}>
                <div>
                  <dt>State</dt>
                  <dd>{asRole(sentence(pr.op?.status || pr.verdict))}</dd>
                </div>
                <div>
                  <dt>Signal</dt>
                  <dd>{pr.verified ? `Verified ${pr.score}` : `Provisional ${pr.score} → Radar high-confidence if verified ≥ 65`}</dd>
                </div>
              </dl>
              {pr.next && <p className={styles.bestNext}>Your move: {asRole(pr.next)}</p>}
              <Link className={styles.primary} to={companyLink(pr.slug)}>
                Open the case <Icon name="arrow" size={13} />
              </Link>
              <Contours />
            </>
          ) : (
            <p className={styles.none}>No clear leader yet — no Conviction company stands out on the current evidence.</p>
          )}
        </section>
      </div>

      <div className={styles.row2}>
        <Card
          title="Promising signals"
          icon="signal"
          sub="Best of the attention queue"
          label="Promising signals"
          testId="desk-signals"
          tone="positive"
          right={
            <Link className={styles.headLink} to="/deal-flow">
              See all signals <Icon name="arrow" size={12} />
            </Link>
          }
        >
          {att6.length ? (
            <ol className={styles.list}>
              {att6.map((c) => (
                <li key={c.id} className={newSignals.has(c.id) ? "pz-arrive" : undefined}>
                  <button type="button" className={styles.sRow} onClick={() => navigate(candidateLink(c.id))}>
                    <StatusChip tone={c.discovery_tier === "pre_company" ? "progress" : "neutral"}>{tierL(c)}</StatusChip>
                    <b className={styles.sName}>{c.name}</b>
                    <span className={styles.sTheme}>{(c.themes ?? []).slice(0, 2).map(thn).join(" · ")}</span>
                    <span className={styles.sScore} title={attWhy(c)}>
                      {c.attention_v2?.final != null ? `F ${c.attention_v2.final}` : `att ${att(c)}`}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            <p className={styles.none}>Nothing in the attention queue yet — Find New Candidates in Deal Flow.</p>
          )}
        </Card>

        <UpcomingEvent be={h.best_event} />

        <Card title="Recent activity" icon="pulse" label="Recent activity" testId="desk-activity" tone="activity">
          {activity.length ? (
            <ol className={styles.timeline}>
              {activity.slice(0, 4).map((a) => (
                <li key={a.key} className={newActivity.has(a.key) ? "pz-arrive" : undefined}>
                  <button type="button" className={styles.tRow} onClick={() => navigate(a.to)}>
                    <span className={styles.tTime}>{timeOf(a.t)}</span>
                    <span className={styles.tBody}>
                      <b>{a.title}</b>
                      <span>{a.sub}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            <p className={styles.none}>No recent activity.</p>
          )}
          <Link className={styles.more} to="/deal-flow">
            See the full signal flow <Icon name="arrow" size={12} />
          </Link>
        </Card>
      </div>

      <Machine ib={ib} progress={pg} news={news} C={C} done={done} warn={warn} onWeekly={onWeekly} />
    </div>
  );
}

/** Decorative topographic contours for the Best opportunity card (no data — purely a quiet surface texture). */
function Contours() {
  return (
    <svg className={styles.contours} viewBox="0 0 200 90" aria-hidden data-decorative="true">
      <path d="M0 80 C40 62 70 70 104 52 S170 30 200 34" />
      <path d="M0 88 C46 72 78 80 112 62 S176 44 200 48" />
      <path d="M20 90 C60 80 92 88 124 72 S180 58 200 62" />
    </svg>
  );
}
