import { useId, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { linkTarget } from "../model/links";

/** An intelligence link (decision d): a route when its target exists here, otherwise plain text followed by the
 *  visible reason (when there is one). */
export function GeoLink({ link, children }: { link: string | null | undefined; children: ReactNode }) {
  const t = linkTarget(link);
  const id = useId();
  if (t.to !== null) return <Link to={t.to}>{children}</Link>;
  if (!t.reason) return <>{children}</>;
  return (
    <>
      <span data-deferred="" title={t.reason} aria-describedby={id}>
        {children}
      </span>{" "}
      <span id={id} className="muted small">
        ({t.reason})
      </span>
    </>
  );
}
