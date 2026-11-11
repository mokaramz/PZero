import { Link } from "react-router-dom";

import { DeferredButton } from "@/components/Deferred";
import { Badge, Button } from "@/components/ui";
import { cx } from "@/lib/format";
import { NOT_PORTED } from "../model/deferred";
import type { EventRecord, EventsPayload, PeopleSlice, ScoutReport, WsigItem } from "../model/types";
import { audienceSignal, costLine, evFormat, ladderLevel, peopleIn } from "../model/eventUtil";
import { Unk, When } from "./When";
import { travelLine } from "./bits";
import { isPriorityEvent, priorityWhy, type Item } from "../model/workspace";
import styles from "../Events.module.css";

type Props = {
  e: EventRecord;
  ev: EventsPayload;
  people: PeopleSlice["people"];
  wsig: WsigItem[];
  homeCity: string;
  onWeekend: () => void;
};

const BAND = (v?: string) => (v === "HIGH" ? styles.bHigh : v === "MEDIUM" ? styles.bMed : styles.bNone);
const bandText = (v?: string) => (!v || v === "NOT ENOUGH INFORMATION" ? "not enough information" : v.toLowerCase());
const FACTOR: Record<string, string> = { founder: "Founder evidence", project_a: "Project A evidence", networking: "Networking evidence" };

function stateLabel(e: EventRecord): [string, string] {
  if (e.status === "planned") return ["Planned — GO", styles.labGo];
  if (e.status === "attended") return ["Attended", styles.labGo];
  if (e.status === "skipped") return ["Skipped", styles.labMute];
  if (isPriorityEvent(e)) return [`Priority · ${priorityWhy({ kind: "event", e } as Item)}`, styles.labPrio];
  if (e.eligibility?.tier === "NEEDS REVIEW") return ["Needs your verification", styles.labRv];
  if (e.eligibility?.tier === "REJECTED") return [`Not recommended · ${e.eligibility.label ?? ""}`, styles.labMute];
  return ["High-signal", styles.labGo];
}

/** Event details — one column: the facts on a dark card, then your decision, why it matters, verification, sources.
 *  Scores and the legacy ladder stay one fold away ("Evidence & scoring"). The decision, Verify, Edit and Debrief wait
 *  for the event writes port: they keep their place, disabled with the reason. */
export function EventDetail({ e, ev, people, wsig, homeCity, onWeekend }: Props) {
  const a = e.assessment ?? {};
  const w = wsig.find((x) => x.id === e.id);
  const ppl = peopleIn(people, e.city);
  const fmt = evFormat(e);
  // the old clock read, kept as it was: days from now to the stored start
  // oxlint-disable-next-line react/purity
  const days = e.start ? Math.round((new Date(e.start).getTime() - Date.now()) / 86_400_000) : null;
  const dims = ev.dims ?? {};
  const parts = e.score_parts ?? {};
  const ladderText = (k: string) => (dims[k]?.ladder ?? []).find((l) => l[0] === parts[k])?.[1] ?? "";
  const pill = (label: string, v: number | null | undefined, max: number, title: string) => {
    const [t, tone] = ladderLevel(v, max);
    return (
      <Badge key={label} tone={tone} className={styles.pill} title={`${title}${v != null ? ` · ${v} / ${max} on the existing ladder` : " · no ladder value on file"}`}>
        {label}: {t}
      </Badge>
    );
  };
  const [audLabel, audTone] = audienceSignal(e);
  const action = e.action ?? {};
  const [label, labelCls] = stateLabel(e);
  const tier = e.eligibility?.tier;

  return (
    <div className={styles.detail} data-testid="event-detail">
      <section className={styles.dFacts}>
        <span className={cx(styles.lab, styles.onDark, labelCls)}>{label}</span>
        <dl className={styles.dKv}>
          <dt>When</dt>
          <dd>
            <When e={e} />
            {e.when?.weekend && <span className={styles.dWk}> · weekend</span>}
          </dd>
          <dt>Where</dt>
          <dd>
            {[e.venue, e.place?.label || e.city].filter(Boolean).join(" · ") || <Unk>Location unknown</Unk>}
            {fmt && <span className={styles.dMut}> · {fmt}</span>}
            {e.travel_hours != null && <div className={styles.dMut}>{travelLine(e.travel_hours)}</div>}
          </dd>
          <dt>Organizer</dt>
          <dd>{e.organizer && e.organizer !== "UNKNOWN" ? e.organizer : <span className={styles.dMut}>not stated</span>}</dd>
          <dt>Type</dt>
          <dd>{e.type && e.type !== "UNKNOWN" ? ev.types[e.type] || e.type : <span className={styles.dMut}>not evidenced</span>}</dd>
          <dt>Price</dt>
          <dd>{costLine(e).toLowerCase()}</dd>
        </dl>
      </section>

      <aside className={styles.dDecision} aria-label="Decision">
        <div className={styles.goRow} role="group" aria-label="Your decision">
          <DeferredButton size="sm" variant={e.status === "planned" ? "primary" : "default"} aria-pressed={e.status === "planned"} reason={NOT_PORTED.status}>
            GO
          </DeferredButton>
          <DeferredButton size="sm" variant={e.status === "new" ? "primary" : "default"} aria-pressed={e.status === "new"} reason={NOT_PORTED.status}>
            MAYBE
          </DeferredButton>
          <DeferredButton size="sm" variant={e.status === "skipped" ? "danger" : "default"} aria-pressed={e.status === "skipped"} reason={NOT_PORTED.status}>
            SKIP
          </DeferredButton>
        </div>
        {action.state === "sold_out" ? (
          <Button size="sm" disabled>
            Sold out
          </Button>
        ) : action.state === "waitlist" ? (
          <a className={styles.btnLink} href={action.url} target="_blank" rel="noreferrer">
            Sold out — check waitlist ↗
          </a>
        ) : e.url ? (
          <a className={styles.btnLink} href={e.registration_url || e.url} target="_blank" rel="noreferrer">
            Register / details ↗
          </a>
        ) : null}
        <Button size="sm" variant="ghost" onClick={onWeekend}>
          Add to sourcing weekend
        </Button>
      </aside>

      <Sect title="Why it matters for scouting">
        {e.scout && (
          <div className={styles.dScout}>
            <div className={styles.dScoutHd}>
              Scout 00 · {[e.scout.p_class, e.scout.ev_class].filter(Boolean).join(" · ")} · cycles {e.scout.cycles.join(", ")}
            </div>
            {e.scout.why}
            {e.scout.action && <div className={styles.dMutInk}>Suggested: {e.scout.action}</div>}
          </div>
        )}
        <div className={styles.dBands}>
          <span>Founder potential</span>
          <b className={BAND(a.founder)}>{bandText(a.founder)}</b>
          <span>Project A relevance</span>
          <b className={BAND(a.project_a)}>{bandText(a.project_a)}</b>
          <span>Networking</span>
          <b className={BAND(a.networking)}>{bandText(a.networking)}</b>
        </div>
        {(a.factors ?? []).map((f) => (
          <div key={f.dimension} className={styles.dMutInk}>
            {FACTOR[f.dimension] ?? f.dimension}: {f.evidence.join(", ")}
          </div>
        ))}
        {a.passage && (
          <div className={styles.dMutInk}>
            Source passage ({a.passage_field || "?"}): “{a.passage}”
          </div>
        )}
        {(e.themes ?? []).length > 0 && (
          <div className={styles.dThemes}>
            {(e.themes ?? []).map((t) => (
              <span key={t} className={styles.theme}>
                {t}
              </span>
            ))}
          </div>
        )}
        {w && <div className={styles.dMutInk}>Where should I go: {w.reason}{w.extra ? ` · ${w.extra}` : ""}</div>}
      </Sect>

      <Sect title="Verification">
        {e.human_verified ? (
          <span className={styles.verOk}>Verified by you</span>
        ) : tier === "NEEDS REVIEW" ? (
          <>
            <span className={styles.verNo}>Not verified.</span> Missing: {(e.eligibility?.reasons ?? []).slice(0, 3).join("; ")}
            <div className={styles.dRow}>
              <DeferredButton size="sm" reason={NOT_PORTED.verify}>
                Mark as verified
              </DeferredButton>
            </div>
          </>
        ) : tier === "REJECTED" ? (
          <>Not recommended: {(e.eligibility?.reasons ?? []).join("; ")}</>
        ) : (
          <>High-signal from source evidence · source data {(a.confidence || "").toLowerCase()}</>
        )}
      </Sect>

      <Sect title="Sources">
        {(e.sources ?? []).length ? (
          (e.sources ?? []).map((s, i) => (
            <div key={i}>
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.source || s.url} ↗
                </a>
              ) : (
                s.source
              )}
            </div>
          ))
        ) : (
          <span className="muted">No source link recorded.</span>
        )}
      </Sect>

      <Sect title="People to meet">
        {ppl.length ? (
          ppl.slice(0, 6).map((p) => (
            <div key={p.id}>
              <Link to={`/network?person=${encodeURIComponent(p.id)}`}>
                <b>{p.name}</b>
              </Link>{" "}
              <span className="muted">{p.role || ""}</span>
            </div>
          ))
        ) : (
          <span className="muted">
            No contacts in {e.city || "this city"} yet — <Link to="/network">open Network</Link>
          </span>
        )}
      </Sect>

      <Sect title="Notes">
        <div className={styles.pre}>{e.notes || <span className="muted">No notes — add via Edit.</span>}</div>
      </Sect>

      <div className={styles.dRow}>
        <DeferredButton size="sm" reason={NOT_PORTED.edit}>
          Edit event &amp; notes
        </DeferredButton>
        <DeferredButton size="sm" reason={NOT_PORTED.debrief}>
          Debrief after the event
        </DeferredButton>
        <Link className={styles.actQ} to={`/map?event=${encodeURIComponent(e.id)}`}>
          Show on map
        </Link>
      </div>

      <details className={styles.dFold}>
        <summary>Evidence &amp; scoring</summary>
        <div className={styles.scoreRow} data-testid="event-score">
          {e.sc.human ? (
            <>
              <ScoreCell hd="Your score (human judgment)" big={<>{e.sc.total}<span className={styles.den}>/100</span></>} sub="your ladder, not source evidence" />
              <ScoreCell hd="Founder density" big={parts.founder_density ?? "—"} sub="/25" />
              <ScoreCell hd="Technical talent" big={parts.tech_talent ?? "—"} sub="/20" />
              <ScoreCell hd="Network value" big={parts.network_value ?? "—"} sub="/15" />
            </>
          ) : e.rank_score != null && (e.rank_factors ?? []).length ? (
            <>
              <ScoreCell hd="Ordering (evidence factors)" big={e.rank_score} sub="sorting only · not a quality score" />
              {(e.rank_factors ?? []).map((f) => (
                <ScoreCell key={f.factor} hd={f.factor} big={f.points} sub={(a.factors ?? []).find((x) => f.factor.startsWith(x.dimension.replace("_", " ")))?.band ?? ""} />
              ))}
            </>
          ) : (
            <ScoreCell hd="Event score" big={<span className={styles.notScorable}>NOT YET SCORABLE</span>} sub="minimum scoring evidence not present" />
          )}
        </div>
        <div className="muted small">
          Eligibility: <b>{e.eligibility?.label || ""}</b> — {(e.eligibility?.reasons ?? []).join("; ")}
          {e.sc.why && <div>{e.sc.why}</div>}
        </div>
        <div className={styles.pills}>
          {pill("Founder potential", parts.founder_density, 25, "founder / pre-founder density")}
          {pill("Technical founders", parts.tech_talent, 20, "technical talent density")}
          {pill("Early stage", parts.earliness, 15, "earliness of the people there")}
          {pill("Project A relevance", parts.domain_fit, 15, "domain fit with Project A themes")}
          {pill("Networking", parts.network_value, 15, "network value")}
          <Badge tone={audTone} className={styles.pill} title="only stated audience evidence is used">
            Audience: {audLabel}
          </Badge>
        </div>
        <div className="muted small">Labels are bands of the existing event-score ladders (HIGH ≥ 70 %, MEDIUM ≥ 40 % of the ladder maximum); nothing is estimated.</div>
        {(ladderText("founder_density") || e.audience) && (
          <div className="muted small">
            {e.audience && <>Stated audience: {e.audience} · </>}
            {ladderText("founder_density")}
          </div>
        )}
        <table className={styles.dimTable} data-testid="score-breakdown">
          <tbody>
            {(ev.dim_order ?? []).map((k) => {
              const v = parts[k];
              return (
                <tr key={k}>
                  <td>{dims[k]?.label || k}</td>
                  <td className={styles.num}>{v != null ? `${v} / ${dims[k]?.max ?? ""}` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {e.sc.human && e.sc.evidence?.length > 0 && (
          <div className="muted small">
            Event Score {e.sc.total} — {e.sc.band}. Evidence: {e.sc.evidence.map((x) => `${x[0]} ${x[1]}/${x[2]} — ${x[3]}`).join(" · ")}
          </div>
        )}
        <div className="muted small">
          {e.travel_hours != null ? `Travel time ~${e.travel_hours}h from ${homeCity}${e.city ? ` to ${e.city}` : ""} (city-table approximation, not a routed estimate)` : "Travel time unknown"}
          {parts.accessibility != null && ` · accessibility ${parts.accessibility}/10 (your ladder)`}
          {e.deadline && ` · register by ${e.deadline}`}
          {days != null && ` · starts in ${days} day${days === 1 ? "" : "s"}`}
        </div>
      </details>
    </div>
  );
}

/** Details of a Scout 00 suggestion that is not an Events record yet (Add / Monitor / Ignore wait for the writes port). */
export function SuggestionDetail({ r }: { r: ScoutReport }) {
  return (
    <div className={styles.detail} data-testid="suggestion-detail">
      <section className={styles.dFacts}>
        <span className={cx(styles.lab, styles.onDark, styles.labSug)}>Scout 00 suggestion · not on Events yet</span>
        <dl className={styles.dKv}>
          <dt>When</dt>
          <dd>{r.date ? new Date(`${r.date}T12:00:00`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" }) : "Date not stated"} · time not stated</dd>
          <dt>Where</dt>
          <dd>
            {r.place?.label || r.city}
            {r.travel_hours != null && <div className={styles.dMut}>{travelLine(r.travel_hours)}</div>}
          </dd>
        </dl>
      </section>
      <div className={styles.dRow}>
        <DeferredButton size="sm" variant="primary" reason={NOT_PORTED.scout}>
          Add to Events
        </DeferredButton>
        {!r.statuses.includes("MONITOR") && (
          <DeferredButton size="sm" reason={NOT_PORTED.scout}>
            Monitor
          </DeferredButton>
        )}
        <DeferredButton size="sm" variant="ghost" reason={NOT_PORTED.scout}>
          Ignore
        </DeferredButton>
        {r.url && (
          <a className={styles.actQ} href={r.url} target="_blank" rel="noreferrer">
            Official source ↗
          </a>
        )}
      </div>
      <Sect title="Why it matters for scouting">
        <div className={styles.dScout}>
          <div className={styles.dScoutHd}>
            Scout 00 · {[r.p_class, r.ev_class].filter(Boolean).join(" · ")} · cycles {r.cycles.join(", ")}
          </div>
          {r.why}
          {r.action && <div className={styles.dMutInk}>Suggested: {r.action}</div>}
        </div>
        <div className={styles.dMutInk}>
          Not an Events record yet — adding it creates one (with Scout 00 as its source) that you then verify. Nothing is registered or planned automatically.
        </div>
      </Sect>
      <div className={styles.dMutInk}>
        Full packets in <Link to="/scout-intake">Scout Intake</Link>.
      </div>
    </div>
  );
}

function ScoreCell({ hd, big, sub }: { hd: string; big: React.ReactNode; sub: string }) {
  return (
    <div className={styles.scoreCell}>
      <div className={styles.hd}>{hd}</div>
      <div className={styles.big}>{big}</div>
      <div className="muted small">{sub}</div>
    </div>
  );
}

function Sect({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className={styles.sect}>
      <h4 className={styles.hd}>{title}</h4>
      <div className={styles.sectBody}>{children}</div>
    </section>
  );
}
