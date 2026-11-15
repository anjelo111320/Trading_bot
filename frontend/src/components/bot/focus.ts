/**
 * One trade shown on the Bot page's chart (D065), as the Binance app opens a trade on its chart:
 * from a Signals page link or the Results tab. The chart scrolls to the trade and marks its entry
 * and exit. Every time and price comes from the trade's fills, never from the signal's plan.
 */

import type { SeriesMarker, Time, UTCTimestamp } from "lightweight-charts";

import { DOWN, UP } from "@/components/chart/bars";
import type { SignalAccount } from "@/features/trading/queries";
import type { ClosedTrade, Signal, Timeframe } from "@/lib/api/client";
import { formatPrice } from "@/lib/format";

import { COLORS } from "./trades";

/** The Bot chart's timeframes. A 4H or daily signal opens on the 1H chart. */
export const CHART_TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h"];

export function chartTimeframe(timeframe: Timeframe): Timeframe {
  return CHART_TIMEFRAMES.includes(timeframe) ? timeframe : "1h";
}

export const ACCOUNT_LABEL: Record<SignalAccount, string> = {
  binance_live: "Binance real",
  binance: "Binance demo",
  portfolio: "Paper: money plan",
  demo: "Paper: demo bot",
  paper: "Paper: tested strategies",
};

export type ChartFocus = {
  key: string;
  symbol: string;
  side: "BUY" | "SELL";
  strategy: string;
  account: string;
  state: string; // open, won, lost or even.
  openedAt: string;
  closedAt: string | null;
  entryPrice: string | null;
  exitPrice: string | null;
  net: string | null;
};

/** A Signals page link: which signal to show, and the coin and timeframe to open on. */
export type ChartLink = { account: SignalAccount; signalId: string; symbol: string; timeframe: Timeframe };

/** The Bot page's address for a signal's trade on the chart, or null before it entered. */
export function chartHref(signal: Signal, account: SignalAccount, symbol: string): string | null {
  if (!signal.trade?.opened_at) return null;
  const query = new URLSearchParams({
    account,
    signal: signal.id,
    coin: symbol,
    tf: chartTimeframe(signal.timeframe),
  });
  return `/bot?${query}`;
}

/** The link in the Bot page's address, if it holds a whole one. */
export function readChartLink(params: Pick<URLSearchParams, "get">): ChartLink | null {
  const account = params.get("account");
  const signalId = params.get("signal");
  const symbol = params.get("coin");
  const timeframe = params.get("tf") as Timeframe | null;
  if (!account || !(account in ACCOUNT_LABEL) || !signalId || !symbol) return null;
  return {
    account: account as SignalAccount,
    signalId,
    symbol,
    timeframe: timeframe && CHART_TIMEFRAMES.includes(timeframe) ? timeframe : "15m",
  };
}

export function focusOfSignal(signal: Signal, symbol: string, account: SignalAccount): ChartFocus | null {
  const trade = signal.trade;
  if (!trade?.opened_at) return null;
  return {
    key: `signal:${signal.id}`,
    symbol,
    side: signal.action === "SELL" ? "SELL" : "BUY",
    strategy: signal.strategy,
    account: ACCOUNT_LABEL[account],
    state: trade.state,
    openedAt: trade.opened_at,
    closedAt: trade.closed_at ?? null,
    entryPrice: trade.entry_price ?? null,
    exitPrice: trade.exit_price ?? null,
    net: trade.net ?? null,
  };
}

export function focusOfTrade(trade: ClosedTrade, account: string): ChartFocus {
  return {
    key: `trade:${trade.symbol}:${trade.opened_at}`,
    symbol: trade.symbol,
    side: trade.side === "LONG" ? "BUY" : "SELL",
    strategy: trade.strategy,
    account,
    state: trade.won ? "won" : "lost",
    openedAt: trade.opened_at,
    closedAt: trade.closed_at,
    entryPrice: trade.entry_price ?? null,
    exitPrice: trade.exit_price ?? null,
    net: trade.net,
  };
}

function barOf(iso: string, step: number): number {
  return Math.floor(Date.parse(iso) / 1000 / step) * step;
}

/** Bars kept on each side of the trade, at least this many, or a quarter of its length. */
const PADDING_BARS = 20;

/**
 * The span the chart scrolls to: the trade with room on either side. An open trade runs to
 * `latest`, the newest bar's open time.
 */
export function focusRange(focus: ChartFocus, step: number, latest: number): { from: number; to: number } {
  const from = barOf(focus.openedAt, step);
  const to = focus.closedAt ? barOf(focus.closedAt, step) : Math.max(latest, from);
  const pad = Math.max(PADDING_BARS * step, Math.ceil((to - from) / 4 / step) * step);
  return { from: from - pad, to: to + pad };
}

export function signedUsdt(value: string | null): string {
  if (value === null) return "";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}`;
}

const STATE_TEXT: Record<string, string> = {
  waiting: "Waiting to fill",
  "not filled": "Not filled",
  refused: "Refused by Binance",
  even: "Even",
};

/** What became of a trade, in words, with its result in USDT: net once closed, open profit now. */
export function tradeText(state: string, net: string | null): string {
  const amount = net === null ? "" : ` ${signedUsdt(net)} USDT`;
  if (state === "won") return `Won${amount}`;
  if (state === "lost") return `Lost${amount}`;
  if (state === "open") return net === null ? "Open" : `Open,${amount} now`;
  return STATE_TEXT[state] ?? state;
}

/** Green for profit, red for a loss; muted when nothing was traded. */
export function tradeTone(state: string, net: string | null): string {
  if (state === "won") return "text-good";
  if (state === "lost") return "text-bad";
  if (state === "open" && net !== null) return Number(net) > 0 ? "text-good" : Number(net) < 0 ? "text-bad" : "text-ink";
  return state === "open" ? "text-ink" : "text-muted";
}

const EXIT_WORD: Record<string, string> = { won: "WON", lost: "LOST", even: "EVEN" };

/** The trade's entry as an arrow and its exit as a dot, with the fill price and the result. */
export function focusMarkers(focus: ChartFocus, step: number, tickSize: string | null): SeriesMarker<Time>[] {
  const buy = focus.side === "BUY";
  const entry = focus.entryPrice ? ` ${formatPrice(focus.entryPrice, tickSize)}` : "";
  const marks: SeriesMarker<Time>[] = [
    {
      id: `${focus.key}:entry`,
      time: barOf(focus.openedAt, step) as UTCTimestamp,
      position: buy ? "belowBar" : "aboveBar",
      shape: buy ? "arrowUp" : "arrowDown",
      color: buy ? UP : DOWN,
      text: `${focus.side}${entry}`,
      size: 1.5,
    },
  ];
  if (focus.closedAt) {
    marks.push({
      id: `${focus.key}:exit`,
      time: barOf(focus.closedAt, step) as UTCTimestamp,
      position: buy ? "aboveBar" : "belowBar",
      shape: "circle",
      color: focus.state === "won" ? COLORS.target : focus.state === "lost" ? COLORS.stop : COLORS.entry,
      text: `${EXIT_WORD[focus.state] ?? "EXIT"} ${signedUsdt(focus.net)}`.trim(),
      size: 1.5,
    });
  }
  return marks;
}

/**
 * The chart's markers with the focused trade's in place of any arrow or dot already on the same
 * bar, such as the entry the orders list marks, so a fill is never drawn twice.
 */
export function withFocus(markers: SeriesMarker<Time>[], focused: SeriesMarker<Time>[]): SeriesMarker<Time>[] {
  const taken = new Set(focused.map((marker) => `${String(marker.time)}:${marker.shape}`));
  return [...markers.filter((marker) => !taken.has(`${String(marker.time)}:${marker.shape}`)), ...focused].sort(
    (a, b) => Number(a.time) - Number(b.time),
  );
}
