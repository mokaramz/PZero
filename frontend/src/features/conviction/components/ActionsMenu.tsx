import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

import { useDeferred } from "@/components/Deferred";
import { useToast } from "@/components/Toast";
import { cx } from "@/lib/format";
import { useAction } from "@/lib/hooks";
import { CONVICTION_KEYS, STATUS } from "../api";
import { NOT_PORTED } from "../model/deferred";
import { STATUSES, type Signal } from "../model/types";
import styles from "../Conviction.module.css";

export type DetailActions = {
  /** opens Edit & verify for the selected company */
  onEdit: () => void;
  /** opens the outreach email draft of the selected company */
  onEmail: () => void;
};

/** Secondary company actions — all still one click away, none competing with the decision. */
export function ActionsMenu({ e, actions }: { e: Signal; actions: DetailActions }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const setStatus = useAction<{ slug: string; status: string }>(STATUS, { invalidates: CONVICTION_KEYS, label: "Changing the pipeline status", quiet: true });
  const toast = useToast();
  const navigate = useNavigate();
  const close = () => ref.current?.removeAttribute("open");
  useEffect(() => {
    const away = (ev: MouseEvent) => {
      if (ref.current?.open && !ref.current.contains(ev.target as Node)) ref.current.removeAttribute("open");
    };
    const esc = (ev: KeyboardEvent) => ev.key === "Escape" && ref.current?.removeAttribute("open");
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, []);
  const item = (label: string, fn: () => void) => (
    <button
      type="button"
      className={styles.menuItem}
      onClick={() => {
        close();
        fn();
      }}
    >
      {label}
    </button>
  );
  const logCall = () => {
    const p = new URLSearchParams({
      new: "1",
      company: e.company,
      pipeline_slug: e.slug,
      name: e.founders?.[0]?.name ?? "",
      discovery_origin: e.discovery_source ?? "",
    });
    navigate(`/founder-calls?${p.toString()}`);
  };
  return (
    <details className={styles.menu} ref={ref} data-testid="company-actions">
      <summary className={styles.menuBtn}>Actions</summary>
      <div className={styles.menuPanel} role="group" aria-label="Company actions">
        {item("Edit & verify", actions.onEdit)}
        {item("Log founder call", logCall)}
        {item("Email draft", actions.onEmail)}
        <DeferredItem label="Send to Manager" reason={NOT_PORTED.manager} />
        {item("Ask PZ Associate", () => navigate(`/associate?company=${encodeURIComponent(e.slug)}`))}
        <label className={styles.menuStatus} data-testid="status-bar">
          <span>Pipeline status</span>
          <select
            aria-label="Change status"
            value={e.status || "new"}
            disabled={setStatus.isPending}
            onChange={(ev) => {
              const status = ev.target.value;
              setStatus.mutate({ slug: e.slug, status }, { onSuccess: () => toast.show(`Status → ${status}`, "ok") });
            }}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>
    </details>
  );
}

function DeferredItem({ label, reason }: { label: string; reason: string }) {
  const d = useDeferred(reason);
  return (
    <>
      <button type="button" {...d.props} className={cx(styles.menuItem, d.props.className)}>
        {label}
      </button>
      {d.note}
    </>
  );
}
