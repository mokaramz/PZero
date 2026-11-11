import { cx } from "@/lib/format";
import { aiStale } from "../model/attention";
import { NOT_PORTED } from "../model/deferred";
import type { Candidate } from "../model/types";
import { useDeferred } from "./Deferred";
import styles from "../DealFlow.module.css";

/** The Analyst line of the detail: the analysis state as before; every action on it waits for the analysis port. */
export function AnalystChip({ c }: { c: Candidate }) {
  const d = useDeferred(NOT_PORTED.analysis);
  const link = (label: string, green = false) => (
    <>
      <button type="button" {...d.props} className={cx(styles.link, green && styles.linkGreen, d.props.className)}>
        {label}
      </button>
      {d.note}
    </>
  );
  const s = c.analysis_state || "UNANALYZED";
  if (s === "ANALYZED") return link("Analyzed — review", true);
  if (s === "ANALYZING")
    return (
      <>
        <span className={styles.amberStrong}>Analyzing…</span> {link(aiStale(c) ? "stalled — restart" : "restart")}
      </>
    );
  if (s === "FAILED")
    return (
      <>
        <span className={styles.redStrong} title={c.analysis_error || ""}>
          Analysis failed{(c.analysis_error || "").includes("response preserved") ? " — response preserved" : ""}
        </span>{" "}
        {link("retry")}
      </>
    );
  return link("Analyze");
}
