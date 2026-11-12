import { Badge } from "@/components/ui";
import styles from "../FounderCalls.module.css";

export const FC_LABEL = "Founder-reported — unverified";

/** v1 `fcDueTag`. */
export function DueTag({ state }: { state: string }) {
  if (state === "overdue") return <Badge tone="red">OVERDUE</Badge>;
  if (state === "due") return <Badge tone="red">DUE TODAY</Badge>;
  if (state === "upcoming") return <Badge tone="amber">DUE SOON</Badge>;
  if (state === "done") return <Badge tone="green">DONE</Badge>;
  if (state === "open") return <Badge>OPEN</Badge>;
  return null;
}

/** The amber "Founder-reported — unverified" label that travels with every founder statement. */
export function FcLabel({ text = FC_LABEL }: { text?: string }) {
  return <span className={styles.fclbl}>{text}</span>;
}

export function Unk({ text = "UNKNOWN" }: { text?: string }) {
  return <span className={styles.unk}>{text}</span>;
}
