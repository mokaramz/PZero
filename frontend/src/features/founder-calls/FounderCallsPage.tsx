/**
 * Founder Calls (v1 view `calls`, review 023): private call notes — Company → Founder → conversations — with the due
 * follow-ups, the call form, the call detail, the memo and the Manager briefing drawers, and the founder / company link
 * pickers. Reads `GET founder-calls/calls`; writes `save`, `followup` and `link` (see ./api).
 *
 * Entry points: `?log=1` / `?new=1` with the context keys (Conviction, Founder Radar, Network) open the form; `?call=<id>`
 * selects a call. A save from a Conviction company (`pipeline_slug` in the context) returns to that company.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { useConfirm } from "@/components/useConfirm";
import { Async, Button, PageHeader } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { companyLink } from "@/features/conviction/api";
import { useBriefing, useCallsWorkspace, useFetchMemo, useFollowup, useLink } from "./api";
import { CallDetail } from "./components/CallDetail";
import { MarkdownDrawer, PickDrawer, type MdView, type Pick } from "./components/CallDrawers";
import { CallForm } from "./components/CallForm";
import { CallIntel } from "./components/CallIntel";
import { CallTree } from "./components/CallTree";
import { DueBox } from "./components/DueBox";
import { briefingFile, ctxFromParams, dueRows, findFounder, memoFile, personRows, pipelineRows, withoutCtx } from "./model/calls";
import type { CallCtx, CallsWorkspace } from "./model/types";
import styles from "./FounderCalls.module.css";

export default function FounderCallsPage() {
  const q = useCallsWorkspace();
  return (
    <div className={styles.page}>
      <PageHeader
        title="Founder Calls"
        subtitle={
          <>
            Private call notes — Company → Founder → conversations. Everything a founder says is <b>Founder-reported — unverified</b>: notes never verify
            identity or founder status, never change Gold/Strong, rankings or evidence gates, and never trigger outreach or Network promotion. Public
            verification stays in the sourced-evidence workflow.
          </>
        }
      />
      <Async q={q} label="Loading Founder Calls…">
        {(fc) => <Workspace fc={fc} />}
      </Async>
    </div>
  );
}

function Workspace({ fc }: { fc: CallsWorkspace }) {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [form, setForm] = useState<CallCtx | null>(null);
  const [md, setMd] = useState<MdView | null>(null);
  const [pick, setPick] = useState<Pick | null>(null);
  const [confirm, confirmEl] = useConfirm();
  const sel = params.get("call");
  const navigate = useNavigate();
  const fetchMemo = useFetchMemo();
  const followup = useFollowup();
  const link = useLink();
  const briefing = useBriefing();

  const setSel = (id: string | null) => {
    const p = new URLSearchParams(params);
    if (id) p.set("call", id);
    else p.delete("call");
    setParams(p, { replace: true });
  };
  const open = (id: string) => {
    setForm(null);
    setSel(id);
  };

  // Entry points on other views (Conviction, Founder Radar, Network): /founder-calls?new=1 (or log=1)&name=…&company=…&person_id=…&radar_key=…
  // The form takes the context while rendering (once per entry URL); the effect then drops the entry keys from the URL.
  const entry = ctxFromParams(params);
  const entryKey = entry ? params.toString() : null;
  const [seenEntry, setSeenEntry] = useState<string | null>(null);
  if (entryKey !== seenEntry) {
    setSeenEntry(entryKey);
    if (entry) setForm(entry);
  }
  useEffect(() => {
    if (entryKey) setParams(withoutCtx(new URLSearchParams(entryKey)), { replace: true });
  }, [entryKey, setParams]);

  const markFollowup = (id: string, done: boolean) =>
    followup.mutate({ id, done }, { onSuccess: () => toast.show(done ? "Follow-up marked done" : "Follow-up reopened", "ok") });

  const openMemo = async (id: string) => {
    try {
      const r = await fetchMemo(id);
      const c = fc.calls.find((x) => x.id === id);
      setMd({ title: `Call memo — ${c?.founder_name ?? ""}`, markdown: r.markdown, file: memoFile(c) });
    } catch (e) {
      toast.show(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const openBriefing = async (fid: string) => {
    const ok = await confirm(
      "Prepare an Manager / Project A briefing from your private call notes? It is generated only on your request, stays unverified and is not sent anywhere.",
      { title: "Prepare Manager briefing", ok: "Prepare briefing" },
    );
    if (!ok) return;
    try {
      const r = await briefing.mutateAsync({ founder_id: fid, confirm: true });
      const f = findFounder(fc, fid);
      setMd({ title: `Project A briefing — ${f?.name ?? ""}`, markdown: r.markdown, file: briefingFile(f?.name) });
    } catch {
      /* toasted */
    }
  };

  const linkFounder = (fid: string) =>
    setPick({
      title: "Link founder to an existing Project Zero person",
      rows: personRows(fc),
      onPick: (pid) =>
        link.mutate(
          { founder_id: fid, person_id: pid },
          { onSuccess: (r) => toast.show(r.ok ? "Founder linked — calls kept under one record" : "link failed", r.ok ? "ok" : "error") },
        ),
    });
  const linkCompany = (cid: string) =>
    setPick({
      title: "Link company to an existing pipeline company",
      rows: pipelineRows(fc),
      onPick: (slug) =>
        link.mutate({ company_id: cid, pipeline_slug: slug }, { onSuccess: (r) => toast.show(r.ok ? "Company linked" : "link failed", r.ok ? "ok" : "error") }),
    });

  const k = fc.counts;
  const call = fc.calls.find((c) => c.id === sel) ?? null;

  return (
    <div className={styles.wrap}>
      <div className={styles.bar}>
        <span className={styles.sub} data-testid="calls-counts">
          {k.companies || 0} companies · {k.founders || 0} founders · {k.calls || 0} calls · {k.due || 0} follow-ups due
        </span>
        <span className="grow" />
        <Button variant="primary" onClick={() => setForm({ external: true })}>
          Add external founder call
        </Button>
      </div>

      <DueBox rows={dueRows(fc)} onOpen={open} onDone={(id) => markFollowup(id, true)} />

      <div className={styles.split} data-testid="calls-split">
        <CallTree
          companies={fc.companies}
          selected={sel}
          formOpen={!!form}
          onSelect={open}
          onLog={(founder_id, company_id) => setForm({ founder_id, company_id })}
          onLinkCompany={linkCompany}
          onLinkFounder={linkFounder}
        />
        <div className={styles.det} data-testid="calls-detail">
          {form ? (
            <>
              {form.pipeline_slug && (
                <Link className="small" to={companyLink(form.pipeline_slug)} data-testid="call-back">
                  ← Back to {form.company || "the company"} (Conviction)
                </Link>
              )}
              <CallForm
                key={JSON.stringify(form)}
                fc={fc}
                ctx={form}
                onCancel={() => setForm(null)}
                onSaved={(id) => {
                  const origin = form.pipeline_slug;
                  setForm(null);
                  if (origin) {
                    // opened from a Conviction company: return there (its prepared case refreshes with this call)
                    toast.show(`Call saved — back on ${form.company || "the company"}`, "ok");
                    navigate(companyLink(origin));
                  } else setSel(id);
                }}
              />
            </>
          ) : call ? (
            <>
              <CallDetail
                fc={fc}
                call={call}
                onEdit={() => setForm({ call_id: call.id })}
                onMemo={() => void openMemo(call.id)}
                onBriefing={() => void openBriefing(call.founder_id)}
                onFollowup={(done) => markFollowup(call.id, done)}
              />
              <CallIntel />
            </>
          ) : (
            <div className={styles.detEmpty}>Select a call, or log a new one.</div>
          )}
        </div>
      </div>

      <MarkdownDrawer view={md} onClose={() => setMd(null)} />
      <PickDrawer pick={pick} onClose={() => setPick(null)} />
      {confirmEl}
    </div>
  );
}
