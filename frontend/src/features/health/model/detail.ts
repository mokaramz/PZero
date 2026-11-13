/** What the detail drawer shows, and its title (ported from the old `HealthPage.tsx`). */
import { asRole } from "@/lib/roles";
import { shortModel, type PNode } from "./dashboard";
import type { Health, Issue, ModelRow, Run, Src } from "./types";

export type Detail =
  | { kind: "node"; node: PNode; lane: string }
  | { kind: "runs"; jobId: string; runs: Run[] }
  | { kind: "source"; src: Src }
  | { kind: "model"; m: ModelRow }
  | { kind: "issue"; i: Issue }
  | null;

export function detailTitle(x: Detail, d: Health): string {
  if (!x) return "";
  if (x.kind === "node") return x.node.name;
  if (x.kind === "runs") return d.jobs.find((j) => j.id === x.jobId)?.label ?? x.jobId;
  if (x.kind === "source") return x.src.name;
  if (x.kind === "model") return shortModel(x.m.model);
  return asRole(x.i.what.split(" — ")[0]);
}
