/**
 * The bot accounts' simulated trades as chart marks and history rows (D044, D045). Every number
 * here comes from stored fills. Profit is shown in USDT and as a share of the starting balance.
 */

import type { SeriesMarker, Time, UTCTimestamp } from "lightweight-charts";

import type { PaperSummary, SignalScore, Trade, TradeFill } from "@/lib/api/client";

import { DOWN, UP } from "@/components/chart/bars";
import type { PriceLevel } from "@/components/chart/CandleChart";

export const COLORS = { entry: "#f8fafc", stop: "#ef4444", target: "#22c55e" } as const;

const EXITS = new Set(["tp1", "tp2", "tp3", "stop"]);
const EXIT_LABEL: Record<string, string> = { tp1: "TP1", tp2: "TP2", tp3: "TP3", stop: "STOP" };
const OPEN_STATUSES = new Set(["pending_entry", "open"]);
const STRATEGY_LABEL: Record<string, string> = {
  daily_trend: "Daily trend",
  pattern_breakout: "1H pattern",
  trend_break_baseline: "15M rule",
};
// Every bot account risks at most 1% of equity per trade, before the money plan's share.
const RISK_PER_TRADE = 1;

function seconds(iso: string): number {
  return Date.parse(iso) / 1000;
}

function sign(trade: Trade): number {
  return trade.side === "LONG" ? 1 : -1;
}

/** BUY for a long entry, SELL for a short one. An exit trades the other way. */
export function actionOf(trade: Trade): "BUY" | "SELL" {
  return trade.side === "LONG" ? "BUY" : "SELL";
}

export function isOpen(trade: Trade): boolean {
  return OPEN_STATUSES.has(trade.status);
}

function exitsOf(trade: Trade): TradeFill[] {
  return trade.fills.filter((fill) => EXITS.has(fill.kind) && fill.price !== null);
}

/** An arrow at each entry and a dot at each exit, on the bar that holds the fill. */
export function tradeMarkers(trades: Trade[], step: number): SeriesMarker<Time>[] {
  const marks: SeriesMarker<Time>[] = [];
  for (const trade of trades) {
    const long = trade.side === "LONG";
    for (const fill of trade.fills) {
      const time = (Math.floor(seconds(fill.at) / step) * step) as UTCTimestamp;
      if (fill.kind === "entry") {
        marks.push({
          id: `${trade.id}:entry`,
          time,
          position: long ? "belowBar" : "aboveBar",
          shape: long ? "arrowUp" : "arrowDown",
          color: long ? UP : DOWN,
          text: actionOf(trade),
        });
      } else if (EXITS.has(fill.kind)) {
        const stopped = fill.kind === "stop";
        marks.push({
          id: `${trade.id}:${fill.kind}`,
          time,
          position: long ? "aboveBar" : "belowBar",
          shape: "circle",
          color: stopped ? COLORS.stop : COLORS.target,
          text: EXIT_LABEL[fill.kind],
        });
      }
    }
  }
  return marks.sort((a, b) => Number(a.time) - Number(b.time));
}

/** Entry, current stop and the targets not yet reached, for each open trade. */
export function openLines(trades: Trade[]): PriceLevel[] {
  const lines: PriceLevel[] = [];
  for (const trade of trades.filter(isOpen)) {
    const reached = new Set(trade.fills.map((fill) => fill.kind));
    const entry = trade.average_entry ?? trade.planned_entry;
    lines.push({ price: Number(entry), color: COLORS.entry, title: `${actionOf(trade)} entry`, dashed: false });
    lines.push({ price: Number(trade.current_stop), color: COLORS.stop, title: "Stop", dashed: true });
    trade.targets.forEach((price, index) => {
      if (!reached.has(`tp${index + 1}`)) {
        lines.push({ price: Number(price), color: COLORS.target, title: `TP${index + 1}`, dashed: true });
      }
    });
  }
  return lines;
}

/** The quantity-weighted exit price, or null before any exit. */
export function averageExit(trade: Trade): number | null {
  const exits = exitsOf(trade);
  const quantity = exits.reduce((sum, fill) => sum + Number(fill.quantity), 0);
  if (quantity === 0) {
    return null;
  }
  return exits.reduce((sum, fill) => sum + Number(fill.price) * Number(fill.quantity), 0) / quantity;
}

/** Open profit at the live mid, before exit costs, which are paid only on exit. */
export function openPnl(trade: Trade, mid: number | null): number | null {
  if (mid === null || trade.status !== "open" || trade.average_entry === null) {
    return null;
  }
  return sign(trade) * (mid - Number(trade.average_entry)) * Number(trade.open_quantity);
}

/** Realized profit after every cost paid so far: fees, spread, slippage and funding. */
export function realizedPnl(trade: Trade): number {
  return Number(trade.realized_pnl);
}

export function percentOf(value: number, balance: string): number {
  return (value / Number(balance)) * 100;
}

/** What happened to a trade, in words. */
export function resultOf(trade: Trade): string {
  if (trade.status === "pending_entry") {
    return "Waiting to enter";
  }
  if (trade.status === "open") {
    return exitsOf(trade).length > 0 ? "Open, part taken" : "Open";
  }
  if (trade.status === "cancelled") {
    return "Not filled";
  }
  const last = exitsOf(trade).at(-1);
  const how = last ? EXIT_LABEL[last.kind] : "closed";
  return `${trade.outcome ?? "Closed"} at ${how}`;
}

export function strategyLabel(name: string): string {
  return STRATEGY_LABEL[name] ?? name;
}

/** The money plan's risk for a trade as a percent of equity, or null outside the plan. */
export function riskPercent(share: string | null | undefined): number | null {
  return share ? Number(share) * RISK_PER_TRADE : null;
}

type Reading = boolean | null;

function reading(value: Reading): string {
  return value === null ? "unknown" : value ? "for" : "against";
}

/**
 * The signal score's conditions in words (docs/34). It failed its test (D046), so it is shown
 * as information beside the decision and never changes a trade's size.
 */
export function scoreText(score: SignalScore | null | undefined): string | null {
  if (!score) return null;
  const conditions: [string, Reading][] = [
    ["coin's trend", score.long_term_trend],
    ...(score.bitcoin_applies ? [["Bitcoin's trend", score.bitcoin_trend] as [string, Reading]] : []),
    ["volume", score.volume],
    ["funding", score.funding],
  ];
  const verdict = score.weak === null ? "incomplete" : score.weak ? "weak" : "strong";
  const parts = conditions.map(([name, value]) => `${name} ${reading(value)}`).join(", ");
  return `Score ${verdict}, ${score.against} of ${conditions.length} against: ${parts}.`;
}

export type Today = {
  pnl: number;
  percent: number;
  stopPercent: number | null;
  progress: number;
  atRisk: number;
  riskLimit: number | null;
};

/** Today's profit against the plan's daily stop, and what open trades could lose now. */
export function today(summary: PaperSummary): Today {
  const start = Number(summary.day_start_equity);
  const equity = Number(summary.equity);
  const pnl = equity - start;
  const percent = start > 0 ? (pnl / start) * 100 : 0;
  const stopPercent = summary.daily_profit_stop === null ? null : Number(summary.daily_profit_stop) * 100;
  const progress = stopPercent ? Math.min(Math.max(percent / stopPercent, 0), 1) : 0;
  const riskLimit = summary.max_open_risk === null ? null : equity * Number(summary.max_open_risk);
  return { pnl, percent, stopPercent, progress, atRisk: Number(summary.open_risk), riskLimit };
}
