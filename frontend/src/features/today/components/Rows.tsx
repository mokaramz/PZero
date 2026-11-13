import { Link } from "react-router-dom";

import { StatusChip } from "@/components/focus";
import { Icon } from "@/components/Icon";
import { asRole } from "@/lib/roles";
import { type Action, type Mission, short } from "../missions";
import styles from "../Today.module.css";

/** One mission row: subject + what it is | why now | biggest unknown | state | next move + ONE open action. */
export function MissionRow({ m, featured }: { m: Mission; featured: boolean }) {
  const { a, k } = m;
  return (
    <li data-testid="today-action" data-type={a.type}>
      <article className={styles.mission} data-accent={k.field(a)} data-group={k.group} data-featured={featured || undefined}>
        <div className={styles.mSubject}>
          <h3 className={styles.mTitle}>
            {m.name}
            {m.score !== undefined && (
              <span className={styles.mScore} title="Verified score">
                {m.score}
              </span>
            )}
          </h3>
          <p className={styles.mLine}>{m.line}</p>
          <Details a={a} />
        </div>
        <div className={styles.mCol}>
          <span className={styles.mLabel}>
            <Icon name="trend" size={12} /> Why now
          </span>
          <p>{m.whyNow}</p>
        </div>
        <div className={styles.mCol}>
          {m.unknown && (
            <>
              <span className={styles.mLabel}>
                <Icon name="question" size={12} /> Biggest unknown
              </span>
              <p>{m.unknown}</p>
            </>
          )}
        </div>
        <div className={styles.mCol}>
          <span className={styles.mLabel}>
            <Icon name="layers" size={12} /> State
          </span>
          <StatusChip tone={k.field(a) === "risk" ? "risk" : k.field(a) === "progress" ? "progress" : "neutral"}>{m.state}</StatusChip>
        </div>
        <div className={styles.mMove}>
          <span className={styles.mLabel}>
            <Icon name="arrow" size={12} /> Next move
          </span>
          <span className={styles.mMoveText}>{asRole(k.move(a))}</span>
          <Link className={styles.mOpen} data-primary={featured || undefined} to={a.link} aria-label={`Open: ${m.name}`}>
            Open <Icon name="arrow" size={12} />
          </Link>
        </div>
      </article>
    </li>
  );
}

/** An event decision: the date tile read from the title ("Decide on X (YYYY-MM-DD, City)"). */
export function EventRow({ m }: { m: Mission }) {
  const d = m.a.title.match(/\((\d{4})-(\d{2})-(\d{2})/);
  const date = d ? new Date(Number(d[1]), Number(d[2]) - 1, Number(d[3])) : null;
  return (
    <li data-testid="today-action" data-type={m.a.type}>
      <article className={styles.item}>
        <span className={styles.dateTile} aria-hidden>
          {date ? (
            <>
              <span>{date.toLocaleDateString("en-GB", { month: "short" })}</span>
              <b>{date.getDate()}</b>
            </>
          ) : (
            <Icon name="calendar" size={16} />
          )}
        </span>
        <div className={styles.itemMain}>
          <h3 className={styles.itemTitle}>{m.name}</h3>
          <p className={styles.itemLine}>{m.line}</p>
          <Details a={m.a} />
        </div>
        <Link className={styles.itemOpen} to={m.a.link} aria-label={`Open: ${m.name}`}>
          Open <Icon name="arrow" size={12} />
        </Link>
      </article>
    </li>
  );
}

/** A decision blocked on the Manager. */
export function ManagerRow({ m }: { m: Mission }) {
  return (
    <li data-testid="today-action" data-type={m.a.type}>
      <article className={`${styles.item} ${styles.itemNoLead}`}>
        <div className={styles.itemMain}>
          <h3 className={styles.itemTitle}>{m.name}</h3>
          <p className={styles.itemLine}>{short(m.a.why, 16)}</p>
          <Details a={m.a} />
        </div>
        <span className={styles.due}>Decision due</span>
        <Link className={`${styles.itemOpen} ${styles.itemOpenNavy}`} to={m.a.link} aria-label={`Open: ${m.name}`}>
          Open <Icon name="arrow" size={12} />
        </Link>
      </article>
    </li>
  );
}

/** The full action text, folded (level 2). Role wording for the system text; nothing else is rewritten. */
function Details({ a }: { a: Action }) {
  return (
    <details className={styles.details}>
      <summary>Details</summary>
      <p>
        <b>{asRole(a.title)}</b>
      </p>
      <p>{asRole(a.why)}</p>
      {!!a.evidence.length && (
        <ul>
          {a.evidence.map((e) => (
            <li key={e}>{asRole(e)}</li>
          ))}
        </ul>
      )}
      <p>
        <b>Your next step:</b> {asRole(a.next_step)}
        {a.conflict !== "unknown" && <> · Project A conflict: {a.conflict}</>}
        {a.type === "CONTACT_FOUNDER" || a.type === "PREPARE_FOUNDER_CALL" ? (
          <> · founder contact {a.contact_appropriate ? "appropriate" : "not yet appropriate"}</>
        ) : null}
      </p>
    </details>
  );
}
