import { formatPrice, formatUtc } from "@/lib/format";

import { type ChartFocus, tradeText, tradeTone } from "./focus";
import { strategyLabel } from "./trades";

/**
 * The trade the chart is showing (D065), above the chart: its fills and its result. `onBack`
 * returns to the Signals page it was opened from.
 */
export function FocusBar({
  focus,
  tickSize,
  onBack,
  onClear,
}: {
  focus: ChartFocus;
  tickSize: string | null;
  onBack?: () => void;
  onClear: () => void;
}) {
  const buy = focus.side === "BUY";
  const at = (price: string | null) => (price ? ` at ${formatPrice(price, tickSize)}` : "");
  return (
    <div
      role="status"
      aria-label="Trade shown on the chart"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-raised px-3 py-2 text-xs"
    >
      <span className="text-sm font-semibold">
        <span className={buy ? "text-up" : "text-down"}>{focus.side}</span> {focus.symbol}
      </span>
      <span className="text-muted">
        {strategyLabel(focus.strategy)}, {focus.account}
      </span>
      <span>
        Entered {formatUtc(focus.openedAt)}
        {at(focus.entryPrice)}
      </span>
      <span>{focus.closedAt ? `Closed ${formatUtc(focus.closedAt)}${at(focus.exitPrice)}` : "Still open"}</span>
      <span className={`font-semibold ${tradeTone(focus.state, focus.net)}`}>{tradeText(focus.state, focus.net)}</span>
      <span className="ml-auto flex gap-2">
        {onBack ? (
          <button
            type="button"
            onClick={onBack}
            className="min-h-9 cursor-pointer rounded border border-line px-2 text-xs text-ink hover:border-ink"
          >
            Back to signals
          </button>
        ) : null}
        <button
          type="button"
          onClick={onClear}
          aria-label="Stop showing this trade"
          className="min-h-9 cursor-pointer rounded border border-line px-2 text-xs text-muted hover:text-ink"
        >
          Clear
        </button>
      </span>
    </div>
  );
}
