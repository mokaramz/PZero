/**
 * The deeper layers of a Conviction company, grouped by the question they answer. Rendered inside collapsed
 * <Section>s (CasePanel), so nothing renders until it is opened. What reads the record is live, the outreach email and
 * the Scout memo included (review 019); what needs a later port (verification proposals, traction review, founders /
 * registries, the Manager card, Scout 00 and the evaluator) keeps its place with the reason instead. The dated why-now
 * trigger is live since review 024.
 */
import { useMemo, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { useToast } from "@/components/Toast";
import { Async, Badge, Button } from "@/components/ui";
import { useAction, useCopy } from "@/lib/hooks";
import { CONVICTION_KEYS, SAVE, useOutreachEmail, useScoutMemo } from "../api";
import { NOT_PORTED } from "../model/deferred";
import { archetypeOf, human, isGated, verifyListText } from "../model/logic";
import type { Meta, SaveBody, ScoutProvenance, Signal } from "../model/types";
import { ImqBlock } from "./ImqBlock";
import { NotPortedPart, Score, Sub2 } from "./parts";
import styles from "../Conviction.module.css";

/* ---------------------------------------------------------------- 1 · investment case */
export function InvestmentCase({ e, meta, children }: { e: Signal; meta?: Meta; children?: ReactNode }) {
  const a = archetypeOf(meta, e.archetype);
  const v = e.verified ?? {};
  const why = [
    e.why_project_a && <p key="p">{e.why_project_a}</p>,
    e.founder_signal && (
      <p key="f" className="small muted">
        <b>Founder signal{v.founders ? "" : " (unverified)"}:</b> {e.founder_signal}
      </p>
    ),
    e.why_found && (
      <p key="w" className="small muted">
        <b>Found because:</b> {e.why_found}
      </p>
    ),
  ].filter(Boolean);
  return (
    <>
      <p className={styles.thesis}>{e.one_liner || "—"}</p>
      <p className="small muted">
        {[e.location, a && `#${a.id} ${a.name}`].filter(Boolean).join(" · ")}
        {e.website && (
          <>
            {" · "}
            <a href={e.website} target="_blank" rel="noreferrer">
              site ↗
            </a>
          </>
        )}
      </p>
      <Sub2>Why you care</Sub2>
      {why.length ? why : <p className="muted small">Add your reasoning via Edit &amp; verify.</p>}
      {(e.bull || e.bear) && (
        <div className={styles.pair}>
          <div>
            <Sub2>Bull</Sub2>
            <p className="small">{e.bull || "—"}</p>
          </div>
          <div>
            <Sub2>Bear</Sub2>
            <p className="small">{e.bear || "—"}</p>
          </div>
        </div>
      )}
      <Sub2>Score &amp; confidence</Sub2>
      <div className={styles.scoreRow}>
        <span>
          <Score value={e.sc.provisional} kind="prov" size="big" /> <span className={styles.sub}>provisional</span>
        </span>
        <span>
          <Score value={e.sc.verified} kind="ver" size="big" /> <span className={styles.sub}>verified</span>
        </span>
        <span className={styles.sub}>
          {e.sc.fully_verified ? "fully verified" : "provisional"} · score band: {e.sc.verdict.toLowerCase()}
        </span>
      </div>
      <Sub2>Portfolio</Sub2>
      <p className="small">
        {isGated(e) ? (
          <>
            Potential overlap with <b>{e.twin || "portfolio"}</b>. Do not contact, do not forward — ask Manager first.
          </>
        ) : (
          <>
            Conflict: {human(e.conflict, "none")}
            {e.twin && ` · closest: ${e.twin}`}
          </>
        )}
      </p>
      {children}
    </>
  );
}

/* ---------------------------------------------------------------- 2 · evidence & verification */
const VER_ROWS: Array<["founders" | "traction" | "funding", string]> = [
  ["founders", "Founders — identities, backgrounds, LinkedIn"],
  ["traction", "Traction — customers/pilots real, not press-release-only"],
  ["funding", "Funding — stage and amounts confirmed"],
];

/** The three verification ticks: each one is a save (the server re-scores; the row and the header follow the refetch). */
function Checklist({ e }: { e: Signal }) {
  const save = useAction<SaveBody>(SAVE, { invalidates: CONVICTION_KEYS, label: "Saving the verification", quiet: true });
  const toast = useToast();
  const v = e.verified ?? {};
  return (
    <div data-testid="checklist">
      {VER_ROWS.map(([k, l]) => (
        <label key={k} className={styles.vrow}>
          <input
            type="checkbox"
            checked={!!v[k]}
            disabled={save.isPending}
            onChange={(ev) => {
              const checked = ev.target.checked;
              save.mutate(
                { slug: e.slug, company: e.company, verified: { ...v, [k]: checked } },
                { onSuccess: () => toast.show(checked ? `Verified: ${k}` : `Unchecked: ${k}`, "ok") },
              );
            }}
            data-verify={k}
          />
          <span>{l}</span>
          {v[k] && <span className={styles.okWord}>verified</span>}
        </label>
      ))}
    </div>
  );
}

export function Evidence({ e, children }: { e: Signal; children?: ReactNode }) {
  const verifyNext = verifyListText(e.verify_list);
  return (
    <>
      <Checklist e={e} />
      <p className="small muted">
        Unchecked = that block scores 0 in the verified number.{" "}
        {e.sc.fully_verified ? "Fully verified — counts for the Radar." : `Missing: ${e.sc.missing.join(", ") || "—"}`}
      </p>
      {verifyNext && (
        <p className="small">
          <b>Verify next:</b> {verifyNext}
        </p>
      )}
      {children}
      <NotPortedPart title="Verification proposals" reason={NOT_PORTED.verification} testId="verification-proposals" />
      <NotPortedPart title="Traction review" reason={NOT_PORTED.traction} testId="traction-review" />
    </>
  );
}

/* ---------------------------------------------------------------- 3 · founders & relationship */
export function Founders({ e, children }: { e: Signal; children?: ReactNode }) {
  const navigate = useNavigate();
  const names = (e.founders ?? []).map((f) => f.name || "").filter(Boolean);
  return (
    <>
      {children}
      {!!names.length && (
        <p className="small">
          <b>Founders:</b> {names.join(", ")}
        </p>
      )}
      <NotPortedPart title="Founders & registries" reason={NOT_PORTED.founders} testId="founders-block" />
      <Sub2>Relationship / intro path</Sub2>
      <p className="small muted">
        Check People for anyone at {e.company} or its ecosystem; a Project A intro only after Manager has seen it.{" "}
        <button type="button" className={styles.link} onClick={() => navigate("/network")}>
          Open Network
        </button>
      </p>
      <OutreachDraft slug={e.slug} />
    </>
  );
}

function OutreachDraft({ slug }: { slug: string }) {
  const email = useOutreachEmail(slug);
  const copy = useCopy();
  return (
    <>
      <Sub2>Outreach email — timing-aware</Sub2>
      <Async q={email}>
        {(d) => (
          <>
            <pre className={styles.cardText} data-testid="outreach-draft">
              {d.text}
            </pre>
            <Button size="sm" variant="ghost" onClick={() => copy(d.text ?? "")}>
              Copy email
            </Button>
          </>
        )}
      </Async>
    </>
  );
}

/* ---------------------------------------------------------------- 4 · funding & timing */
export function Funding({ e, onTrigger }: { e: Signal; onTrigger: () => void }) {
  const t = e.imq_eval?.timing ?? {};
  return (
    <>
      <p>
        <b>{sentenceTiming(e.fundraising_timing)}</b> <span className="muted small">{e.sc.timing_label}</span>
      </p>
      {e.funding_status && <p className="small">{e.funding_status}</p>}
      {e.why_now_text && (
        <p className="small">
          <b>Why now:</b> {e.why_now_text}
        </p>
      )}
      <p className="small muted">
        Stage: {human(e.earliness)} · discovered {e.discovery_date ?? "—"} via {e.discovery_source ?? "—"}
      </p>
      <p className="small">
        Dated why-now trigger:{" "}
        {t.established ? (
          <>
            <b>{t.label}</b> on {t.date} ({t.origin})
          </>
        ) : (
          <>not established · </>
        )}{" "}
        <button type="button" className={styles.link} onClick={onTrigger}>
          Record a dated trigger (sourced)
        </button>
      </p>
    </>
  );
}
const sentenceTiming = (s?: string) => {
  const t = human(s, "timing unknown");
  return t[0].toUpperCase() + t.slice(1);
};

/* ---------------------------------------------------------------- 5 · risks & contradictions */
export function Risks({ e, children }: { e: Signal; children?: ReactNode }) {
  return (
    <>
      {children}
      <ul className={styles.plain}>
        {e.bear && (
          <li>
            <b>Bear:</b> {e.bear}
          </li>
        )}
        {isGated(e) && (
          <li>
            <b>Portfolio conflict:</b> potential overlap with {e.twin || "portfolio"} — Manager first
          </li>
        )}
        {e.sc.missing.length > 0 && (
          <li>
            <b>Unverified:</b> {e.sc.missing.join(", ")}
          </li>
        )}
      </ul>
    </>
  );
}

/* ---------------------------------------------------------------- 6 · manager / team */
export function ManagerTeam({ e }: { e: Signal }) {
  return (
    <>
      <ImqBlock e={e} />
      <div data-testid="omar-card">
        <NotPortedPart
          title={
            <>
              Send-to-Manager card · {e.sent_to_omar ? `sent ${e.sent_to_omar}` : "not sent"}
              {e.omar_feedback ? " · feedback logged" : ""}
            </>
          }
          reason={NOT_PORTED.manager}
        />
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- 7 · full audit (company-side part) */
export function AuditExtras({ e, all, meta }: { e: Signal; all: Signal[]; meta?: Meta }) {
  const memo = useScoutMemo(e.slug);
  const themes = useMemo(() => {
    const m = new Map<string, number>();
    for (const x of all) if (x.status !== "dropped") m.set(String(x.archetype ?? "other"), (m.get(String(x.archetype ?? "other")) ?? 0) + 1);
    return [...m.entries()].sort((p, q) => q[1] - p[1]).slice(0, 5);
  }, [all]);
  const raw: unknown = e.scout_provenance; // tolerate a single record or a malformed element (never crash the workspace)
  const prov = (Array.isArray(raw) ? raw : raw ? [raw] : []).filter((v): v is ScoutProvenance => !!v && typeof v === "object");
  return (
    <>
      <Sub2>Record</Sub2>
      <p className="small muted">
        {e.discovery_status && `${e.discovery_status} · `}
        {e.emerging && "emerging · "}
        source {e.discovery_source ?? "—"} · {e.days_old ?? 0}d in the pipeline · pipeline status {e.status || "new"}
        {e.sent_to_omar && ` · sent to Manager ${e.sent_to_omar}`}
      </p>
      {!!prov.length && (
        <>
          <Sub2>Scout Intake provenance</Sub2>
          <ul className={styles.plain}>
            {prov.map((v, i) => (
              <li key={i} className="small muted">
                Cycle {v.scout_cycle_id} · {(v.source_scouts ?? []).join(", ") || "UNKNOWN"} · {v.attention_state || "UNKNOWN"} · key fact:{" "}
                {v.key_fact || "UNKNOWN"} · key unknown: {v.key_unknown || "UNKNOWN"}
              </li>
            ))}
          </ul>
        </>
      )}
      {!!e.bridge_findings?.length && (
        <>
          <Sub2>Scout 00 research (unverified — not used by scoring)</Sub2>
          {e.bridge_findings.map((f, i) => (
            <div key={i} className="small muted">
              • [{f.category}] {f.claim} —{" "}
              <a href={f.url} target="_blank" rel="noopener noreferrer">
                {f.url.slice(0, 60)}
              </a>
              {f.date && ` · ${f.date}`} · {f.job_id}
            </div>
          ))}
        </>
      )}
      <Sub2>Emerging themes in your conviction set</Sub2>
      <div className={styles.themes}>
        {themes.length
          ? themes.map(([k, n]) => {
              const ar = archetypeOf(meta, Number(k));
              return (
                <Badge key={k} tone="neutral">
                  {ar ? `#${ar.id} ${ar.name.slice(0, 28)}` : k} · {n}
                </Badge>
              );
            })
          : "—"}
      </div>
      <Sub2>Scout memo</Sub2>
      <Async q={memo}>
        {(d) => (
          <pre className={styles.memoText} data-testid="scout-memo">
            {(d.text ?? "").slice(0, 4000)}
          </pre>
        )}
      </Async>
    </>
  );
}
