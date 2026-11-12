/**
 * Every Founder Radar write the page offers, with the old POST bodies and operator wording (`useFrActions`). v1 asked
 * with prompt() / confirm(); the same questions are asked in a form dialog (useAsk, model/dialogs). The scan, the
 * research crawl and the Scout 00 job are not here: they are deferred controls (model/deferred).
 */
import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { useToast } from "@/components/Toast";
import { plainText } from "@/lib/activity";
import { FR_KEYS, postMerge, useBoardyBrief, useCompanyWrite, useJudgment, useRadarAction } from "./api";
import { sv, type Values } from "./model/ask";
import {
  COMPANY_EVIDENCE,
  COMPANY_FACT,
  LINKEDIN_VERIFIED,
  MERGE,
  MERGE_CONFIRM,
  NOTE_ASKS,
  PERSON_EVIDENCE,
  VERIFY_IDENTITY,
  companyEvidenceBody,
  companyFactBody,
  confirmIdentityExtra,
  confirmIdentitySpec,
  linkedinVerifiedExtra,
  noteExtra,
  noteSpec,
  personEvidenceExtra,
  verifyIdentityExtra,
  type NoteAsk,
} from "./model/dialogs";
import type { FounderRadar } from "./model/types";
import { useAsk } from "./useAsk";

export const BOARDY_STATES = [
  "introduction requested",
  "Boardy introduction offered",
  "Boardy introduction accepted",
  "Boardy introduction declined",
  "Boardy follow-up due",
];

export function useFrActions(data: FounderRadar | undefined) {
  const toast = useToast();
  const qc = useQueryClient();
  const { ask, dialog } = useAsk();
  const refresh = useCallback(() => Promise.all(FR_KEYS.map((k) => qc.invalidateQueries({ queryKey: [k] }))), [qc]);

  const action = useRadarAction();
  const company = useCompanyWrite();
  const boardy = useBoardyBrief();
  const judgment = useJudgment();

  const person = (id: string) => data?.people.find((p) => p.id === id);

  /** v1 frAct: POST action {id, action, ...extra}; toast "Recorded: <action>". A refusal is toasted by useAction. */
  const act = useCallback(
    async (id: string, a: string, extra: Record<string, unknown> = {}) => {
      try {
        await action.mutateAsync({ id, action: a, ...extra });
        toast.show("Recorded: " + a, "ok");
        return true;
      } catch {
        return false;
      }
    },
    [action, toast],
  );

  const askNote = async (id: string, n: NoteAsk) => {
    const v = await ask(noteSpec(n));
    if (!v) return false;
    return act(id, n.action, noteExtra(n, v));
  };

  const mergeToast = (r: { ok: boolean; error?: string }) => toast.show(r.ok ? "Merged" : plainText(r.error) || "merge refused", r.ok ? "ok" : "error");

  const companyWrite = async (body: { key: string } & Record<string, unknown>, done: string) => {
    try {
      await company.mutateAsync(body);
      toast.show(done, "ok");
    } catch {
      /* toasted */
    }
  };

  return {
    dialog,
    ask,
    act,
    refresh,

    watch: (id: string) => act(id, "watch"),
    investigate: (id: string) => act(id, "investigate_founder"),
    research: (id: string) => act(id, "research"),
    dismiss: (id: string) => askNote(id, NOTE_ASKS.dismiss),
    linkCompany: (id: string) => askNote(id, NOTE_ASKS.linkCompany),
    linkEvent: (id: string) => askNote(id, NOTE_ASKS.linkEvent),
    opportunity: (id: string) => askNote(id, NOTE_ASKS.opportunity),
    introPath: (id: string) => askNote(id, NOTE_ASKS.introPath),
    boardyStatus: (id: string, status: string) => act(id, "boardy", { status }),
    saveLinkedin: (id: string, url: string) => act(id, "linkedin", { url }),

    async linkedinVerified(id: string, url: string) {
      if (!url) {
        toast.show("Enter the canonical profile URL first", "error");
        return;
      }
      const v = await ask(LINKEDIN_VERIFIED);
      if (v) await act(id, "linkedin", linkedinVerifiedExtra(url, v));
    },

    async personEvidence(id: string) {
      const v = await ask(PERSON_EVIDENCE);
      if (v) await act(id, "evidence", personEvidenceExtra(v));
    },

    async confirmIdentity(id: string) {
      const p = person(id);
      if (!p) return;
      const v = await ask(confirmIdentitySpec(p));
      if (v) await act(id, "confirm_identity", confirmIdentityExtra(v));
    },

    async verifyIdentity(id: string) {
      const v = await ask(VERIFY_IDENTITY);
      if (v) await act(id, "verify_identity", verifyIdentityExtra(v));
    },

    async merge(id: string) {
      const v: Values | null = await ask(MERGE);
      if (!v) return;
      const other = sv(v, "other");
      try {
        const r = await postMerge({ id, other });
        if (r.needs_confirmation) {
          if (await ask(MERGE_CONFIRM)) mergeToast(await postMerge({ id, other, confirm: true }));
        } else mergeToast(r);
      } catch (e) {
        toast.show(e instanceof Error ? e.message : "merge refused", "error");
      }
      await refresh();
    },

    async boardyBrief(id: string): Promise<string> {
      const r = await boardy.mutateAsync({ id });
      toast.show("Brief prepared — nothing was sent", "ok");
      return `${r.brief || ""}\n\n(${r.note || ""})`;
    },

    saveJudgment: (id: string, human_judgment: string) => judgment.mutateAsync({ id, human_judgment }).catch(() => undefined),

    async companyEvidence(key: string) {
      const v = await ask(COMPANY_EVIDENCE);
      if (v) await companyWrite(companyEvidenceBody(key, v), "Company evidence saved with provenance");
    },

    async companyFact(key: string) {
      const v = await ask(COMPANY_FACT);
      if (v) await companyWrite(companyFactBody(key, v), `Sourced company fact recorded (binds only to ${sv(v, "field")})`);
    },
  };
}

export type FrActions = ReturnType<typeof useFrActions>;
