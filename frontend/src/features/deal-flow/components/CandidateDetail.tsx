import { DisclosureGroup } from "@/components/attention";
import { DecisionCard, Disclosure, fieldFor, FIELD_LABEL, HighlightStrip, Monogram, StatusChip } from "@/components/focus";
import { Icon } from "@/components/Icon";
import { Badge, Button, Callout } from "@/components/ui";
import { ago } from "@/lib/format";
import { asRole } from "@/lib/roles";
import { crossScore, earliness, fbTxt, fitScore, recScore, srcDate, srcQuality, tierLbl } from "../model/attention";
import type { SentDecision } from "../model/decision";
import { NOT_PORTED } from "../model/deferred";
import { operatorView } from "../model/operatorView";
import { hostOf, isoDay, revisitLabel } from "../model/revisit";
import type { TriageSummary } from "../model/triage";
import type { Candidate, InboxPayload, Revisit } from "../model/types";
import { AnalystChip } from "./AnalystChip";
import { TriagePanel, type TriageDecide } from "./TriagePanel";
import { WatchSection } from "./WatchSection";
import styles from "../DealFlow.module.css";

export type DetailActions = {
  decide: (decision: SentDecision) => void;
  /** opens the ResearchDrawer (notes are written there) */
  research: () => void;
  /** opens Keep & score (a Conviction save with the candidate's inbox_id) */
  keep: () => void;
  busy: boolean;
  /** accept / override the machine proposal (review 035a); a KEEP opens Keep & score */
  triage: TriageDecide;
  triageBusy: boolean;
};

type Props = {
  c: Candidate | undefined;
  ib: Pick<InboxPayload, "themes" | "feedback_cap" | "feedback_min_reviewed">;
  im: boolean;
  actions: DetailActions;
  tri?: TriageSummary;
  triPending?: string;
};

const sign = (n: number | undefined) => `${(n ?? 0) >= 0 ? "+" : ""}${n ?? 0}`;

/** A section whose data arrives with a later port: its heading stays, with the reason in place of the content. */
function NotPortedSection({ title, reason, testId }: { title: string; reason: string; testId: string }) {
  return (
    <section className={styles.dsec} data-testid={testId} data-deferred="">
      <h4 className={styles.hd}>{title}</h4>
      <div className="small faint">{reason}</div>
    </section>
  );
}

function Header({ c, edge, themes, sector }: { c: Candidate; edge?: string; themes: string[]; sector?: string }) {
  const a = c.attention_v2 || {};
  return (
    <header className={styles.dHead}>
      <Monogram name={c.name} size={52} />
      <div className={styles.dHeadMain}>
        <h2 className={styles.dname}>{c.name}</h2>
        {c.description && <p className={styles.oneLine}>{c.description}</p>}
        <div className={styles.dChips}>
          {edge && (
            <StatusChip tone={edge === "Already funded" ? "neutral" : "progress"} testId="cand-edge">
              {edge}
            </StatusChip>
          )}
          {c.opportunistic && <Badge tone="red">OPPORTUNISTIC</Badge>}
          {(c.location || c.country) && (
            <span className={styles.dGeo}>
              <Icon name="pin" size={13} /> {[c.location, c.country].filter(Boolean).join(" · ")}
            </span>
          )}
          {c.decision !== "new" && <span className={styles.dMeta}>decision: {c.decision}</span>}
        </div>
        <div className={styles.dMeta}>
          {[a.entity ? (a.entity.label || "").replace("Entity: ", "") : "", FIELD_LABEL[fieldFor(c.description, themes.join(" "), sector)] || "", themes.length ? themes.join(" · ") : ""]
            .filter(Boolean)
            .join(" · ")}
        </div>
      </div>
    </header>
  );
}

/** Review 018: a rejected candidate re-reported with a material change since the rejection. Information only — the
 *  reopen is the existing decision row (Undo), Mohamed's call. */
function RevisitCallout({ r }: { r: Revisit }) {
  const earlier = (r.corroboration ?? []).filter((c) => c.evidence_url !== r.evidence_url);
  const meta = [r.rejected_on ? `rejected on ${isoDay(r.rejected_on)}` : "", r.flagged_on ? `flagged ${r.flagged_on}` : ""].filter(Boolean).join(" · ");
  return (
    <Callout tone="blue" className={styles.revisit} data-testid="cand-revisit">
      <div>
        <b>Revisit suggested: {revisitLabel(r.kind)}</b>
        {r.since ? ` since ${isoDay(r.since)}` : ""}
        {r.evidence_url && (
          <>
            {" — "}
            <a href={r.evidence_url} target="_blank" rel="noopener noreferrer">
              evidence ↗
            </a>
          </>
        )}
        {r.note ? ` · ${r.note}` : ""}
        {earlier.length > 0 && (
          <>
            {" · also reported at "}
            {earlier.map((c, i) => (
              <span key={c.evidence_url}>
                {i > 0 ? ", " : ""}
                <a href={c.evidence_url} target="_blank" rel="noopener noreferrer">
                  {hostOf(c.evidence_url)} ↗
                </a>
              </span>
            ))}
          </>
        )}
      </div>
      <div className={`small faint ${styles.revisitMeta}`}>
        {meta}
        {meta ? " · " : ""}
        Reopen with Undo under Your decision if it is worth another look.
      </div>
    </Callout>
  );
}

function AttentionReasoning({ c, im, ib }: { c: Candidate; im: boolean; ib: Props["ib"] }) {
  const a = c.attention_v2 || {};
  const sd = srcDate(c);
  return (
    <section className={styles.dsec}>
      <h4 className={styles.hd}>Attention reasoning</h4>
      <div className={styles.mono}>
        <b>Attention {a.score}</b>
        {im && ` · Lens ${sign(a.lens)} · Differentiation ${sign(a.diff)}${a.entity?.penalty ? ` · Entity ${a.entity.penalty}` : ""} · FINAL ${a.final}`}
      </div>
      <div className="faint small">{[a.explain, im ? a.diff_explain : ""].filter(Boolean).join(" · ") || "no applied signals"}</div>
      {a.gated && <div className={`small ${styles.amberText}`}>Not in the attention queue: {a.gated}</div>}
      {im && !!c.lens?.signals?.length && <div className="faint small">Lens: {c.lens.signals.join(", ")}</div>}
      <div className={`${styles.mono} faint small`}>
        Ordering factors: Project A fit {fitScore(c)} · source quality {srcQuality(c)} · freshness {recScore(c) * 2}
        {sd ? "" : " (source date UNKNOWN)"} · cross-source confirmation {crossScore(c)} · earliness {earliness(c)}
      </div>
      <div className={`small ${styles.fbline}`} data-testid="fb-line">
        <b>{fbTxt(c)}</b> — {c.feedback?.reason || "neutral"}
        <br />
        <span className="faint">
          Ordering only, from your Keep / Research / Reject and Manager ± decisions (cap ±{ib.feedback_cap || 3}, neutral until {ib.feedback_min_reviewed || 5}{" "}
          reviewed companies per source). No model is trained — a bounded counter of your own decisions. The Taste Map is unchanged.
        </span>
      </div>
    </section>
  );
}

function Provenance({ c }: { c: Candidate }) {
  const sd = srcDate(c);
  const fs = c.first_seen || c.detected_on || "";
  return (
    <section className={styles.dsec}>
      <h4 className={styles.hd}>Source &amp; provenance</h4>
      <div className="small">
        {c.source} · {tierLbl(c)} · {sd ? `source date ${sd}` : <span className={styles.amberStrong}>source date UNKNOWN</span>} · first seen by PZ {fs}
        {c.first_seen_run ? ` (scan ${c.first_seen_run})` : ""}
        {c.last_observed && c.last_observed !== c.first_seen_run ? ` · last observed ${c.last_observed}` : ""}
        {(c.seen_runs || 0) > 1 ? ` · seen in ${c.seen_runs} scans` : ""}
        {c.decision === "baseline" && (
          <>
            {" · "}
            <b>existed before first run</b>
          </>
        )}{" "}
        ·{" "}
        <a href={c.source_url} target="_blank" rel="noreferrer">
          source ↗
        </a>
      </div>
      {!!c.also_seen?.length && (
        <div className="small">
          Also seen:{" "}
          {c.also_seen.map((s, i) => (
            <span key={`${s.source}-${i}`}>
              {i > 0 && " · "}
              <a href={s.url || "#"} target="_blank" rel="noreferrer">
                {s.source}
              </a>
            </span>
          ))}
        </div>
      )}
      {c.quality_source_id && (
        <div className="small">
          Quality source: <span className={styles.mono}>{c.quality_source_id}</span>
        </div>
      )}
    </section>
  );
}

/** Layer 2: the selected candidate — the company anchor, the highlights, the PZ Review, evidence, audit, the decision. */
export function CandidateDetail({ c, ib, im, actions, tri, triPending }: Props) {
  if (!c) return <div className={styles.detailEmpty}>Select a candidate</div>;
  const a = c.attention_v2 || {};
  const th = (c.themes || []).map((t) => ib.themes[t] || t);
  const sd = srcDate(c);
  const fs = c.first_seen || c.detected_on || "";
  const toDecision = () => document.getElementById(`decide-${c.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  const ov = operatorView(c, tri, toDecision);
  const tier = tierLbl(c);
  return (
    <div className={styles.detail} data-testid="cand-detail">
      {/* the company anchor: neutral monogram, name, what it is, ONE scan chip (the sourcing edge) + quiet metadata */}
      <Header c={c} edge={ov.edge} themes={th} sector={tri?.sector} />
      <HighlightStrip
        testId="cand-highlights"
        className={styles.dHighlights}
        items={[
          {
            icon: "signal",
            label: "Strongest signal",
            value: (ov.edge || (c.why || [])[0] || "").split(" — ")[0] || undefined,
            tone: ov.edge && ov.edge !== "Already funded" ? "progress" : undefined,
          },
          { icon: "funding", label: "Stage", value: tier ? tier.charAt(0) + tier.slice(1).toLowerCase() : undefined },
          { icon: "layers", label: "Sources", value: `${(c.also_seen?.length ?? 0) + 1} independent`, hint: c.source },
          { icon: "clock", label: "Freshness", value: sd ? `Source ${ago(sd)}` : fs ? `Found ${ago(fs)}` : undefined, hint: sd ? undefined : "source date unknown" },
        ]}
      />

      {c.revisit && <RevisitCallout r={c.revisit} />}

      <DecisionCard
        why={ov.why.map(asRole)}
        risks={ov.risks.map(asRole)}
        unknowns={ov.unknowns}
        pzView={ov.pz}
        move={ov.move ? { ...ov.move, why: typeof ov.move.why === "string" ? asRole(ov.move.why) : ov.move.why } : null}
        aside={
          a.score != null ? (
            <>
              attention <b>{a.score}</b>
            </>
          ) : undefined
        }
        variant="editorial"
      />

      {c.decision === "watch" && <WatchSection candidateId={c.id} />}
      {!tri && triPending && (
        <section className={styles.dsec} data-testid="triage-pending">
          <h4 className={styles.hd}>Machine triage</h4>
          <div className={`small ${styles.amberText}`}>{triPending}</div>
        </section>
      )}
      {tri && <TriagePanel t={tri} themes={ib.themes} decided={c.decision !== "new"} busy={actions.triageBusy} onDecide={actions.triage} />}

      {/* Layer 2 / 3 — one open at a time */}
      <DisclosureGroup>
        <Disclosure title="Founders, description, why it surfaced" icon="people" testId="cand-evidence">
          <NotPortedSection title="Founders" reason={NOT_PORTED.founders} testId="founders-block" />
          <section className={styles.dsec}>
            <h4 className={styles.hd}>Why it surfaced</h4>
            <div className={styles.why}>
              {(c.why || []).join(" · ") || "—"}
              <br />
              <span className="faint">
                Machine-tagged only. Founders, market, timing: <b>not judged</b> — your job.
              </span>
            </div>
          </section>
          <section className={styles.dsec}>
            <h4 className={styles.hd}>Description</h4>
            <div className={styles.desc}>{c.description || ""}</div>
            {c.notes && <div className="faint small">Note: {c.notes}</div>}
          </section>
        </Disclosure>

        <Disclosure title="Analyst · Red Team · Reviewer" icon="doc" hint={c.analysis_state === "ANALYZED" ? "analyzed" : "not analyzed"} testId="cand-models">
          <section className={styles.dsec}>
            <h4 className={styles.hd}>Analyst</h4>
            <div className="small">
              <AnalystChip c={c} />
            </div>
          </section>
          {c.analysis_state === "ANALYZED" && <NotPortedSection title="Red team — tries to break the case (proposals only)" reason={NOT_PORTED.redTeam} testId="red-team" />}
        </Disclosure>

        <Disclosure level={3} title="Attention reasoning, source & provenance" testId="cand-audit">
          {a.score != null && <AttentionReasoning c={c} im={im} ib={ib} />}
          <Provenance c={c} />
        </Disclosure>
      </DisclosureGroup>

      <div className={styles.dec} id={`decide-${c.id}`}>
        <span className={styles.decLab}>Your decision</span>
        <Button variant="danger" onClick={() => actions.decide("rejected")} disabled={actions.busy}>
          Reject
        </Button>
        <Button onClick={actions.research}>Research</Button>
        <Button variant="success" onClick={actions.keep}>
          Keep — score it
        </Button>
        {c.decision !== "new" && (
          <Button size="sm" variant="ghost" onClick={() => actions.decide("new")} disabled={actions.busy}>
            Undo
          </Button>
        )}
      </div>
    </div>
  );
}
