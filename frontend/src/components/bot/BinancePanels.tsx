import type { ExchangeOrder, ExchangePosition, ExchangeStatus } from "@/lib/api/client";
import { formatPrice, formatUtc } from "@/lib/format";

import { budgetProfit, heldOnBinance, protection, STALE_SECONDS } from "./binance";
import { percent, Stat, tone, usdt } from "./BotPanels";

function money(value: string | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Number(value).toFixed(2)} USDT`;
}

function age(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "never";
  if (seconds < 90) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)} min ago`;
}

/** The bot's budget on Binance demo trading, and the test funds behind it. */
export function BinanceAccount({ status }: { status: ExchangeStatus }) {
  if (!status.connected) {
    return (
      <section aria-label="Binance demo account" className="rounded border border-line bg-panel p-3">
        <h2 className="mb-2 text-sm font-semibold">Binance demo account</h2>
        <p className="text-sm text-muted">
          Waiting for the quant worker&apos;s first check of Binance. It runs once a minute while the
          demo key is set.
        </p>
      </section>
    );
  }
  const profit = budgetProfit(status) ?? 0;
  const held = heldOnBinance(status.positions);
  const stale = (status.age_seconds ?? 0) > STALE_SECONDS;
  return (
    <section aria-label="Binance demo account" className="rounded border border-line bg-panel p-3">
      <h2 className="mb-2 text-sm font-semibold">Binance demo account</h2>
      <dl className="grid grid-cols-2 gap-3">
        <Stat label="Budget" value={money(status.capital)} />
        <Stat label="Equity now" value={money(status.equity)} />
        <Stat label="Profit" value={`${usdt(profit)} USDT`} className={tone(profit)} />
        <Stat label="Profit on budget" value={percent((profit / Number(status.capital)) * 100)} className={tone(profit)} />
        <Stat label="In open trades" value={`${held.value.toFixed(2)} USDT`} />
        <Stat label="Margin held" value={`${held.margin.toFixed(2)} USDT`} />
        <Stat label="Free for margin" value={money(status.available)} />
        <Stat label="Open positions" value={String(status.positions.length)} />
      </dl>
      <p className="mt-2 text-xs text-muted">
        Test funds on Binance: {money(status.binance_equity)}. The bot uses only its {Number(status.capital).toFixed(0)}{" "}
        USDT budget plus its own profit and loss. Isolated margin; stops and targets are held by Binance.
      </p>
      <p role={stale ? "alert" : undefined} className={`mt-1 text-xs ${stale ? "text-warn" : "text-muted"}`}>
        Checked on Binance {age(status.age_seconds)}
        {stale ? ": the quant worker may be stopped" : ""}.
      </p>
    </section>
  );
}

/** One open Binance position with the stop and targets Binance holds for it. */
export function BinancePosition({
  status,
  position,
  tickSize,
}: {
  status: ExchangeStatus;
  position: ExchangePosition;
  tickSize: string | null;
}) {
  const { stop, targets } = protection(status, position.symbol);
  const unrealized = Number(position.unrealized);
  const long = position.side === "LONG";
  return (
    <section aria-label={`Open ${position.symbol} position on Binance`} className="rounded border border-line bg-panel p-3">
      <h2 className="mb-2 text-sm font-semibold">
        <span className={long ? "text-up" : "text-down"}>{long ? "BUY" : "SELL"}</span> {position.symbol}, open on
        Binance
      </h2>
      <dl className="grid grid-cols-2 gap-3">
        <Stat label="Entry" value={formatPrice(position.entry_price, tickSize)} />
        <Stat label="Mark price" value={formatPrice(position.mark_price, tickSize)} />
        <Stat
          label="Stop"
          value={stop ? formatPrice(stop.trigger, tickSize) : "None: being restored"}
          className="text-bad"
        />
        <Stat
          label="Targets"
          value={targets.length ? targets.map((t) => formatPrice(t.trigger, tickSize)).join(" / ") : "–"}
          className="text-good"
        />
        <Stat label="Size" value={String(Number(position.quantity))} />
        <Stat label="In the trade" value={`${Number(position.notional).toFixed(2)} USDT`} />
        <Stat label="Open profit" value={`${usdt(unrealized)} USDT`} className={tone(unrealized)} />
        <Stat label="Margin" value={`${Number(position.margin).toFixed(2)} USDT`} />
      </dl>
      <p className="mt-2 text-xs text-muted">
        {position.liquidation ? `Liquidation at ${formatPrice(position.liquidation, tickSize)}, well beyond the stop. ` : ""}
        Binance closes the position at the stop or the targets, even while this computer sleeps.
      </p>
    </section>
  );
}

const KIND_LABEL: Record<string, string> = {
  entry: "Entry",
  stop: "Stop",
  tp1: "Target 1",
  tp2: "Target 2",
  tp3: "Target 3",
  close: "Close",
};

/** Every request the bot sent to Binance demo trading, newest first. */
export function BinanceOrders({ orders, ticks }: { orders: ExchangeOrder[]; ticks: Map<string, string | null> }) {
  if (orders.length === 0) {
    return (
      <p className="rounded border border-line bg-panel p-3 text-sm text-muted">
        No orders sent to Binance yet. The first one appears here, and on the chart, when Python finds a setup
        that passes the risk engine.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded border border-line bg-panel">
      <table className="w-full text-left text-sm tabular-nums">
        <caption className="p-2 text-left text-sm font-semibold">Orders sent to Binance demo, all coins</caption>
        <thead className="text-xs text-muted">
          <tr>
            <th scope="col" className="p-2">Time</th>
            <th scope="col" className="p-2">Coin</th>
            <th scope="col" className="p-2">Order</th>
            <th scope="col" className="p-2">Side</th>
            <th scope="col" className="p-2 text-right">Quantity</th>
            <th scope="col" className="p-2 text-right">Price</th>
            <th scope="col" className="p-2">Result</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => {
            const tick = ticks.get(order.symbol) ?? null;
            const price = order.average_price ?? order.trigger;
            return (
              <tr key={`${order.created_at}:${order.symbol}:${order.kind}`} className="border-t border-line">
                <td className="p-2 whitespace-nowrap">{formatUtc(order.created_at)}</td>
                <td className="p-2">{order.symbol}</td>
                <td className="p-2">{KIND_LABEL[order.kind] ?? order.kind}</td>
                <td className={`p-2 font-semibold ${order.side === "BUY" ? "text-up" : "text-down"}`}>{order.side ?? "–"}</td>
                <td className="p-2 text-right">{order.executed ?? order.quantity ?? "whole position"}</td>
                <td className="p-2 text-right">
                  {price ? formatPrice(price, tick) : "–"}
                  {order.average_price ? <span className="block text-xs text-muted">filled</span> : null}
                </td>
                <td className={`p-2 ${order.outcome === "accepted" ? "text-good" : "text-bad"}`} title={order.error ?? undefined}>
                  {order.outcome === "accepted" ? "Accepted" : order.outcome === "no reply" ? "No reply, checked within a minute" : `Refused: ${order.error ?? ""}`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
