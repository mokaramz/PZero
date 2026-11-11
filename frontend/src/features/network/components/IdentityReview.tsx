import { Disclosure } from "@/components/focus";
import { NOT_PORTED } from "../model/deferred";
import styles from "../Network.module.css";

/**
 * The identity question (old `features/identity/IdentityReview`) keeps its quiet row above the network, but its data and
 * its three answers (same person / different people / not a founder) arrive with the identity port: the row says so
 * and nothing is read or written.
 */
export function IdentityReview() {
  return (
    <div data-deferred="">
      <Disclosure title="Identity review" icon="people" hint={NOT_PORTED.identity} testId="identity-review" className={styles.identity}>
        <p className="small faint">
          <b>What does this mean?</b> The same name can be two different people, and one person can appear in several records. Project Zero never
          merges identities on its own — it asks you. Your answer is recorded; no record is rewritten.
        </p>
        <div className="small faint" data-testid="identity-deferred">
          {NOT_PORTED.identity}.
        </div>
      </Disclosure>
    </div>
  );
}
