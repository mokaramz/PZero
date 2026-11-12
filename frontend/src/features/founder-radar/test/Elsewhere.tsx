import { useLocation } from "react-router-dom";

/** Where a link took the operator (every other route of the app, in the page tests). */
export function Elsewhere() {
  const loc = useLocation();
  return <p data-testid="elsewhere">{loc.pathname + loc.search}</p>;
}
