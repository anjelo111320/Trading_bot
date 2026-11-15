import Link from "next/link";
import { Fragment, useState } from "react";

import { chartHref, tradeTone } from "@/components/bot/focus";
import { strategyLabel } from "@/components/bot/trades";
import { SignalDetails } from "@/components/trading/SignalCard";
import type { SignalAccount } from "@/features/trading/queries";
import type { Signal } from "@/lib/api/client";
import { formatPrice, formatUtc } from "@/lib/format";

import { signalResult } from "./filters";

export type Coin = { symbol: string; tickSize: string | null };

const COLUMNS = 13;

function number(value: string | null | undefined, digits: number): string {
  return value === null || value === undefined ? "–" : Number(value).toFixed(digits);
}

/**
 * Signals, newest first, one row each. A row opens to everything the risk engine weighed, and
 * an entered trade's Chart link opens it on the Bot page's chart, as the Binance app does (D065).
 */
export function SignalsTable({
  signals,
  account,
  accountLabel,
  coins,
}: {
  signals: Signal[];
  account: SignalAccount;
  accountLabel: string;
  coins: ReadonlyMap<number, Coin>;
}) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = (id: string) =>
    setExpanded((now) => {
      const next = new Set(now);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  return (
    // Relative, so the hidden column names stay inside the scrolling box on a phone.
    <div className="relative overflow-x-auto rounded border border-line bg-panel">
      <table className="w-full text-left text-sm tabular-nums">
        <caption className="p-2 text-left text-sm font-semibold">Signals on {accountLabel}, newest first</caption>
        <thead className="text-xs text-muted">
          <tr>
            <th scope="col" className="p-2">
              <span className="sr-only">Details</span>
            </th>
            <th scope="col" className="p-2">Time</th>
            <th scope="col" className="p-2">Coin</th>
            <th scope="col" className="p-2">Strategy</th>
            <th scope="col" className="p-2">Side</th>
            <th scope="col" className="p-2 text-right">Entry</th>
            <th scope="col" className="p-2 text-right">Stop</th>
            <th scope="col" className="p-2 text-right">Targets</th>
            <th scope="col" className="p-2 text-right" title="Reward to risk after fees, to the last target">
              Net R:R
            </th>
            <th scope="col" className="p-2 text-right" title="What the risk engine planned to lose at the stop">
              Risk USDT
            </th>
            <th scope="col" className="p-2">Risk engine</th>
            <th scope="col" className="p-2" title="From Binance's own fills, or the paper simulator's">
              Result
            </th>
            <th scope="col" className="p-2">
              <span className="sr-only">Chart</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {signals.map((signal) => {
            const coin = coins.get(signal.instrument_id);
            const symbol = coin?.symbol ?? `#${signal.instrument_id}`;
            const tick = coin?.tickSize ?? null;
            const price = (value: string | null | undefined) => (value ? formatPrice(value, tick) : "–");
            const buy = signal.action === "BUY";
            const approved = signal.decision === "APPROVED";
            const open = expanded.has(signal.id);
            const href = coin ? chartHref(signal, account, coin.symbol) : null;
            const trade = signal.trade ?? null;
            return (
              <Fragment key={signal.id}>
                <tr className="border-t border-line align-top">
                  <td className="p-2">
                    <button
                      type="button"
                      aria-expanded={open}
                      aria-label={`Details of the ${signal.action} ${symbol} signal at ${formatUtc(signal.created_at)}`}
                      onClick={() => toggle(signal.id)}
                      className="min-h-9 min-w-9 cursor-pointer rounded border border-line text-muted hover:text-ink"
                    >
                      <svg
                        aria-hidden="true"
                        viewBox="0 0 16 16"
                        className={`mx-auto h-3.5 w-3.5 transition-transform duration-150 ${open ? "rotate-90" : ""}`}
                      >
                        <path
                          d="M6 3l5 5-5 5"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                  </td>
                  <td className="p-2 whitespace-nowrap">{formatUtc(signal.created_at)}</td>
                  <td className="p-2 font-semibold">{symbol}</td>
                  <td className="p-2 text-xs">
                    {strategyLabel(signal.strategy)}
                    <span className="block text-muted">{signal.timeframe.toUpperCase()}</span>
                  </td>
                  <td className={`p-2 font-semibold ${buy ? "text-up" : "text-down"}`}>{signal.action}</td>
                  <td className="p-2 text-right whitespace-nowrap">
                    {price(signal.entry_price)}
                    {trade?.entry_price ? (
                      <span className="block text-xs text-muted">filled {price(trade.entry_price)}</span>
                    ) : signal.entry_type === "LIMIT" ? (
                      <span className="block text-xs text-muted">limit</span>
                    ) : null}
                  </td>
                  <td className="p-2 text-right whitespace-nowrap">{price(signal.stop_loss)}</td>
                  <td className="p-2 text-right text-xs">
                    {signal.targets.length ? signal.targets.map((target) => price(target.price)).join(" / ") : "–"}
                  </td>
                  <td className="p-2 text-right">{number(signal.reward_risk_net, 2)}</td>
                  <td className="p-2 text-right">{number(signal.max_account_risk, 2)}</td>
                  <td className={`p-2 ${approved ? "text-good" : "text-warn"}`}>
                    {approved ? "Approved" : "Rejected"}
                    {!approved && signal.rejection_codes.length ? (
                      <span className="block text-xs break-words">{signal.rejection_codes.join(", ")}</span>
                    ) : null}
                  </td>
                  <td className={`p-2 whitespace-nowrap ${trade ? tradeTone(trade.state, trade.net ?? null) : "text-muted"}`}>
                    {signalResult(signal)}
                    {trade?.closed_at ? (
                      <span className="block text-xs text-muted">closed {formatUtc(trade.closed_at)}</span>
                    ) : null}
                  </td>
                  <td className="p-2">
                    {href ? (
                      <Link
                        href={href}
                        aria-label={`Show the ${symbol} trade on the chart`}
                        className="inline-flex min-h-9 items-center rounded border border-line px-2 text-xs text-ink hover:border-ink"
                      >
                        Chart
                      </Link>
                    ) : null}
                  </td>
                </tr>
                {open ? (
                  <tr>
                    <td colSpan={COLUMNS} className="bg-raised px-3 pb-3">
                      <SignalDetails signal={signal} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
