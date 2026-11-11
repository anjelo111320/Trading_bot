/**
 * Binance demo trading on the Bot page (D048): what the quant worker last saved from Binance,
 * and the orders it sent. Test funds only. The page never talks to Binance itself.
 */

import type { SeriesMarker, Time, UTCTimestamp } from "lightweight-charts";

import { DOWN, UP } from "@/components/chart/bars";
import type { PriceLevel } from "@/components/chart/CandleChart";
import type { ExchangeOpenOrder, ExchangeOrder, ExchangePosition, ExchangeStatus } from "@/lib/api/client";

import { COLORS } from "./trades";

/** A snapshot older than this means the quant worker has stopped checking Binance. */
export const STALE_SECONDS = 180;

export function isStop(order: ExchangeOpenOrder): boolean {
  return order.type === "STOP_MARKET" || order.type === "STOP";
}

/** A limit entry resting on Binance, waiting to fill (D054). */
export function isEntry(order: ExchangeOpenOrder): boolean {
  return order.type === "LIMIT";
}

/** The coin's limit entry still waiting on Binance, if any. */
export function waitingEntry(status: ExchangeStatus | undefined, symbol: string): ExchangeOpenOrder | null {
  return status?.orders.find((order) => order.symbol === symbol && isEntry(order)) ?? null;
}

/** The stop and the targets Binance holds for one coin, targets nearest first. */
export function protection(status: ExchangeStatus, symbol: string) {
  const mine = status.orders.filter((order) => order.symbol === symbol && !isEntry(order));
  const position = status.positions.find((item) => item.symbol === symbol);
  const stop = mine.find(isStop) ?? null;
  const entry = Number(position?.entry_price ?? waitingEntry(status, symbol)?.trigger ?? 0);
  const distance = (order: ExchangeOpenOrder) => Math.abs(Number(order.trigger) - entry);
  const targets = mine.filter((order) => !isStop(order)).sort((a, b) => distance(a) - distance(b));
  return { stop, targets };
}

/** Entry, stop and targets of the coin's open Binance position, or of its waiting limit entry. */
export function binanceLines(status: ExchangeStatus | undefined, symbol: string): PriceLevel[] {
  const position = status?.positions.find((item) => item.symbol === symbol);
  const waiting = waitingEntry(status, symbol);
  if (!status || (!position && !waiting)) return [];
  const { stop, targets } = protection(status, symbol);
  const action = (position ? position.side === "LONG" : waiting?.side === "BUY") ? "BUY" : "SELL";
  const lines: PriceLevel[] = [
    position
      ? { price: Number(position.entry_price), color: COLORS.entry, title: `${action} entry`, dashed: false }
      : { price: Number(waiting!.trigger), color: COLORS.entry, title: `${action} limit, waiting`, dashed: true },
  ];
  if (stop) lines.push({ price: Number(stop.trigger), color: COLORS.stop, title: "Stop", dashed: true });
  targets.forEach((target, index) =>
    lines.push({ price: Number(target.trigger), color: COLORS.target, title: `TP${index + 1}`, dashed: true }),
  );
  return lines;
}

/**
 * Entries Binance filled, as arrows, and closes the bot sent, as dots. Stops and targets that
 * Binance triggers itself are not reported back yet, so they show only as the lines vanishing.
 * Nor is a limit entry's later fill: an accepted limit that had not filled gets no arrow, and
 * its fill shows as the waiting line becoming the position.
 */
export function binanceMarkers(orders: ExchangeOrder[], symbol: string, step: number): SeriesMarker<Time>[] {
  return orders
    .filter((order) => order.symbol === symbol && order.outcome === "accepted")
    .filter((order) => (order.kind === "entry" || order.kind === "close") && order.type !== "CANCEL")
    .filter((order) => order.type !== "LIMIT" || Number(order.executed ?? 0) > 0)
    .map((order) => {
      const time = (Math.floor(Date.parse(order.created_at) / 1000 / step) * step) as UTCTimestamp;
      const buy = order.side === "BUY";
      if (order.kind === "entry") {
        return {
          id: `${order.created_at}:${order.kind}`,
          time,
          position: buy ? "belowBar" : "aboveBar",
          shape: buy ? "arrowUp" : "arrowDown",
          color: buy ? UP : DOWN,
          text: buy ? "BUY" : "SELL",
        } satisfies SeriesMarker<Time>;
      }
      return {
        id: `${order.created_at}:${order.kind}`,
        time,
        position: buy ? "belowBar" : "aboveBar",
        shape: "circle",
        color: COLORS.stop,
        text: "CLOSE",
      } satisfies SeriesMarker<Time>;
    })
    .sort((a, b) => Number(a.time) - Number(b.time));
}

/** USDT held in Binance positions, at the mark price, and the margin they lock. */
export function heldOnBinance(positions: ExchangePosition[]): { value: number; margin: number } {
  return positions.reduce(
    (sum, item) => ({ value: sum.value + Number(item.notional), margin: sum.margin + Number(item.margin) }),
    { value: 0, margin: 0 },
  );
}

/** The bot's profit on its budget: equity above the capital it started with. */
export function budgetProfit(status: ExchangeStatus): number | null {
  return status.equity === null || status.equity === undefined ? null : Number(status.equity) - Number(status.capital);
}

/** USDT the budget can still lose before its loss stop (D053), or null without one. */
export function aboveLossStop(status: ExchangeStatus): number | null {
  if (status.loss_floor === null || status.loss_floor === undefined) return null;
  if (status.equity === null || status.equity === undefined) return null;
  return Math.max(Number(status.equity) - Number(status.loss_floor), 0);
}
