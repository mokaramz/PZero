/**
 * Keep & score / Edit & verify / Add company (v1 openKeep + live + submitKeep) → `POST conviction/save`.
 * Every score is the operator's judgment; the live Provisional / Verified preview mirrors taste.py (the server re-scores
 * on save and its score is the one stored). A Keep sends the Deal Flow candidate's `inbox_id`: the server decides the
 * candidate in the same write. A save the server refuses as a duplicate (409) offers the existing entry instead.
 */
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { Button, Callout, Drawer } from "@/components/ui";
import { useAction } from "@/lib/hooks";
import { companyLink, CONVICTION_KEYS, duplicateOf, SAVE, useMeta, type SaveResult } from "../api";
import { liveScore, today } from "../model/logic";
import type { Ladder, Meta, SaveBody, Signal } from "../model/types";
import styles from "../Conviction.module.css";

/** The Deal Flow candidate fields "Keep & score" prefills from (a Deal Flow `Candidate` fits it as it is). */
export type KeepCandidate = {
  id: string;
  name: string;
  description?: string;
  location?: string;
  source?: string;
  source_url?: string;
  discovery_tier?: string;
  date?: string;
  detected_on?: string;
  archetype_hits?: number[];
  twins?: string[];
};

type Props = {
  open: boolean;
  onClose: () => void;
  /** Existing Conviction entry → "Edit & verify". */
  entry?: Signal | null;
  /** Deal Flow candidate → "Keep & score". Neither → "Add company". */
  candidate?: KeepCandidate | null;
  onSaved?: (slug: string) => void;
};

export function EditCompanyDrawer(props: Props) {
  const meta = useMeta();
  if (!props.open) return null;
  const title = props.entry ? `Edit & verify: ${props.entry.company}` : props.candidate ? `Keep & score: ${props.candidate.name}` : "Add company";
  return (
    <Drawer open onClose={props.onClose} title={title} width={820}>
      {meta.data ? <KeepForm {...props} meta={meta.data} /> : <p className="muted">Loading…</p>}
    </Drawer>
  );
}

const TEXT_KEYS = [
  "company",
  "one_liner",
  "location",
  "website",
  "discovery_source",
  "discovery_tier",
  "discovery_date",
  "funding_status",
  "fundraising_timing",
  "earliness",
  "twin",
  "conflict",
  "why_found",
  "why_project_a",
  "why_now_text",
  "founder_signal",
  "venture_scale_text",
  "bull",
  "bear",
  "next_action",
] as const;
type TextKey = (typeof TEXT_KEYS)[number];
type ScoreKey = "founder" | "venture_scale" | "why_now" | "taste" | "insight";

function initialText(e: Signal | null | undefined, c: KeepCandidate | null | undefined): Record<TextKey, string> {
  return {
    company: e ? e.company : (c?.name ?? ""),
    one_liner: e ? (e.one_liner ?? "") : (c?.description ?? "").slice(0, 160),
    location: e ? (e.location ?? "") : (c?.location ?? ""),
    website: e?.website ?? "",
    discovery_source: e ? (e.discovery_source ?? "") : (c?.source ?? ""),
    discovery_tier: e ? (e.discovery_tier ?? "manual") : (c?.discovery_tier ?? "manual"),
    discovery_date: e ? (e.discovery_date ?? "") : c ? (c.date || c.detected_on || "").slice(0, 10) : today(),
    funding_status: e?.funding_status ?? "",
    fundraising_timing: e?.fundraising_timing ?? "unknown",
    earliness: e?.earliness ?? "unknown",
    twin: e ? (e.twin ?? "") : (c?.twins ?? []).join(" / "),
    conflict: e ? (e.conflict ?? "none") : c?.twins?.length ? "unclear" : "none",
    why_found: e?.why_found ?? "",
    why_project_a: e?.why_project_a ?? "",
    why_now_text: e?.why_now_text ?? "",
    founder_signal: e?.founder_signal ?? "",
    venture_scale_text: e?.venture_scale_text ?? "",
    bull: e?.bull ?? "",
    bear: e?.bear ?? "",
    next_action: e?.next_action ?? "",
  };
}

const lines = (x: string) => x.split("\n").filter(Boolean);

function KeepForm({ entry: e, candidate: c, meta, onClose, onSaved }: Props & { meta: Meta }) {
  const navigate = useNavigate();
  const s = e?.scores ?? {};
  const v = e?.verified ?? {};
  const first = (l: Ladder) => l[0]?.[1] ?? 0;
  const [text, setText] = useState<Record<TextKey, string>>(() => initialText(e, c));
  const [scores, setScores] = useState<Record<ScoreKey, number>>(() => ({
    founder: s.founder ?? first(meta.ladders.founder),
    venture_scale: s.venture_scale ?? first(meta.ladders.venture_scale),
    why_now: s.why_now ?? first(meta.ladders.why_now),
    taste: s.taste ?? first(meta.ladders.taste),
    insight: s.insight ?? first(meta.ladders.insight),
  }));
  // never a silent default: a company without an archetype stays "not set" until the operator picks one
  const [archetype, setArchetype] = useState<number>(() => e?.archetype ?? c?.archetype_hits?.[0] ?? 0);
  const [emerging, setEmerging] = useState(!!e?.emerging);
  const [penalties, setPenalties] = useState<string[]>(e?.penalties ?? []);
  const [ver, setVer] = useState({ founders: !!v.founders, traction: !!v.traction, funding: !!v.funding });
  const [founders, setFounders] = useState(() => (e?.founders ?? []).map((f) => f.name + (f.background ? ` — ${f.background}` : "")).join("\n"));
  const [verifyList, setVerifyList] = useState(() =>
    e ? (Array.isArray(e.verify_list) ? e.verify_list : e.verify_list ? [e.verify_list] : []).join("\n") : "Founders\nTraction\nFunding status / timing\nPortfolio conflict",
  );
  const [sources, setSources] = useState(() => (e ? (e.sources ?? []).join("\n") : (c?.source_url ?? "")));
  const [dup, setDup] = useState<{ slug: string; message: string } | null>(null);

  const save = useAction<SaveBody, SaveResult>(SAVE, { invalidates: CONVICTION_KEYS, label: "Saving to the pipeline", success: "Saved & scored" });

  const live = useMemo(
    () => liveScore({ ...scores, earliness: text.earliness, conflict: text.conflict, penalties, v_founders: ver.founders, v_traction: ver.traction, v_funding: ver.funding }),
    [scores, text.earliness, text.conflict, penalties, ver],
  );

  const setT = (k: TextKey) => (ev: { target: { value: string } }) => setText((t) => ({ ...t, [k]: ev.target.value }));

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setDup(null);
    const byName = new Map((e?.founders ?? []).map((f) => [f.name, f]));
    const o: SaveBody = {
      ...text,
      archetype,
      emerging,
      scores: { ...scores },
      penalties,
      verified: { ...ver },
      founders: lines(founders).map((l) => {
        const [n, b] = l.split(" — ");
        const name = n.trim();
        const prev = byName.get(name);
        // v1 dropped the founder's `role` on every edit; keep it when the row still names the same person.
        return prev?.role ? { name, role: prev.role, background: (b ?? "").trim() } : { name, background: (b ?? "").trim() };
      }),
      verify_list: lines(verifyList),
      sources: lines(sources),
    };
    if (c) o.inbox_id = c.id;
    if (e) o.slug = e.slug;
    const r = await save.mutateAsync(o).catch((err: unknown) => {
      setDup(duplicateOf(err));
      return null;
    });
    if (r?.ok) {
      onClose();
      onSaved?.(r.slug);
    }
  };

  const openExisting = (slug: string) => {
    onClose();
    navigate(companyLink(slug));
  };

  const ladder = (k: ScoreKey, label: ReactNode, hint?: ReactNode) => (
    <label className={styles.col}>
      <span className={styles.groupLabel}>
        {label} <span className={styles.human}>YOU DECIDE</span>
      </span>
      <select name={k} value={scores[k]} onChange={(ev) => setScores((x) => ({ ...x, [k]: Number(ev.target.value) }))}>
        {/* a stored score that is not a ladder step (e.g. 13) stays selectable instead of silently becoming the first */}
        {!meta.ladders[k].some(([, p]) => p === scores[k]) && <option value={scores[k]}>Current score — between ladder steps ({scores[k]})</option>}
        {meta.ladders[k].map(([l, p]) => (
          <option key={`${p}-${l}`} value={p}>
            {l} ({p})
          </option>
        ))}
      </select>
      {hint && <span className="faint small">{hint}</span>}
    </label>
  );
  const input = (k: TextKey, label: ReactNode, opts: { full?: boolean; required?: boolean; placeholder?: string; list?: string; hint?: ReactNode } = {}) => (
    <label className={`${styles.col} ${opts.full ? styles.full : ""}`}>
      <span className={styles.groupLabel}>{label}</span>
      <input name={k} value={text[k]} onChange={setT(k)} required={opts.required} placeholder={opts.placeholder} list={opts.list} />
      {opts.hint && <span className="faint small">{opts.hint}</span>}
    </label>
  );
  const select = (k: TextKey, label: ReactNode, options: Record<string, string>, hint?: ReactNode, full?: boolean, fmt = (l: string) => l) => (
    <label className={`${styles.col} ${full ? styles.full : ""}`}>
      <span className={styles.groupLabel}>{label}</span>
      <select name={k} value={text[k]} onChange={setT(k)}>
        {Object.entries(options).map(([key, l]) => (
          <option key={key} value={key}>
            {fmt(l)}
          </option>
        ))}
      </select>
      {hint && <span className="faint small">{hint}</span>}
    </label>
  );

  return (
    <>
      <Callout tone="blue">
        <b>Every score below is YOUR judgment.</b> Unverified blocks are zeroed in the Verified score — tick the verification boxes only after you
        actually checked.
      </Callout>
      <form className={styles.form} onSubmit={submit} aria-label="Edit and verify company">
        {input("company", "Company", { full: true, required: true })}
        {input("one_liner", "One-liner — what they do", { full: true })}
        {input("location", "Location")}
        {input("website", "Website")}
        {input("discovery_source", "DISCOVERY source — where found")}
        {select("discovery_tier", "Discovery tier", meta.tiers, undefined, false, (l) => l.split(" — ")[0])}
        {input("discovery_date", "Signal date")}
        <label className={styles.col}>
          <span className={styles.groupLabel}>Archetype (hypothesis, not mandate)</span>
          <select name="archetype" value={archetype} onChange={(ev) => setArchetype(Number(ev.target.value))}>
            <option value={0}>— not set (choose the archetype) —</option>
            {meta.archetypes.map((a) => (
              <option key={a.id} value={a.id}>
                #{a.id} {a.name}
              </option>
            ))}
          </select>
          <span className="faint small">#15 = outlier route: no theme required, bar is very high.</span>
        </label>
        <label className={`${styles.check} ${styles.full}`}>
          <input type="checkbox" name="emerging" checked={emerging} onChange={(ev) => setEmerging(ev.target.checked)} />
          Emerging / adjacent thesis candidate (competes for the 1 emerging slot, not the 8)
        </label>
        <label className={`${styles.col} ${styles.full}`}>
          <span className={styles.groupLabel}>Founders (name — background, one per line)</span>
          <textarea name="founders" rows={2} value={founders} onChange={(ev) => setFounders(ev.target.value)} />
        </label>
        {ladder("founder", "Founder signal")}
        {ladder("venture_scale", "Venture-scale potential", "€1B+ plausible? market huge/expanding? wedge → platform? Europe → global?")}
        {ladder("why_now", "Why now")}
        {ladder("taste", "Project A taste fit", '"AI/climate/fintech" alone = 0.')}
        {ladder("insight", "Differentiated insight")}
        {select("earliness", "EARLINESS — how early are we", meta.earliness)}
        {input("funding_status", "Funding status (evidence)", { full: true, placeholder: "e.g. €3.1M pre-seed led by Speedinvest, Jun 2026" })}
        {select("fundraising_timing", "FUNDRAISING TIMING — when is contact useful", meta.timing, 'Recent funding LOWERS urgency. "Pre-seed closed" ≠ "seed open".')}
        {input("twin", "Portfolio twin (closest Project A company)", { list: "pz-portfolio" })}
        <datalist id="pz-portfolio">
          {meta.portfolio.map((p) => (
            <option key={p.name} value={p.name}>
              {p.what}
            </option>
          ))}
        </datalist>
        {select(
          "conflict",
          "Portfolio conflict check (mandatory)",
          meta.conflict,
          "Potential conflict = −25 and a warning. Whether two companies truly compete is Project A's judgment, not the algorithm's.",
          true,
        )}
        <fieldset className={styles.full}>
          <legend className={styles.groupLabel}>Penalties</legend>
          <div className={styles.checks}>
            {Object.entries(meta.penalties).map(([k, l]) => (
              <label key={k} className={styles.check}>
                <input
                  type="checkbox"
                  name="penalties"
                  value={k}
                  checked={penalties.includes(k)}
                  onChange={(ev) => setPenalties((p) => (ev.target.checked ? [...p, k] : p.filter((x) => x !== k)))}
                />
                {l}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset className={styles.full}>
          <legend className={styles.groupLabel}>Verification — tick ONLY after you checked</legend>
          <div className={styles.checks}>
            {(
              [
                ["founders", "Founders' backgrounds verified"],
                ["traction", "Traction verified"],
                ["funding", "Funding status verified"],
              ] as const
            ).map(([k, l]) => (
              <label key={k} className={styles.check}>
                <input type="checkbox" name={`v_${k}`} checked={ver[k]} onChange={(ev) => setVer((x) => ({ ...x, [k]: ev.target.checked }))} />
                {l}
              </label>
            ))}
          </div>
        </fieldset>
        <div className={styles.livescore} data-testid="livescore">
          <span>
            Provisional <b>{live.prov}</b>
          </span>
          <span>
            Verified <b>{live.ver}</b>
          </span>
          <span className="muted small">{live.missLabel}</span>
        </div>
        {input("why_found", "WHY FOUND", { full: true })}
        {input("why_project_a", "WHY PROJECT A", { full: true })}
        {input("why_now_text", "WHY NOW", { full: true })}
        {input("founder_signal", "FOUNDER SIGNAL", { full: true })}
        {input("venture_scale_text", "Venture-scale case", { full: true })}
        {input("bull", "Strongest reason to contact")}
        {input("bear", "Strongest reason to pass")}
        <label className={`${styles.col} ${styles.full}`}>
          <span className={styles.groupLabel}>WHAT I NEED TO VERIFY (one per line)</span>
          <textarea name="verify_list" rows={2} value={verifyList} onChange={(ev) => setVerifyList(ev.target.value)} />
        </label>
        {input("next_action", "NEXT ACTION", { full: true })}
        <label className={`${styles.col} ${styles.full}`}>
          <span className={styles.groupLabel}>Sources (URLs, one per line)</span>
          <textarea name="sources" rows={2} value={sources} onChange={(ev) => setSources(ev.target.value)} />
        </label>
        {dup && (
          <Callout tone="amber" role="alert" className={styles.full} data-testid="save-duplicate">
            <div className="row">
              <span className="grow">{dup.message}</span>
              <Button size="sm" variant="primary" onClick={() => openExisting(dup.slug)}>
                Open existing entry
              </Button>
            </div>
          </Callout>
        )}
        <div className={styles.full}>
          <Button type="submit" variant="success" size="lg" busy={save.isPending}>
            Save to pipeline
          </Button>
        </div>
      </form>
    </>
  );
}
