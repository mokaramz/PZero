import { useState, type ReactNode } from "react";

import { DeferredButton } from "@/components/Deferred";
import { Button, Drawer } from "@/components/ui";
import { useFr } from "../context";
import { NOT_PORTED } from "../model/deferred";
import { RESEARCH, UNRESOLVED, frTier, unknownBands } from "../model/logic";
import type { Person } from "../model/types";
import { linkedinPeopleSearch } from "../model/view";
import { BOARDY_STATES } from "../useFrActions";
import { BandPill, Ext } from "./bits";
import styles from "../FounderRadar.module.css";

/** The founder evidence drawer (v1 openFounder, `?person=`): identity, ordering, evidence, judgment, LinkedIn (manual
 *  only), connections, history and every next step. An unresolved identity blocks Network promotion, the pre-company
 *  opportunity and Boardy, with the guard's reason on each. */
export function PersonDrawer({ personId, onClose }: { personId: string | null; onClose: () => void }) {
  const { data } = useFr();
  const p = data.people.find((x) => x.id === personId);
  return (
    <Drawer open={!!p} onClose={onClose} title={p?.name ?? ""} width={880}>
      {p && <PersonBody key={p.id} p={p} onClose={onClose} />}
    </Drawer>
  );
}

const Sect = ({ hd, children }: { hd: ReactNode; children: ReactNode }) => (
  <section className={styles.sect}>
    <h4 className={styles.hd}>{hd}</h4>
    <div>{children}</div>
  </section>
);

function PersonBody({ p, onClose }: { p: Person; onClose: () => void }) {
  const { data, actions, openPromote, logCall } = useFr();
  const s = p.signal ?? {};
  const b = (s.bands ?? {}) as Record<string, string>;
  const ev = p.evidence ?? [];
  const hist = p.state_history ?? [];
  const unres = (p.identity_status || "") === UNRESOLVED;
  const tier = frTier(p, data.network_states ?? []);
  const block = p.promotion_block;
  const [hj, setHj] = useState(p.human_judgment || "");
  const [li, setLi] = useState(p.linkedin || "");
  const [brief, setBrief] = useState("");
  // A fresh read with another stored URL replaces the field (v1 re-rendered the drawer).
  const [liStored, setLiStored] = useState(p.linkedin);
  if (p.linkedin !== liStored) {
    setLiStored(p.linkedin);
    setLi(p.linkedin || "");
  }

  return (
    <div className={styles.person} data-testid="fr-person">
      <div className={styles.revSummary}>
        <div>
          <div className={styles.hd}>Identity</div>
          <div>
            <b>{p.identity_status || ""}</b>
          </div>
          <div className={styles.sub}>{(p.identity_evidence ?? []).join(" · ") || "no identity evidence"}</div>
        </div>
        <div>
          <div className={styles.hd}>Evidence ordering</div>
          <div className={styles.big}>{s.ordering != null ? s.ordering : "—"}</div>
          <div className={styles.sub}>
            {s.ordering != null ? (s.ordering_factors ?? []).map((f) => f.factor + " " + f.points).join(", ") : "no number — identity or evidence gate not met"}
          </div>
        </div>
        <div>
          <div className={styles.hd}>Relationship</div>
          <div>
            <b>{p.radar_state || ""}</b>
          </div>
          <div className={styles.sub}>
            strength: {p.relationship_strength || "not recorded"} · owner {p.relationship_owner || "Smooth Operator"}
          </div>
        </div>
      </div>

      <Sect hd="Who / where now">
        {p.role || "role UNKNOWN"}
        {p.company ? " · " + p.company : ""}
        {(p.institutions ?? []).length ? " · " + p.institutions!.join(", ") : ""} · {p.location || "location UNKNOWN"}
        {p.country ? " " + p.country : ""}
        {(p.aliases ?? []).length > 0 && <div className={styles.sub}>aliases: {p.aliases!.join(", ")}</div>}
        {(p.profile_urls ?? []).length > 0 && (
          <div className={styles.sub}>
            {p.profile_urls!.map((u, i) => (
              <span key={u}>
                {i > 0 && " · "}
                <Ext href={u}>{u}</Ext>
              </span>
            ))}
          </div>
        )}
        <div className={styles.sub}>founder status: {p.founder_status || "UNKNOWN"}</div>
      </Sect>

      <Sect hd="Why surfaced / why now">
        {p.why_surfaced || "—"}
        {p.last_signal && <div className={styles.sub}>last meaningful signal {p.last_signal}</div>}
      </Sect>

      <Sect hd="Public evidence (machine-collected, attributed)">
        {ev.length ? (
          ev.map((x, i) => (
            <div key={i}>
              • <b>[{x.category}]</b> {x.claim}{" "}
              <span className={styles.subInline}>
                — {x.source}
                {x.source_url && (
                  <>
                    {" · "}
                    <Ext href={x.source_url}>source ↗</Ext>
                  </>
                )}{" "}
                · {x.retrieved || ""}
              </span>
            </div>
          ))
        ) : (
          <span className={styles.sub}>No public evidence yet.</span>
        )}
        <div className={styles.pills}>
          <BandPill label="Builder" value={b.builder} />
          <BandPill label="Technical" value={b.technical_depth} />
          <BandPill label="Entrepreneurial" value={b.entrepreneurial} />
          <BandPill label="Trajectory" value={b.trajectory} />
          <BandPill label="Talent magnet" value={b.talent_magnet} />
          <BandPill label="Project A" value={b.project_a} />
        </div>
        <div className={styles.sub}>
          Unknown = {unknownBands(b, false) || "nothing"}. Integrity, coachability, obsession, resilience and trust are never inferred here.
        </div>
      </Sect>

      <Sect hd="Machine inference">
        <span className={styles.sub}>{p.machine_research || "none recorded"}</span>
      </Sect>

      <Sect hd="Your judgment (private, human)">
        <textarea aria-label="Your judgment" rows={3} value={hj} onChange={(e) => setHj(e.target.value)} />
        <div className={styles.inlineRow}>
          <Button size="sm" onClick={() => actions.saveJudgment(p.id, hj)}>
            Save judgment
          </Button>
          <span className={styles.sub}>founder potential: {p.founder_potential || "—"}</span>
        </div>
      </Sect>

      <Sect hd="Relevance bucket">
        <b>{s.bucket || ""}</b> · founder status: {s.founder_status_class || "unknown"} · {s.founder_scorable ? "founder-scorable" : "Not founder-scorable"}
        {(s.missing ?? []).length ? " · missing: " + s.missing!.join(", ") : ""}
      </Sect>

      <Sect hd="LinkedIn — MANUAL / AUTHORIZED (never scanned)">
        <div className={styles.inlineRow}>
          <input
            className={styles.grow}
            aria-label="LinkedIn profile URL"
            value={li}
            onChange={(e) => setLi(e.target.value)}
            placeholder="canonical profile URL you looked up yourself"
          />
          <Button size="sm" onClick={() => actions.saveLinkedin(p.id, li)}>
            Save URL
          </Button>
          <Ext className={styles.extBtn} href={linkedinPeopleSearch(p)}>
            Search on LinkedIn ↗
          </Ext>
          <Button size="sm" onClick={() => actions.linkedinVerified(p.id, li)}>
            Mark verified manually (URL + fact + confirm)
          </Button>
        </div>
        <div className={styles.sub}>Provenance is recorded as operator action; nothing automated.</div>
      </Sect>

      <Sect hd="Connections">
        Companies: {(p.companies ?? []).join(", ") || "—"} · Events: {(p.events ?? []).join(", ") || "—"} · Ecosystems: {(p.ecosystems ?? []).join(", ") || "—"} ·
        Intro route: {p.intro_route || p.introduced_by_name || "—"}
        {(p.opportunities ?? []).length > 0 && (
          <div className={styles.sub}>Opportunities: {p.opportunities!.map((o) => `${o.name} (${o.status})`).join("; ")}</div>
        )}
        {p.boardy?.status && <div className={styles.sub}>Boardy: {p.boardy.status}</div>}
      </Sect>

      <Sect hd="History">
        <div className={styles.sub}>
          {hist.length
            ? hist.map((h, i) => (
                <div key={i}>
                  {h.on} {h.from || "—"} → <b>{h.to}</b>
                  {h.note ? " · " + h.note : ""}
                </div>
              ))
            : "—"}
        </div>
      </Sect>

      <Sect hd="What next">
        <div className={styles.actionsGrid}>
          <Button size="sm" onClick={() => actions.research(p.id)}>
            Research
          </Button>
          <Button
            size="sm"
            onClick={() => {
              onClose();
              logCall({ person_id: p.id, name: p.name, company: p.company || "" });
            }}
          >
            Log founder call
          </Button>
          <Button size="sm" onClick={() => actions.personEvidence(p.id)}>
            Add public evidence (URL + claim)
          </Button>
          <Button size="sm" onClick={() => actions.confirmIdentity(p.id)}>
            Confirm identity with evidence
          </Button>
          {unres && (
            <DeferredButton size="sm" reason={NOT_PORTED.bridge}>
              Ask Scout 00 for identity evidence
            </DeferredButton>
          )}
          {s.bucket === RESEARCH && (
            <Button size="sm" onClick={() => actions.investigate(p.id)}>
              Investigate founder status
            </Button>
          )}
          {tier === "radar" && (
            <Button size="sm" onClick={() => actions.watch(p.id)}>
              Add to Watchlist
            </Button>
          )}
          {tier !== "network" &&
            (block ? (
              <Button size="sm" disabled title={block}>
                Add to Network — {block}
              </Button>
            ) : (
              <Button size="sm" variant="primary" onClick={() => openPromote(p.id)}>
                Add to Network
              </Button>
            ))}
          <Button size="sm" onClick={() => actions.linkCompany(p.id)}>
            Link to company
          </Button>
          <Button size="sm" onClick={() => actions.linkEvent(p.id)}>
            Link to event
          </Button>
          {block ? (
            <Button size="sm" disabled title={block}>
              Create pre-company opportunity — {block}
            </Button>
          ) : (
            <Button size="sm" onClick={() => actions.opportunity(p.id)}>
              Create pre-company opportunity
            </Button>
          )}
          <Button size="sm" onClick={() => actions.introPath(p.id)}>
            Record introduction path
          </Button>
          {block ? (
            <Button size="sm" disabled title={block}>
              Prepare Boardy request — {block}
            </Button>
          ) : (
            <Button size="sm" onClick={async () => setBrief(await actions.boardyBrief(p.id).catch(() => ""))}>
              Prepare Boardy request
            </Button>
          )}
          <select
            aria-label="Boardy status"
            disabled={!!block}
            value=""
            onChange={(e) => e.target.value && actions.boardyStatus(p.id, e.target.value)}
          >
            <option value="">Boardy status…</option>
            {BOARDY_STATES.map((x) => (
              <option key={x}>{x}</option>
            ))}
          </select>
          <Button size="sm" onClick={() => actions.verifyIdentity(p.id)}>
            Mark identity verified (evidence required)
          </Button>
          <Button size="sm" onClick={() => actions.merge(p.id)}>
            Merge duplicate…
          </Button>
          <Button size="sm" variant="danger" onClick={() => actions.dismiss(p.id)}>
            Dismiss
          </Button>
        </div>
        {brief && (
          <pre className={styles.brief} data-testid="fr-brief">
            {brief}
          </pre>
        )}
      </Sect>
    </div>
  );
}
