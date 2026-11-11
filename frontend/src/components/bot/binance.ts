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

/** The stop and the targets Binance holds for one coin, targets nearest first. */
export function protection(status: ExchangeStatus, symbol: string) {
  const mine = status.orders.filter((order) => order.symbol === symbol);
  const position = status.positions.find((item) => item.symbol === symbol);
  const stop = mine.find(isStop) ?? null;
  const entry = Number(position?.entry_price ?? 0);
  const distance = (order: ExchangeOpenOrder) => Math.abs(Number(order.trigger) - entry);
  const targets = mine.filter((order) => !isStop(order)).sort((a, b) => distance(a) - distance(b));
  return { stop, targets };
}

/** Entry, stop and targets of the coin's open Binance position, as chart lines. */
export function binanceLines(status: ExchangeStatus | undefined, symbol: string): PriceLevel[] {
  const position = status?.positions.find((item) => item.symbol === symbol);
  if (!status || !position) return [];
  const { stop, targets } = protection(status, symbol);
  const action = position.side === "LONG" ? "BUY" : "SELL";
  const lines: PriceLevel[] = [
    { price: Number(position.entry_price), color: COLORS.entry, title: `${action} entry`, dashed: false },
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
 */
export function binanceMarkers(orders: ExchangeOrder[], symbol: string, step: number): SeriesMarker<Time>[] {
  return orders
    .filter((order) => order.symbol === symbol && order.outcome === "accepted")
    .filter((order) => (order.kind === "entry" || order.kind === "close") && order.type !== "CANCEL")
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
