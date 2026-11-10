import type { Instrument, PaperSummary, Signal, Trade } from "@/lib/api/client";
import { formatPrice, formatUtc } from "@/lib/format";

import {
  actionOf,
  averageExit,
  openPnl,
  percentOf,
  realizedPnl,
  resultOf,
  riskPercent,
  strategyLabel,
  today,
} from "./trades";

function usdt(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

function percent(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function tone(value: number): string {
  if (value > 0) return "text-good";
  if (value < 0) return "text-bad";
  return "text-ink";
}

function Stat({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`text-base font-semibold tabular-nums ${className}`}>{value}</dd>
    </div>
  );
}

function Side({ trade }: { trade: Trade }) {
  const action = actionOf(trade);
  return <span className={`font-semibold ${action === "BUY" ? "text-up" : "text-down"}`}>{action}</span>;
}

function risk(share: string | null | undefined): string | null {
  const value = riskPercent(share);
  return value === null ? null : `${value.toFixed(2)}%`;
}

function Today({ summary }: { summary: PaperSummary }) {
  const day = today(summary);
  if (day.stopPercent === null) {
    return null;
  }
  return (
    <div className="mt-3 border-t border-line pt-3">
      <div className="flex items-baseline justify-between text-xs text-muted">
        <span>Today, UTC</span>
        <span>New trades stop at +{day.stopPercent.toFixed(2)}%</span>
      </div>
      <p className={`text-base font-semibold tabular-nums ${tone(day.pnl)}`}>
        {usdt(day.pnl)} USDT, {percent(day.percent)}
      </p>
      <div
        role="progressbar"
        aria-label="Progress to today's profit stop"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(day.progress * 100)}
        className="mt-1 h-2 overflow-hidden rounded bg-raised"
      >
        <div className="h-full bg-good" style={{ width: `${day.progress * 100}%` }} />
      </div>
      {day.riskLimit === null ? null : (
        <p className="mt-2 text-xs text-muted">
          At risk in open trades: {day.atRisk.toFixed(2)} of {day.riskLimit.toFixed(2)} USDT allowed.
          The stop is a ceiling, not a goal: Python never trades more to reach it.
        </p>
      )}
    </div>
  );
}

export function BotAccount({ summary, title }: { summary: PaperSummary; title: string }) {
  const equity = Number(summary.equity);
  const change = equity - Number(summary.starting_balance);
  const winRate =
    summary.win_rate === null ? "None yet" : `${(summary.win_rate * 100).toFixed(0)}%`;
  return (
    <section aria-label={title} className="rounded border border-line bg-panel p-3">
      <h2 className="mb-2 text-sm font-semibold">{title}</h2>
      <dl className="grid grid-cols-2 gap-3">
        <Stat label="Started with" value={`${Number(summary.starting_balance).toFixed(2)} USDT`} />
        <Stat label="Equity now" value={`${equity.toFixed(2)} USDT`} />
        <Stat label="Profit" value={`${usdt(change)} USDT`} className={tone(change)} />
        <Stat
          label="Profit on start"
          value={percent(percentOf(change, summary.starting_balance))}
          className={tone(change)}
        />
        <Stat label="Wins / losses" value={`${summary.wins} / ${summary.losses}`} />
        <Stat label="Win rate" value={winRate} />
        <Stat label="Open trades" value={String(summary.open_positions)} />
        <Stat label="Costs paid" value={`${Number(summary.costs).toFixed(2)} USDT`} />
      </dl>
      <p className="mt-2 text-xs text-muted">
        Equity counts open trades at the latest price. Profit is after fees, spread, slippage and
        funding.
      </p>
      <Today summary={summary} />
    </section>
  );
}

type OpenProps = { trade: Trade; mid: number | null; tickSize: string | null; balance: string };

export function OpenTrade({ trade, mid, tickSize, balance }: OpenProps) {
  const open = openPnl(trade, mid);
  const entry = trade.average_entry ?? trade.planned_entry;
  return (
    <section aria-label={`Open ${trade.symbol} trade`} className="rounded border border-line bg-panel p-3">
      <h2 className="mb-2 text-sm font-semibold">
        <Side trade={trade} /> {trade.symbol}, {resultOf(trade).toLowerCase()}
      </h2>
      <p className="mb-2 text-xs text-muted">
        {strategyLabel(trade.strategy)}
        {risk(trade.risk_share) ? `, risking ${risk(trade.risk_share)} of equity` : ""}
      </p>
      <dl className="grid grid-cols-2 gap-3">
        <Stat label="Entry" value={formatPrice(entry, tickSize)} />
        <Stat label="Stop" value={formatPrice(trade.current_stop, tickSize)} className="text-bad" />
        <Stat
          label="Targets"
          value={trade.targets.map((price) => formatPrice(price, tickSize)).join(" / ")}
          className="text-good"
        />
        <Stat label="Size" value={trade.open_quantity} />
        <Stat
          label="Open profit, live"
          value={open === null ? "Waiting for price" : `${usdt(open)} USDT`}
          className={open === null ? "" : tone(open)}
        />
        <Stat
          label={`On ${Number(balance).toFixed(0)} USDT`}
          value={open === null ? "–" : percent(percentOf(open, balance))}
          className={open === null ? "" : tone(open)}
        />
      </dl>
      <p className="mt-2 text-xs text-muted">{trade.explanation}</p>
    </section>
  );
}

export function Decisions({ signals, symbols }: { signals: Signal[]; symbols: Map<number, string> }) {
  return (
    <section aria-label="Python's latest signals" className="rounded border border-line bg-panel p-3">
      <h2 className="mb-1 text-sm font-semibold">Python&apos;s latest signals</h2>
      <p className="mb-2 text-xs text-muted">
        Every setup Python found, and what the risk engine decided. Closes with no setup are not
        listed.
      </p>
      {signals.length === 0 ? (
        <p className="text-sm text-muted">No setups yet. Python checks every coin at each 15M close.</p>
      ) : (
        <ul className="space-y-2 text-sm">
          {signals.map((signal) => (
            <li key={signal.id} className="border-t border-line pt-2 first:border-t-0 first:pt-0">
              <span className={`font-semibold ${signal.action === "BUY" ? "text-up" : "text-down"}`}>
                {signal.action}
              </span>{" "}
              {symbols.get(signal.instrument_id) ?? `#${signal.instrument_id}`}{" "}
              <span className="text-xs text-muted">
                {strategyLabel(signal.strategy)}, {formatUtc(signal.created_at)}
              </span>
              <div className={signal.decision === "APPROVED" ? "text-good" : "text-warn"}>
                {signal.decision === "APPROVED"
                  ? `Approved, traded${risk(signal.risk_share) ? ` at ${risk(signal.risk_share)} risk` : ""}`
                  : `Refused: ${signal.rejection_codes.join(", ")}`}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

type HistoryProps = { trades: Trade[]; balance: string; ticks: Map<number, string | null> };

export function TradeHistory({ trades, balance, ticks }: HistoryProps) {
  if (trades.length === 0) {
    return (
      <p className="rounded border border-line bg-panel p-3 text-sm text-muted">
        No trades yet in this account. The first one appears here, and on the chart, when Python
        finds a setup that passes the risk engine.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto rounded border border-line bg-panel">
      <table className="w-full text-left text-sm tabular-nums">
        <caption className="p-2 text-left text-sm font-semibold">Trade history, all coins</caption>
        <thead className="text-xs text-muted">
          <tr>
            <th scope="col" className="p-2">Signal time</th>
            <th scope="col" className="p-2">Coin</th>
            <th scope="col" className="p-2">Strategy</th>
            <th scope="col" className="p-2">Side</th>
            <th scope="col" className="p-2 text-right">Risked USDT</th>
            <th scope="col" className="p-2 text-right">Entry</th>
            <th scope="col" className="p-2 text-right">Exit</th>
            <th scope="col" className="p-2">Result</th>
            <th scope="col" className="p-2 text-right">Profit USDT</th>
            <th scope="col" className="p-2 text-right">On {Number(balance).toFixed(0)} USDT</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => {
            const tick = ticks.get(trade.instrument_id);
            const exit = averageExit(trade);
            const pnl = realizedPnl(trade);
            const done = trade.status === "closed";
            return (
              <tr key={trade.id} className="border-t border-line">
                <td className="p-2 whitespace-nowrap">{formatUtc(trade.created_at)}</td>
                <td className="p-2">{trade.symbol}</td>
                <td className="p-2 whitespace-nowrap">{strategyLabel(trade.strategy)}</td>
                <td className="p-2">
                  <Side trade={trade} />
                </td>
                <td className="p-2 text-right" title={risk(trade.risk_share) ?? undefined}>
                  {trade.max_account_risk === null ? "–" : Number(trade.max_account_risk).toFixed(2)}
                </td>
                <td className="p-2 text-right">
                  {trade.average_entry ? formatPrice(trade.average_entry, tick) : "Not filled"}
                </td>
                <td className="p-2 text-right">
                  {exit === null ? "–" : formatPrice(String(exit), tick)}
                </td>
                <td className="p-2">{resultOf(trade)}</td>
                <td className={`p-2 text-right ${done ? tone(pnl) : "text-muted"}`}>
                  {done ? usdt(pnl) : `${usdt(pnl)} so far`}
                </td>
                <td className={`p-2 text-right ${done ? tone(pnl) : "text-muted"}`}>
                  {percent(percentOf(pnl, balance))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Tick sizes and symbols by instrument id, for trades on coins other than the chart's. */
export function lookups(instruments: Instrument[]) {
  return {
    ticks: new Map(instruments.map((item) => [item.id, item.tick_size] as const)),
    symbols: new Map(instruments.map((item) => [item.id, item.symbol] as const)),
  };
}
