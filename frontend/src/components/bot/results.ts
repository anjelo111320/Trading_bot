/**
 * Binance demo's results on the Bot page (D057): formatting and shaping only. Every figure
 * comes from the API, which rebuilds completed trades from Binance's own fills.
 */

import type { Results, ResultStats } from "@/lib/api/client";

import { strategyLabel } from "./trades";

/** A rate given as a fraction, such as "0.5", shown as "50%". None shows as a dash. */
export function rate(value: string | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Math.round(Number(value) * 100)}%`;
}

/** USDT with a sign and two places, or four when it is under half a cent, or a dash. */
export function signedUsdt(value: string | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const number = Number(value);
  const places = number !== 0 && Math.abs(number) < 0.005 ? 4 : 2;
  return `${number > 0 ? "+" : ""}${number.toFixed(places)}`;
}

/** R with a sign and two places, or a dash. */
export function signedR(value: string | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}R`;
}

export function profitFactor(stats: ResultStats): string {
  if (stats.trades === 0) return "–";
  if (stats.profit_factor === null || stats.profit_factor === undefined) return "no losses";
  return Number(stats.profit_factor).toFixed(2);
}

export function streakText(current: number): string {
  if (current === 0) return "–";
  return current > 0 ? `${current} won in a row` : `${-current} lost in a row`;
}

export function sideLabel(side: string): string {
  return side === "LONG" ? "Long (buy)" : side === "SHORT" ? "Short (sell)" : side;
}

export function groupLabel(kind: "coin" | "strategy" | "side" | "day", name: string): string {
  if (kind === "strategy") return strategyLabel(name);
  if (kind === "side") return sideLabel(name);
  return name;
}

/** Equity after each closed trade, one point per second, for a time chart. */
export function equitySeries(results: Results): { time: number; value: number }[] {
  const bySecond = new Map<number, number>();
  for (const point of results.equity) {
    bySecond.set(Math.floor(Date.parse(point.at) / 1000), Number(point.equity));
  }
  return [...bySecond.entries()].sort((a, b) => a[0] - b[0]).map(([time, value]) => ({ time, value }));
}

/** The strategy x coin grid as rows of strategies and columns of coins, empty cells included. */
export function gridMatrix(results: Results) {
  const strategies = [...new Set(results.grid.map((cell) => cell.strategy))].sort();
  const symbols = [...new Set(results.grid.map((cell) => cell.symbol))].sort();
  const cells = new Map(results.grid.map((cell) => [`${cell.strategy}\t${cell.symbol}`, cell.stats]));
  return {
    strategies,
    symbols,
    cell: (strategy: string, symbol: string) => cells.get(`${strategy}\t${symbol}`) ?? null,
  };
}
