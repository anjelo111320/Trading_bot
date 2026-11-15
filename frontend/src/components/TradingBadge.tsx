"use client";

import { useLiveArmed } from "@/features/trading/queries";

/**
 * Whether real money can trade, on every page (D060). The bot opens real trades only once the
 * owner has armed the real account; until then everything else is paper or demo trading.
 */
export function TradingBadge() {
  const armed = useLiveArmed();
  return armed ? (
    <span className="rounded border border-warn px-2 py-0.5 text-xs font-semibold text-warn">Real money: armed</span>
  ) : (
    <span className="rounded border border-line px-2 py-0.5 text-xs text-muted">No real trades</span>
  );
}
