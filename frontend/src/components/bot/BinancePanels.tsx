import type { ReactNode } from "react";

import type { ExchangeVenue } from "@/features/trading/queries";
import type { ExchangeOrder, ExchangePosition, ExchangeStatus, LiveState } from "@/lib/api/client";
import { formatPrice, formatUtc } from "@/lib/format";

import {
  aboveLossStop,
  budgetProfit,
  heldOnBinance,
  nowText,
  protection,
  STALE_SECONDS,
  usdtOrDash,
} from "./binance";
import { percent, Stat, tone, usdt } from "./BotPanels";
import { strategyLabel } from "./trades";

function money(value: string | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Number(value).toFixed(2)} USDT`;
}

function age(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "never";
  if (seconds < 90) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)} min ago`;
}

const LIVE_COMMAND = "cd backend && uv run python -m trading_intel.entrypoints.binance_live";

/** How to connect the real futures wallet (D060), shown until the bot has seen USDT in it. */
function LiveSetup() {
  return (
    <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
      <li>
        In the terminal run <code className="text-ink">{LIVE_COMMAND} keygen</code>. The private key stays on this
        Mac; it prints a public key.
      </li>
      <li>
        On binance.com: API Management, Create API, Self-generated. Paste the public key and tick Enable Futures
        only. Leave withdrawals, transfers, spot, margin and options off: the bot refuses such a key.
      </li>
      <li>Put the API key Binance shows in .env as BINANCE_LIVE_API_KEY, and restart the quant worker.</li>
      <li>Move the USDT the bot may trade into your USDⓈ-M futures wallet.</li>
      <li>
        Run <code className="text-ink">{LIVE_COMMAND} check</code> to see any problem. Then turn real trading on with
        the switch that appears here. Nothing trades until then.
      </li>
    </ol>
  );
}

/** Whether the real account may trade, and anything the hourly check with Binance found. */
function LiveChecks({ state }: { state: LiveState | null | undefined }) {
  if (!state) return null;
  return (
    <div className="mt-2 space-y-1 text-xs">
      {state.armed ? (
        <p className="font-semibold text-good">
          Armed: the bot opens trades here at its signals{state.armed_at ? `, since ${formatUtc(state.armed_at)}` : ""}.
        </p>
      ) : (
        <p className="font-semibold text-warn">Not armed: no new trades. Turn real trading on below.</p>
      )}
      {state.problems.length ? (
        <ul role="alert" className="list-disc pl-5 text-bad">
          {state.problems.map((problem) => (
            <li key={problem}>{problem[0]!.toUpperCase() + problem.slice(1)}. No new trades until it is fixed.</li>
          ))}
        </ul>
      ) : null}
      {state.ip_restricted === false ? (
        <p className="text-muted">
          The key is not restricted to this computer&apos;s IP. Binance recommends adding the restriction.
        </p>
      ) : null}
    </div>
  );
}

/**
 * A Binance account the bot trades: demo trading's budget of test funds (D048), or the owner's
 * real futures wallet, where what they put in is the capital (D060).
 */
export function BinanceAccount({
  status,
  venue = "demo",
  control,
}: {
  status: ExchangeStatus;
  venue?: ExchangeVenue;
  control?: ReactNode; // The account's on/off switch (D063, D064).
}) {
  const live = venue === "live";
  const title = live ? "Binance real account" : "Binance demo account";
  if (!status.connected) {
    return (
      <section aria-label={title} className="rounded border border-line bg-panel p-3">
        <h2 className="mb-2 text-sm font-semibold">{title}</h2>
        {live ? (
          <LiveSetup />
        ) : (
          <p className="text-sm text-muted">
            Waiting for the quant worker&apos;s first check of Binance. It runs once a minute while the
            demo key is set.
          </p>
        )}
      </section>
    );
  }
  const profit = budgetProfit(status) ?? 0;
  const bots = status.positions.filter((position) => position.bot !== false);
  const owners = status.positions.length - bots.length;
  const held = heldOnBinance(bots);
  const stale = (status.age_seconds ?? 0) > STALE_SECONDS;
  const room = aboveLossStop(status);
  const capital = Number(status.capital);
  return (
    <section aria-label={title} className="rounded border border-line bg-panel p-3">
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      <dl className="grid grid-cols-2 gap-3">
        <Stat label={live ? "Put in" : "Budget"} value={money(status.capital)} />
        <Stat label="Equity now" value={money(status.equity)} />
        <Stat label="Profit" value={`${usdt(profit)} USDT`} className={tone(profit)} />
        <Stat
          label={live ? "Profit on what you put in" : "Profit on budget"}
          value={capital > 0 ? percent((profit / capital) * 100) : "–"}
          className={tone(profit)}
        />
        <Stat label="In open trades" value={`${held.value.toFixed(2)} USDT`} />
        <Stat label="Margin held" value={`${held.margin.toFixed(2)} USDT`} />
        <Stat label="Free for margin" value={money(status.available)} />
        <Stat label="Open positions" value={String(bots.length)} />
        {owners ? <Stat label="Your own positions" value={String(owners)} /> : null}
        {status.loss_floor ? <Stat label="Loss stop at" value={money(status.loss_floor)} /> : null}
        {room !== null ? <Stat label="Left above the stop" value={`${room.toFixed(2)} USDT`} /> : null}
      </dl>
      {live ? <LiveChecks state={status.live} /> : null}
      {control}
      {status.loss_stopped_at ? (
        <p role="alert" className="mt-2 text-xs font-semibold text-warn">
          Stopped by the loss stop at {formatUtc(status.loss_stopped_at)}. No new trades until the owner sets
          new limits; open trades keep their stops and targets.
        </p>
      ) : null}
      {live ? (
        <p className="mt-2 text-xs text-muted">
          Real money in your futures wallet. The bot reads only this wallet, never Spot, Funding or the Overview,
          and its key cannot withdraw or transfer. USDT you move in or out changes what you put in, never the
          profit. Your own positions count in the margin and the risk, and the bot leaves them alone. Isolated
          margin; stops and targets are held by Binance.
        </p>
      ) : (
        <p className="mt-2 text-xs text-muted">
          Test funds on Binance: {money(status.binance_equity)}. The bot uses only its {capital.toFixed(0)} USDT
          budget plus its own profit and loss. Isolated margin; stops and targets are held by Binance.
        </p>
      )}
      <p role={stale ? "alert" : undefined} className={`mt-1 text-xs ${stale ? "text-warn" : "text-muted"}`}>
        Checked on Binance {age(status.age_seconds)}
        {stale ? ": the quant worker may be stopped" : ""}.
      </p>
    </section>
  );
}

/**
 * One open Binance position with the stop and targets Binance holds for it. `action` is the
 * close button, shown only for the bot's own trades: the owner's are closed in the Binance app.
 */
export function BinancePosition({
  status,
  position,
  tickSize,
  action,
}: {
  status: ExchangeStatus;
  position: ExchangePosition;
  tickSize: string | null;
  action?: ReactNode;
}) {
  const { stop, targets } = protection(status, position.symbol);
  const unrealized = Number(position.unrealized);
  const long = position.side === "LONG";
  const owners = position.bot === false;
  return (
    <section aria-label={`Open ${position.symbol} position on Binance`} className="rounded border border-line bg-panel p-3">
      <h2 className="mb-2 text-sm font-semibold">
        <span className={long ? "text-up" : "text-down"}>{long ? "BUY" : "SELL"}</span> {position.symbol},{" "}
        {owners ? "your own position" : "open on Binance"}
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
      {owners ? (
        <p className="mt-2 text-xs text-muted">
          You opened this one. The bot never gives it a stop, moves it or closes it; close it in the Binance app.
          Its margin and its whole value count against the bot&apos;s room for new trades.
        </p>
      ) : (
        <p className="mt-2 text-xs text-muted">
          {position.liquidation ? `Liquidation at ${formatPrice(position.liquidation, tickSize)}, well beyond the stop. ` : ""}
          Binance closes the position at the stop or the targets, even while this computer sleeps. If you close it
          in the Binance app, the bot sees it within a minute and its margin is free for the next trade.
        </p>
      )}
      {!owners && action ? <div className="mt-2">{action}</div> : null}
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

/** A cancel is named for what it removed: a stop being replaced, or orders on a closed coin. */
function orderLabel(order: ExchangeOrder): string {
  if (order.type === "CANCEL") return order.kind === "stop" ? "Stop cancelled" : "Orders cancelled";
  return KIND_LABEL[order.kind] ?? order.kind;
}

/** Every request the bot sent to a Binance account, newest first. */
export function BinanceOrders({
  orders,
  ticks,
  venue = "demo",
}: {
  orders: ExchangeOrder[];
  ticks: Map<string, string | null>;
  venue?: ExchangeVenue;
}) {
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
        <caption className="p-2 text-left text-sm font-semibold">
          Orders sent to {venue === "live" ? "your real account" : "Binance demo"}, all coins
        </caption>
        <thead className="text-xs text-muted">
          <tr>
            <th scope="col" className="p-2">Time</th>
            <th scope="col" className="p-2">Coin</th>
            <th scope="col" className="p-2">Strategy</th>
            <th scope="col" className="p-2">Order</th>
            <th scope="col" className="p-2">Side</th>
            <th scope="col" className="p-2 text-right">Quantity</th>
            <th scope="col" className="p-2 text-right">Price</th>
            <th scope="col" className="p-2 text-right">Value USDT</th>
            <th scope="col" className="p-2 text-right" title="What a stop loses or a target makes if it fills, before fees">
              If hit USDT
            </th>
            <th scope="col" className="p-2 text-right" title="On the entry: profit now while open, or the net result once closed">
              Now USDT
            </th>
            <th scope="col" className="p-2 text-right">Risk USDT</th>
            <th scope="col" className="p-2">Result</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => {
            const tick = ticks.get(order.symbol) ?? null;
            const filled = order.average_price ?? order.fill_price ?? null;
            const price = filled ?? order.trigger;
            return (
              <tr key={`${order.created_at}:${order.symbol}:${order.kind}`} className="border-t border-line">
                <td className="p-2 whitespace-nowrap">{formatUtc(order.created_at)}</td>
                <td className="p-2">{order.symbol}</td>
                <td className="p-2 text-xs">{order.strategy ? strategyLabel(order.strategy) : "–"}</td>
                <td className="p-2">{orderLabel(order)}</td>
                <td className={`p-2 font-semibold ${order.side === "BUY" ? "text-up" : "text-down"}`}>{order.side ?? "–"}</td>
                <td className="p-2 text-right">{order.executed ?? order.quantity ?? "whole position"}</td>
                <td className="p-2 text-right">
                  {price ? formatPrice(price, tick) : "–"}
                  {filled ? <span className="block text-xs text-muted">filled</span> : null}
                </td>
                <td className="p-2 text-right">{usdtOrDash(order.value_usdt)}</td>
                <td className={`p-2 text-right ${tone(Number(order.if_hit_usdt ?? 0))}`}>
                  {usdtOrDash(order.if_hit_usdt, true)}
                </td>
                <td className={`p-2 text-right whitespace-nowrap ${tone(Number(order.now_usdt ?? 0))}`}>{nowText(order)}</td>
                <td className="p-2 text-right">{usdtOrDash(order.risk_usdt)}</td>
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
