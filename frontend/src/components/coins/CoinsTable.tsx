import { Fragment, useState } from "react";

import { tone } from "@/components/bot/BotPanels";
import { signedR } from "@/components/bot/results";
import { strategyLabel } from "@/components/bot/trades";
import type { CoinCard, EntryQuality, LiveResult, StrategyCell } from "@/lib/api/client";

const COLUMNS = 9;
// A coin whose entries often went half their risk against them, measured on 3 or more.
const OFTEN = 0.5;
const ENOUGH = 3;

/** "2 of 3 won, 1 open", or that nothing traded yet. */
export function liveText(live: LiveResult): string {
  if (live.entered === 0) return "No trades yet";
  const open = live.entered - live.closed;
  const closed = live.closed ? `${live.won} of ${live.closed} won` : "None closed";
  return open ? `${closed}, ${open} open` : closed;
}

/** A move against the trade, never below zero, so it needs no sign: "0.55R". */
export function againstR(value: string | null | undefined): string {
  return value === null || value === undefined ? "–" : `${Number(value).toFixed(2)}R`;
}

function spreadText(bps: string | null): string {
  if (bps === null) return "no fresh spread";
  return Number(bps) === 0 ? "under 0.1 bp spread" : `${bps} bp spread`;
}

/** "3 of 5 went 0.5R against", from the entries with a full first hour. */
export function againstText(entries: EntryQuality): string {
  return entries.trades ? `${entries.went_against} of ${entries.trades} went 0.5R against` : "–";
}

export function enteredBadly(entries: EntryQuality): boolean {
  return entries.trades >= ENOUGH && entries.went_against / entries.trades >= OFTEN;
}

function testedText(cells: StrategyCell[]): string {
  const tested = cells.filter((cell) => cell.evidence).length;
  return tested ? `${tested} of ${cells.length}` : "None";
}

function evidenceText(cell: StrategyCell): string {
  const evidence = cell.evidence;
  if (!evidence) return cell.untested ?? "Untested";
  return `${signedR(evidence.mean_r)} a trade over ${evidence.trades} trades, 95% range ${signedR(evidence.low)} to ${signedR(evidence.high)} (${evidence.source})`;
}

function StrategyRows({ cells }: { cells: StrategyCell[] }) {
  return (
    <table className="w-full text-left text-xs tabular-nums">
      <caption className="sr-only">Each strategy on this coin</caption>
      <thead className="text-muted">
        <tr>
          <th scope="col" className="p-2">Strategy</th>
          <th scope="col" className="p-2">Backtest, 2020 to 2025</th>
          <th scope="col" className="p-2">Live</th>
          <th scope="col" className="p-2 text-right">Live mean</th>
          <th scope="col" className="p-2">First hour</th>
          <th scope="col" className="p-2">On this coin</th>
        </tr>
      </thead>
      <tbody>
        {cells.map((cell) => (
          <tr key={cell.strategy} className="border-t border-line align-top">
            <th scope="row" className="p-2 font-normal">{strategyLabel(cell.strategy)}</th>
            <td className={`p-2 ${cell.evidence ? tone(Number(cell.evidence.mean_r)) : "text-muted"}`}>
              {evidenceText(cell)}
            </td>
            <td className="p-2">{liveText(cell.live)}</td>
            <td className={`p-2 text-right ${tone(Number(cell.live.mean_r ?? 0))}`}>{signedR(cell.live.mean_r)}</td>
            <td className={`p-2 ${enteredBadly(cell.entries) ? "text-warn" : ""}`}>
              {cell.entries.trades ? `${againstR(cell.entries.first_hour_r)} against, ${againstText(cell.entries)}` : "–"}
            </td>
            <td className={`p-2 ${cell.left_out ? "text-warn" : "text-muted"}`}>
              {cell.left_out ? "Switched off after its study" : "Trades"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * One row per coin, opening to every strategy on it (D068). Each row says what backs the
 * strategies there, what live trading did, and how far entries went against in their first hour.
 */
export function CoinsTable({ coins }: { coins: CoinCard[] }) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = (symbol: string) =>
    setExpanded((now) => {
      const next = new Set(now);
      if (!next.delete(symbol)) next.add(symbol);
      return next;
    });
  return (
    // Relative, so the hidden column name stays inside the scrolling box on a phone.
    <div className="relative overflow-x-auto rounded border border-line bg-panel">
      <table className="w-full text-left text-sm tabular-nums">
        <caption className="p-2 text-left text-sm font-semibold">Every coin the bot trades</caption>
        <thead className="text-xs text-muted">
          <tr>
            <th scope="col" className="p-2">
              <span className="sr-only">Details</span>
            </th>
            <th scope="col" className="p-2">Coin</th>
            <th scope="col" className="p-2" title="Strategies with a backtest on this coin">
              Backtested
            </th>
            <th scope="col" className="p-2">Live trades</th>
            <th scope="col" className="p-2 text-right" title="Closed trades: net result over planned risk">
              Live mean
            </th>
            <th scope="col" className="p-2" title="Median of how far the price went against each entry in its first hour">
              First hour
            </th>
            <th scope="col" className="p-2 text-right" title="Median of how much worse than planned the entry filled">
              Fill vs plan
            </th>
            <th scope="col" className="p-2" title="1H ATR over price, spread, and missing candles not yet repaired">
              Now
            </th>
            <th scope="col" className="p-2">Today&apos;s signals</th>
          </tr>
        </thead>
        <tbody>
          {coins.map((coin) => {
            const open = expanded.has(coin.symbol);
            const now = coin.conditions;
            return (
              <Fragment key={coin.symbol}>
                <tr className="border-t border-line align-top">
                  <td className="p-2">
                    <button
                      type="button"
                      aria-expanded={open}
                      aria-label={`Every strategy on ${coin.symbol}`}
                      onClick={() => toggle(coin.symbol)}
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
                  <td className="p-2 font-semibold">{coin.symbol}</td>
                  <td className={`p-2 ${coin.strategies.some((cell) => cell.evidence) ? "" : "text-warn"}`}>
                    {testedText(coin.strategies)}
                  </td>
                  <td className="p-2">{liveText(coin.live)}</td>
                  <td className={`p-2 text-right ${tone(Number(coin.live.mean_r ?? 0))}`}>{signedR(coin.live.mean_r)}</td>
                  <td className={`p-2 ${enteredBadly(coin.entries) ? "text-warn" : ""}`}>
                    {coin.entries.trades ? againstR(coin.entries.first_hour_r) : "–"}
                    <span className="block text-xs text-muted">{againstText(coin.entries)}</span>
                  </td>
                  <td className="p-2 text-right">{signedR(coin.entries.slippage_r)}</td>
                  <td className="p-2 text-xs">
                    {now.atr_percent ? `${now.atr_percent}% an hour` : "–"}
                    <span className="block text-muted">{spreadText(now.spread_bps)}</span>
                    {now.open_gaps ? (
                      <span className="block text-warn">
                        {now.open_gaps} data gap{now.open_gaps === 1 ? "" : "s"}
                      </span>
                    ) : null}
                  </td>
                  <td className="p-2 text-xs">
                    {now.signals_today ? `${now.approved_today} of ${now.signals_today} approved` : "None yet"}
                    {now.top_refusal ? <span className="block text-muted break-words">most refused: {now.top_refusal}</span> : null}
                  </td>
                </tr>
                {open ? (
                  <tr>
                    <td colSpan={COLUMNS} className="bg-raised px-3 pb-3">
                      <StrategyRows cells={coin.strategies} />
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
