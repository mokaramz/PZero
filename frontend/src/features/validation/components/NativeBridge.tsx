import { Panel } from "@/components/ui";
import { NOT_PORTED } from "../model/deferred";
import type { ValidationPayload } from "../model/types";
import { BRIDGE_COST, BRIDGE_STEPS, bridgeMetrics, topAlpha, usd } from "../model/view";

const TITLE = "Native search bridge — production pilot";

/** "What does it cost?" — the native search bridge pilot: a compact funnel, spend and source / query alpha. The pilot
 *  depends on the Scout search bridge, which is never ported, so the server answers `{available: false, reason}` and the
 *  panel keeps its place with the reason (the old page rendered nothing for a null answer, leaving the tab empty). */
export function NativeBridge({ bridge }: { bridge: ValidationPayload["native_bridge"] }) {
  const m = bridgeMetrics(bridge);
  if (!m)
    return (
      <Panel title={TITLE} data-testid="val-native-bridge">
        <p className="small faint" data-testid="val-native-bridge-deferred">
          {NOT_PORTED.bridge}
        </p>
      </Panel>
    );
  const s = m.status;
  return (
    <Panel title={TITLE} data-testid="val-native-bridge">
      <div className="small">
        {BRIDGE_STEPS.map(([k, l], i) => (
          <span key={k}>
            {i ? " → " : ""}
            <b>{m.funnel[k] ?? 0}</b> {l}
          </span>
        ))}
        {m.convergence ? ` · ${m.convergence} cross-scout convergence` : ""}.
      </div>
      <div className="small">
        Spend ${m.spend_usd.toFixed(2)} (today ${s.day_usd.toFixed(2)} of ${s.daily_cap.toFixed(2)} · month ${s.month_usd.toFixed(2)} of $
        {s.monthly_cap.toFixed(2)} · X {s.x_hunts_this_week}/{s.x_hunts_per_week} this week · {s.state}). Cost per{" "}
        {BRIDGE_COST.map(([k, l]) => `${l} ${usd(m.cost_per[k])}`).join(" · ")}.
      </div>
      <div className="small faint">
        Alpha (INVESTIGATE / found) — lane: {topAlpha(m.alpha.lane)}; geography: {topAlpha(m.alpha.geography)}; web vs X: {topAlpha(m.alpha.web_vs_x)};
        source: {topAlpha(m.alpha.source)}.
      </div>
      <div className="small faint">{m.note}</div>
    </Panel>
  );
}
