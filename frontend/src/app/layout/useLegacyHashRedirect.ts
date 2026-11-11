import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { pathForLegacyView } from "../nav";

/** v1 deep links used hashes (`/#pipe`); on `/` only, map them onto the new routes once (history entry replaced). */
export function useLegacyHashRedirect() {
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const view = location.hash.replace(/^#/, "");
    const target = view ? pathForLegacyView(view) : undefined;
    if (target && location.pathname === "/") navigate(target, { replace: true });
  }, [location.hash, location.pathname, navigate]);
}
