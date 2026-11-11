/**
 * PREPARED CASE — the decision at the heart of a Conviction company, then its deeper layers. READ-ONLY in review 011:
 * an imported case is shown as it was prepared; a new one is never started (no background preparation, no paid model,
 * no web fetch). Without a case (or while `GET conviction/case` does not exist) the panel shows its "not started" state.
 *
 * Above the fold: WHY IT MATTERS · BIGGEST RISK · TOP UNKNOWN, PZ VIEW · YOUR MOVE, and "What I need from you" only when
 * a human decision is open. Below: seven grouped sections, collapsed unless the current workflow needs one open.
 * Moves that only open Edit & verify, a section or another page work; every move that would record, verify, convene or
 * contact keeps its place, disabled with the reason (see model/deferred).
 */
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { DeferredButton, useDeferred } from "@/components/Deferred";
import { DecisionCard, type Move } from "@/components/focus";
import { Icon, type IconName } from "@/components/Icon";
import { Button } from "@/components/ui";
import { cx } from "@/lib/format";
import { asRole } from "@/lib/roles";
import { useCase } from "../api";
import type { Brief, Card, Decision, Ev } from "../model/case";
import { NOT_PORTED } from "../model/deferred";
import { AUTO_OPEN, human, imqLabel, moveDetail, PRIMARY, pzView, type Section as SectionId, sentence, verifiedCount } from "../model/logic";
import type { Meta, Signal } from "../model/types";
import type { DetailActions } from "./ActionsMenu";
import { AuditExtras, Evidence, Founders, Funding, InvestmentCase, ManagerTeam, Risks } from "./sections";
import styles from "../Case.module.css";

const SECTION_IDS: SectionId[] = ["case", "evidence", "founders", "funding", "risks", "omar", "audit"];

/** The deferred reason of a move kind that records, verifies, convenes or contacts (none for a pure navigation). */
const MOVE_DEFERRED: Partial<Record<string, string>> = {
  contact: NOT_PORTED.outreach,
  omar: NOT_PORTED.manager,
  whynow: NOT_PORTED.imqTrigger,
};

function EvLinks({ ev }: { ev?: Ev[] }) {
  const xs = (ev ?? []).filter((e) => e.url);
  if (!xs.length) return null;
  return (
    <span className={styles.ev}>
      {" "}
      ·{" "}
      {xs.map((e, i) => (
        <span key={e.url}>
          {i > 0 && ", "}
          <a href={e.url} target="_blank" rel="noreferrer noopener">
            {e.label}
          </a>
        </span>
      ))}
    </span>
  );
}

/** One grouped deeper layer — a hairline row with a one-line summary, collapsed unless the workflow needs it now. */
function Section({
  id,
  title,
  hint,
  open,
  auto,
  audit,
  onToggle,
  children,
  icon,
}: {
  id: SectionId;
  icon: IconName;
  title: string;
  hint?: ReactNode;
  open: boolean;
  auto: boolean;
  audit?: boolean;
  onToggle: (open: boolean) => void;
  children: ReactNode;
}) {
  return (
    <details
      id={`sec-${id}`}
      className={cx(styles.sec, audit && styles.secAudit)}
      open={open}
      onToggle={(ev) => onToggle((ev.currentTarget as HTMLDetailsElement).open)}
      data-testid={id === "audit" ? "case-details" : `sec-${id}`}
      data-auto-open={auto || undefined}
    >
      <summary className={styles.secHead}>
        <Icon name={icon} size={16} className={styles.secIcon} />
        <span className={styles.secTitle}>{title}</span>
        {hint && <span className={styles.secHint}>{hint}</span>}
        <Icon name="chevron" size={14} className={styles.secChevron} />
      </summary>
      {open && <div className={cx(styles.secBody, "pz-reveal")}>{children}</div>}
    </details>
  );
}

/** A small text link whose target is not ported yet (an anchor without href, inert). */
function DeferredAnchor({ reason, children }: { reason: string; children: ReactNode }) {
  const d = useDeferred(reason);
  return (
    <>
      <a {...d.props}>{children}</a>
      {d.note}
    </>
  );
}

export function CasePanel({ e, all, meta, actions }: { e: Signal; all: Signal[]; meta?: Meta; actions: DetailActions }) {
  const q = useCase(e.slug);
  const navigate = useNavigate();
  const v = q.data;
  const c = v?.card;
  const state = q.isLoading ? "…" : (v?.state ?? "NOT STARTED");
  const preparing = v?.state === "PREPARING";
  const code = c?.next_action.code ?? "";
  const autoId = c ? AUTO_OPEN[code] : undefined;
  // a section is open when the operator opened it, or — until they touch it — when the current workflow needs it
  const [touched, setTouched] = useState<Partial<Record<SectionId, boolean>>>({});
  const open = { has: (id: SectionId) => touched[id] ?? id === autoId };
  // one open section at a time (focus architecture): opening one collapses the previously open one
  const toggle = (id: SectionId) => (on: boolean) =>
    setTouched((t) => {
      const cur = t[id] ?? id === autoId;
      if (cur === on) return t;
      if (!on) return { ...t, [id]: false };
      const closed = Object.fromEntries(SECTION_IDS.map((x) => [x, false])) as Record<SectionId, boolean>;
      return { ...closed, [id]: true };
    });
  const reveal = (id: SectionId) => {
    toggle(id)(true);
    requestAnimationFrame(() => document.getElementById(`sec-${id}`)?.scrollIntoView?.({ block: "start", behavior: "smooth" }));
  };

  /** A case decision's own button: editing and opening work; recording, verifying and convening are deferred. */
  const act = (d: Decision) => {
    const a = d.action;
    if (!a) return null;
    if (a.type === "outreach")
      return (
        <DeferredButton size="sm" reason={NOT_PORTED.outreach}>
          {a.kind === "follow_up_sent" ? "I sent the follow-up…" : "I sent the outreach…"}
        </DeferredButton>
      );
    if (a.type === "verify")
      return (
        <DeferredButton size="sm" reason={NOT_PORTED.verification}>
          Accept {a.flag} (your click)
        </DeferredButton>
      );
    if (a.type === "imq_trigger")
      return (
        <DeferredButton size="sm" reason={NOT_PORTED.imqTrigger}>
          Review &amp; record…
        </DeferredButton>
      );
    if (a.type === "reviewer" || a.type === "committee") {
      const role = a.type === "committee" ? a.role : "chair";
      return (
        <DeferredButton size="sm" reason={NOT_PORTED.committee} data-testid={`case-convene-${role}`}>
          {role === "outside" ? "Ask the outside member (≈$0.10, ~5 min)" : "Convene the IC Chair (≈$0.04, ~3 min)"}
        </DeferredButton>
      );
    }
    if (a.type === "edit")
      return (
        <Button size="sm" onClick={actions.onEdit}>
          Edit archetype
        </Button>
      );
    return (
      <Button size="sm" onClick={() => navigate(a.link)}>
        Open
      </Button>
    );
  };

  /** The ONE contextual primary action (presentation of the case's own next action). */
  const primary = (card: Card): Move => {
    const na = card.next_action;
    const p = PRIMARY[na.code];
    const base = { why: asRole(na.label), detail: asRole(moveDetail(na.why)), testId: "case-primary" };
    if (!p) return na.link && !na.link.includes(`company=${e.slug}`) ? { ...base, label: "Open", to: na.link } : { ...base, label: "Edit & verify", onClick: actions.onEdit };
    const deferred = MOVE_DEFERRED[p.kind];
    if (deferred) return { ...base, label: p.label, deferred };
    switch (p.kind) {
      case "none":
        return { ...base, label: "" };
      case "link":
        return { ...base, label: p.label, to: na.link };
      case "section":
        return { ...base, label: p.label, onClick: () => reveal(p.section ?? "evidence") };
      default:
        return { ...base, label: p.label, onClick: actions.onEdit };
    }
  };

  const risks = c ? [...c.contradictions.map((f) => `${f.label}: ${f.text}`), ...points(c.brief?.why_fail)] : [];
  const why = c ? (points(c.brief?.why_exceptional).length ? points(c.brief?.why_exceptional) : c.why_pz_cares).slice(0, 6) : [];
  const verifiedN = verifiedCount(e);
  const imqState = e.imq_eval?.state;

  return (
    <>
      <section className={styles.case} data-state={v?.state ?? "NOT STARTED"} data-testid="case-panel" aria-label="Prepared case">
        <div className={styles.head}>
          <span className={styles.title}>Prepared case</span>
          <span className={styles.caseState} data-testid="case-state" title={[v?.why, v?.prepared_for && `for “${v.prepared_for}”`].filter(Boolean).join(" · ")}>
            {preparing ? "PREPARING CASE" : state}
          </span>
          {v?.prepared_at && <span className={styles.when}>{v.prepared_at.slice(0, 10)}</span>}
          <span className={styles.grow} />
          <DeferredButton size="sm" variant={c ? "ghost" : "primary"} reason={NOT_PORTED.casePrep} data-testid="case-refresh">
            {c ? "Refresh case" : "Prepare case"}
          </DeferredButton>
        </div>
        {!c ? (
          <p className={cx("muted", styles.empty)} data-testid="case-empty">
            {preparing
              ? "Project Zero was preparing this case when it was imported; the case-preparation port finishes it."
              : "Not prepared yet. Nothing is prepared automatically until the case-preparation port; your scores, verification and status work meanwhile."}
          </p>
        ) : (
          <>
            <div data-testid="case-next" data-code={c.next_action.code}>
              <DecisionCard
                aside={
                  <>
                    Verified <b>{e.sc.verified}</b> · provisional {e.sc.provisional}
                  </>
                }
                why={why.map((x) => asRole(x))}
                risks={risks.map((x) => asRole(x))}
                unknowns={c.unknown.map((f) => `${f.label}: ${f.text}`)}
                pzView={
                  <>
                    <span data-testid="pz-view">{pzView(e)}</span>
                    {c.brief?.confidence && <span className={styles.pzSub}>confidence {c.brief.confidence.replace(/_/g, " ").toLowerCase()}</span>}
                  </>
                }
                move={primary(c)}
              />
            </div>
            {!!c.decisions.length && (
              <div className={styles.need}>
                <div className={styles.needHead}>What I need from you</div>
                <ol className={styles.decisions} data-testid="case-decisions">
                  {c.decisions.map((d) => (
                    <li key={d.kind + d.text} data-testid="case-decision" data-kind={d.kind}>
                      <span className={styles.oneLine} title={asRole(d.text)}>
                        {asRole(d.text)}
                      </span>
                      {act(d)}
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </>
        )}
      </section>

      <div className={styles.sections} aria-label="Supporting evidence">
        <Section id="case" icon="doc" title="Investment case" hint={`Provisional ${e.sc.provisional} · Verified ${e.sc.verified}`} open={open.has("case")} auto={autoId === "case"} onToggle={toggle("case")}>
          <InvestmentCase e={e} meta={meta}>
            {c && (
              <>
                <div className={styles.sect}>Why Project Zero cares</div>
                <ul className={styles.list}>
                  {c.why_pz_cares.map((x) => (
                    <li key={x}>{x}</li>
                  ))}
                </ul>
                <p className="small">
                  <b>Why this next action:</b> {c.next_action.label} — {c.next_action.why}
                </p>
                {c.brief && <BriefBlock b={c.brief} />}
              </>
            )}
          </InvestmentCase>
        </Section>

        <Section id="evidence" icon="shield" title="Evidence & verification" hint={`${verifiedN} of 3 critical facts verified`} open={open.has("evidence")} auto={autoId === "evidence"} onToggle={toggle("evidence")}>
          <Evidence e={e}>
            {c && (
              <>
                <div className={styles.sect}>Key facts</div>
                <ul className={styles.list} data-testid="case-known">
                  {c.known.map((f) => (
                    <li key={f.label + f.text}>
                      <span className={styles.ok}>✓</span> <b>{f.label}:</b> {f.text}{" "}
                      <span className="faint">
                        ({f.state}
                        {f.how ? ` — ${f.how}` : ""})
                      </span>
                      <EvLinks ev={f.evidence} />
                    </li>
                  ))}
                  {!c.known.length && <li className="muted">Nothing publicly confirmed yet.</li>}
                </ul>
              </>
            )}
          </Evidence>
        </Section>

        <Section
          id="founders"
          icon="people"
          title="Founders & relationship"
          hint={c?.contact ? sentence(c.contact.label.split(" — ")[0]) : `${(e.founders ?? []).length || "no"} named founder${(e.founders ?? []).length === 1 ? "" : "s"}`}
          open={open.has("founders")}
          auto={autoId === "founders"}
          onToggle={toggle("founders")}
        >
          <Founders e={e}>
            {c?.contact && <ContactLine contact={c.contact} />}
            {!!c?.human && (c.human.calls.length > 0 || !!c.human.omar.outcome || c.human.hold) && <HumanJudgment h={c.human} />}
          </Founders>
        </Section>

        <Section
          id="funding"
          icon="funding"
          title="Funding & timing"
          hint={`${!e.fundraising_timing || e.fundraising_timing === "unknown" ? "Timing unknown" : sentence(human(e.fundraising_timing))}${e.imq_eval?.timing?.established ? " · why-now dated" : ""}`}
          open={open.has("funding")}
          auto={autoId === "funding"}
          onToggle={toggle("funding")}
        >
          <Funding e={e} />
        </Section>

        <Section
          id="risks"
          icon="warning"
          title="Risks & contradictions"
          hint={
            c
              ? `${c.contradictions.length} contradiction${c.contradictions.length === 1 ? "" : "s"} · ${c.unknown.length} open question${c.unknown.length === 1 ? "" : "s"}`
              : `${e.sc.missing.length} unverified`
          }
          open={open.has("risks")}
          auto={autoId === "risks"}
          onToggle={toggle("risks")}
        >
          <Risks e={e}>{c && <CaseRisks c={c} />}</Risks>
        </Section>

        <Section
          id="omar"
          icon="approval"
          title="Manager / Team"
          hint={`${imqState ? imqLabel(imqState) : "IMQ not evaluated"} · ${e.sent_to_omar ? `sent ${e.sent_to_omar}` : "not sent"}`}
          open={open.has("omar")}
          auto={autoId === "omar"}
          onToggle={toggle("omar")}
        >
          <ManagerTeam e={e} />
        </Section>

        <Section id="audit" icon="layers" audit title="Full audit" hint="models, score evidence, provenance, audit trail" open={open.has("audit")} auto={false} onToggle={toggle("audit")}>
          {c && v && (
            <>
              <p className="small muted">
                {v.why}
                {v.prepared_at && ` · prepared ${v.prepared_at.replace("T", " ").slice(0, 16)}`}
                {v.prepared_for && ` for “${v.prepared_for}”`}
              </p>
              {!!c.more_decisions.length && (
                <>
                  <div className={styles.sect}>Other open items</div>
                  <ul className={styles.list}>
                    {c.more_decisions.map((d) => (
                      <li key={d.kind + d.text} data-testid="case-more" data-kind={d.kind}>
                        {d.text} {act(d)}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <div className={styles.sect}>What blocks progress</div>
              <ul className={styles.list}>
                {c.blockers.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>
              <div className={styles.sect}>Score — you author it</div>
              <div className="small muted" data-testid="case-score-explain">
                {c.score.explain}
              </div>
              <div className={styles.tableWrap}>
                <table className={styles.rubric} data-testid="case-rubric">
                  <thead>
                    <tr>
                      <th>Component</th>
                      <th>Your score</th>
                      <th>Evidence prepared</th>
                      <th>Machine suggestion (advisory)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.score.rubric.map((r) => (
                      <tr key={r.key}>
                        <td>
                          {r.label} /{r.max}
                        </td>
                        <td>
                          <b>{r.yours}</b>
                        </td>
                        <td className={styles.ev}>{r.evidence.length ? r.evidence.join(" · ") : "—"}</td>
                        <td className={styles.ev}>{r.machine ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="small">
                <Button size="sm" onClick={actions.onEdit}>
                  Set your scores (Edit &amp; verify)
                </Button>
              </div>
              <div className={styles.sect}>Archetype &amp; conflict</div>
              <div className="small">
                Archetype: {c.archetype.stored ?? "not set"} — <b>{c.archetype.status === "OK" ? "OK" : "ARCHETYPE NEEDS REVIEW"}</b> ({c.archetype.why})
              </div>
              <div className="small">
                Conflict: {c.conflict.state}
                {!!c.conflict.adjacent.length && <span className="faint"> · adjacent portfolio (not a conflict signal): {c.conflict.adjacent.join("; ")}</span>}
                <span className="faint"> · {c.conflict.rule}</span>
              </div>
              <MachineView c={c} />
              <div className={styles.sect}>What Project Zero did</div>
              <ul className={styles.list}>
                {v.steps.map((s) => (
                  <li key={s.step}>
                    <b>{s.step}:</b> {s.note}
                  </li>
                ))}
                <li className="faint">Model spend on this case so far: ${(v.usd || 0).toFixed(4)}</li>
              </ul>
              <div className={styles.sect}>Audit trail — every automated action</div>
              <ul className={`${styles.list} ${styles.audit}`} data-testid="case-audit">
                {[...v.audit].reverse().map((a, i) => (
                  <li key={i}>
                    {a.ts.replace("T", " ").slice(0, 16)} · {a.actor} · {a.action.replace(/_/g, " ")} — {a.result}
                    {a.human_confirmed ? " · human-confirmed" : ""}
                  </li>
                ))}
              </ul>
              <div className={styles.sect}>External research agent</div>
              <div className="small">
                An external agent (Scout 00, Grok, Cursor…) can receive this case as a research packet. Its findings come back schema-checked and staged as
                UNVERIFIED; Project Zero re-reads every URL itself and nothing it says becomes a trusted fact.{" "}
                <DeferredButton size="sm" reason={NOT_PORTED.bridge} data-testid="case-external">
                  Create research job (your click)
                </DeferredButton>{" "}
                <DeferredAnchor reason={NOT_PORTED.bridge}>view packet</DeferredAnchor>
              </div>
            </>
          )}
          <AuditExtras e={e} all={all} meta={meta} />
        </Section>
      </div>
    </>
  );
}

const KIND_LABEL: Record<string, string> = {
  outreach_sent: "Outreach sent",
  follow_up_sent: "Follow-up sent",
  reply_received: "Reply received",
  call_scheduled: "Call scheduled",
};
const NEXT_KIND: Record<string, string> = {
  NOT_CONTACTED: "outreach_sent",
  CONTACTED_AWAITING_RESPONSE: "reply_received",
  FOLLOW_UP_DUE: "follow_up_sent",
  FOLLOWED_UP_AWAITING_RESPONSE: "reply_received",
  NO_RESPONSE_WATCH: "reply_received",
  REPLIED: "call_scheduled",
};

/** Founder contact: what the Smooth Operator recorded (Project Zero never sends, follows up or books anything). */
function ContactLine({ contact }: { contact: NonNullable<Card["contact"]> }) {
  const kind = NEXT_KIND[contact.state];
  return (
    <div className="small" data-testid="case-contact" data-state={contact.state}>
      <b>Founder contact:</b>{" "}
      <span title={contact.history.map((h) => `${KIND_LABEL[h.kind] ?? h.kind} ${h.date}`).join(" · ") || undefined}>{contact.label}</span>{" "}
      {contact.state !== "CALL_COMPLETED" && kind && (
        <DeferredButton size="sm" variant="ghost" reason={NOT_PORTED.outreach} data-testid="contact-record">
          Record: {KIND_LABEL[kind].toLowerCase()}…
        </DeferredButton>
      )}
      {!!contact.history.length && (
        <ul className={styles.list}>
          {contact.history.map((h, i) => (
            <li key={i} className="faint">
              {h.date} · {KIND_LABEL[h.kind] ?? h.kind} · {h.channel}
              {h.note && ` — ${h.note}`}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function HumanJudgment({ h }: { h: NonNullable<Card["human"]> }) {
  return (
    <div data-testid="case-human">
      <div className={styles.sect}>Human judgment</div>
      <ul className={styles.list}>
        {h.calls.map((k) => (
          <li key={k.id}>
            <b>Founder call {k.date}:</b> outcome {k.recommendation ? `${k.recommendation} (${k.outcome.toLowerCase()})` : "not recorded yet"}
            {k.next_action && <span> · your next step: “{k.next_action}”</span>}
          </li>
        ))}
        {!!h.omar.outcome && (
          <li>
            <b>Manager:</b> {h.omar.outcome}
            {h.omar.feedback && <span className="faint"> — “{h.omar.feedback}”</span>}
          </li>
        )}
        {!!h.reopen_evidence.length && <li>Re-opened by newer evidence: {h.reopen_evidence.join("; ")}</li>}
        {h.hold && <li data-testid="case-reopen">Re-open if: {h.reopen_triggers.join("; ")}</li>}
        <li className="faint">{h.label}</li>
      </ul>
    </div>
  );
}

function CaseRisks({ c }: { c: Card }) {
  return (
    <ul className={styles.list} data-testid="case-risks">
      {c.contradictions.map((f) => (
        <li key={"c" + f.label + f.text} data-testid="case-contradiction">
          <span className={styles.warn}>⚠</span> <b>{f.label}:</b> {f.text}
          <EvLinks ev={f.evidence} />
        </li>
      ))}
      {points(c.brief?.why_fail).map((x) => (
        <li key={"f" + x}>
          <span className={styles.warn}>⚠</span> {x}
        </li>
      ))}
      {c.unknown.map((f) => (
        <li key={"u" + f.label + f.text}>
          <span className={styles.unk}>?</span> <b>{f.label}:</b> {f.text} {f.who && <span className="faint">— answerable by {f.who}</span>}
        </li>
      ))}
      {(c.brief?.disagreements ?? []).map((x) => (
        <li key={"d" + x}>
          <span className={styles.unk}>≠</span> {x}
        </li>
      ))}
    </ul>
  );
}

function MachineView({ c }: { c: Card }) {
  const m = c.machine;
  return (
    <>
      <div className={styles.sect}>Machine view (advisory)</div>
      <ul className={styles.list} data-testid="case-machine">
        <li>
          <b>Machine triage:</b> {m.triage ? `${m.triage.proposal} — ${m.triage.reasons.join("; ")}` : "— (not from a Deal Flow candidate)"}
        </li>
        <li>
          <b>Analyst:</b>{" "}
          {m.analyst
            ? `${m.analyst.recommendation ?? "—"} · machine score ${m.analyst.proposed_provisional ?? "—"} (advisory) · for: ${m.analyst.for.join("; ")} · against: ${m.analyst.against.join("; ")}`
            : "not run"}
        </li>
        <li>
          <b>Red Team:</b> {m.red_team ? `${m.red_team.verdict} — ${m.red_team.summary ?? ""}` : "not run"}
        </li>
        <li>
          <b>Reviewer:</b>{" "}
          {m.reviewer ? `${m.reviewer.state} ${m.reviewer.review?.verdict ?? ""} — ${m.reviewer.review?.summary ?? ""}` : "not run (selective — offered when stakes justify it)"}
        </li>
        <li data-testid="case-committee">
          <b>Investment Committee:</b>{" "}
          {m.committee?.chair
            ? `IC Chair ${m.committee.chair.state} (${m.committee.chair.model ?? ""})${m.committee.chair.error ? " — " + m.committee.chair.error : ""}`
            : "not convened (offered only on hard cases)"}
          {m.committee?.outside ? ` · outside member ${m.committee.outside.state}` : ""}
          {!m.committee?.chair && (
            <>
              {" "}
              <DeferredButton size="sm" variant="ghost" reason={NOT_PORTED.committee} data-testid="case-ask-committee">
                Ask the committee to look
              </DeferredButton>
            </>
          )}
        </li>
        <li className="faint">{m.run_note}</li>
        <li className="faint">{m.advisory}</li>
      </ul>
    </>
  );
}

/** Split a model paragraph into short points for the first screen (the full text stays in the brief below). */
const points = (t?: string | null) =>
  (t || "")
    .split(/(?<=[.;])\s+(?=[A-Z0-9])|;\s+/)
    .map((x) => x.trim().replace(/[.;]+$/, ""))
    .filter((x) => x.length > 3);

function BriefBlock({ b }: { b: Brief }) {
  const row = (label: string, body: string | string[]) => {
    const items = Array.isArray(body) ? body.filter(Boolean) : body ? [body] : [];
    return (
      <div className={styles.briefRow}>
        <dt className="faint small">{label}</dt>
        <dd>{items.length ? items.join(" · ") : <span className="muted">—</span>}</dd>
      </div>
    );
  };
  return (
    <dl className={styles.brief} data-testid="case-brief" data-source={b.source}>
      <div className="faint small">
        From the {b.source} (advisory)
        {b.routing ? ` · routing ${b.routing.replace(/_/g, " ")}` : ""}
        {b.confidence ? ` · confidence ${b.confidence.replace(/_/g, " ")}` : ""}
      </div>
      {b.human_conflict && (
        <div className="small" data-testid="case-brief-conflict">
          <b>Your signal stands:</b> {b.human_conflict}
        </div>
      )}
      {row("WHY EXCEPTIONAL", b.why_exceptional)}
      {row("WHY IT MAY FAIL", b.why_fail)}
      {row("DISAGREEMENTS", b.disagreements)}
      {row("VERIFIED", b.verified)}
      {row("UNKNOWN", b.unknown)}
      {b.contrarian && (
        <div className="small" data-testid="case-brief-contrarian">
          <b>Outside member — contrarian, advisory:</b> {b.contrarian.interpretation} <span className="faint">Why it may still be false: {b.contrarian.still_false}</span>
        </div>
      )}
      {row("WHAT YOU DECIDE", b.mohamed_decides)}
      {row("ONE NEXT ACTION", b.next_action)}
    </dl>
  );
}
