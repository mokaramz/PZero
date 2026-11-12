import { cx } from "@/lib/format";
import type { Company } from "../model/types";
import { DueTag } from "./bits";
import styles from "../FounderCalls.module.css";

type TreeProps = {
  companies: Company[];
  /** the selected call (highlighted unless the form is open) */
  selected: string | null;
  formOpen: boolean;
  onSelect: (callId: string) => void;
  onLog: (founderId: string, companyId: string) => void;
  onLinkCompany: (companyId: string) => void;
  onLinkFounder: (founderId: string) => void;
};

/** Company → Founder → calls. A company or founder not yet linked to a Project Zero record is "external", with a link
 *  button; a linked company says what it is linked to (pipeline or radar). */
export function CallTree({ companies, selected, formOpen, onSelect, onLog, onLinkCompany, onLinkFounder }: TreeProps) {
  return (
    <nav className={styles.tree} aria-label="Companies, founders and calls" data-testid="calls-tree">
      {companies.length ? (
        companies.map((co) => (
          <div key={co.id} className={styles.co} data-testid="tree-company">
            <div className={styles.coName}>
              <span>{co.name}</span>
              {co.external ? (
                <span className={styles.tagN} title="not yet linked to a Project Zero company record">
                  external
                </span>
              ) : (
                <span className={styles.tagG} title="linked to an existing Project Zero record">
                  {co.linked_pipeline_slug ? "pipeline" : "radar"}
                </span>
              )}
              <span className={styles.sub}>
                {co.call_count} call{co.call_count === 1 ? "" : "s"}
              </span>
              {co.external && (
                <button type="button" className={styles.lnk} onClick={() => onLinkCompany(co.id)}>
                  link
                </button>
              )}
            </div>
            {co.founders.map((f) => (
              <div key={f.id} className={styles.f} data-testid="tree-founder">
                <div className={styles.fName}>
                  <b>{f.name}</b>
                  {f.linked_person_id ? (
                    <span className={styles.tagG} title="linked to an existing Project Zero person">
                      linked
                    </span>
                  ) : (
                    <>
                      <span className={styles.tagN}>external</span>
                      <button type="button" className={styles.lnk} onClick={() => onLinkFounder(f.id)}>
                        link
                      </button>
                    </>
                  )}
                  <button type="button" className={styles.lnk} onClick={() => onLog(f.id, co.id)}>
                    + Log call
                  </button>
                </div>
                {f.calls.length ? (
                  f.calls.map((c) => (
                    <button
                      type="button"
                      key={c.id}
                      className={cx(styles.callRow, c.id === selected && !formOpen && styles.callSel)}
                      onClick={() => onSelect(c.id)}
                      aria-current={c.id === selected || undefined}
                    >
                      <span className={styles.num}>{c.date}</span>
                      <span>{c.call_type_label}</span>
                      <DueTag state={c.due_state} />
                    </button>
                  ))
                ) : (
                  <div className={styles.noCalls}>no calls yet</div>
                )}
              </div>
            ))}
          </div>
        ))
      ) : (
        <div className={styles.treeEmpty}>
          No calls yet. <b>Add external founder call</b>, or use <b>Log founder call</b> on a Conviction company, a Founder Radar lead or a Network person.
        </div>
      )}
    </nav>
  );
}
