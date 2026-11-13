import { useLocation } from "react-router-dom";

/** Where a link or button took the page (every other route of the app, in the page tests). */
export function Landed() {
  const loc = useLocation();
  return <div data-testid="landed">{loc.pathname + loc.search}</div>;
}
