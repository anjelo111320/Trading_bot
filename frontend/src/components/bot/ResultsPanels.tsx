import type { ClosedTrade, ResultGroup, Results, ResultStats } from "@/lib/api/client";
import { formatPrice, formatUtc } from "@/lib/format";

import { Stat, tone } from "./BotPanels";
import { EquityChart } from "./EquityChart";
import {
  groupLabel,
  gridMatrix,
  profitFactor,
  rate,
  sideLabel,
  signedR,
  signedUsdt,
  streakText,
} from "./results";
import { strategyLabel } from "./trades";

export type Period = "7d" | "30d" | "all";
const PERIODS: Record<Period, string> = { "7d": "7 days", "30d": "30 days", all: "All time" };

function money(value: string | null | undefined): string {
  return value === null || value === undefined ? "–" : `${signedUsdt(value)} USDT`;
}

export function PeriodSwitch({ value, onChange }: { value: Period; onChange: (value: Period) => void }) {
  return (
    <div role="group" aria-label="Results period" className="flex gap-1">
      {(Object.keys(PERIODS) as Period[]).map((item) => (
        <button
          key={item}
          type="button"
          aria-pressed={item === value}
          onClick={() => onChange(item)}
          className={`min-h-9 cursor-pointer rounded border px-2 text-xs transition-colors duration-150 ${
            item === value ? "border-ink bg-raised font-semibold text-ink" : "border-line text-muted hover:text-ink"
          }`}
        >
          {PERIODS[item]}
        </button>
      ))}
    </div>
  );
}

/** The headline figures for the period, beside the chart (D057). */
export function ResultsSummary({
  results,
  period,
  onPeriod,
}: {
  results: Results;
  period: Period;
  onPeriod: (value: Period) => void;
}) {
  const s = results.summary;
  const drawdown = Number(results.drawdown);
  return (
    <section aria-label="Binance demo results" className="rounded border border-line bg-panel p-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">Binance demo results</h2>
        <PeriodSwitch value={period} onChange={onPeriod} />
      </div>
      <dl className="grid grid-cols-2 gap-3">
        <Stat label="Completed trades" value={`${s.trades} (${s.wins} won, ${s.losses} lost)`} />
        <Stat label="Win rate" value={rate(s.win_rate)} />
        <Stat label="Net profit" value={money(s.net)} className={tone(Number(s.net))} />
        <Stat label="Average per trade" value={signedR(s.average_r)} className={tone(Number(s.average_r ?? 0))} />
        <Stat label="Average win" value={money(s.average_win)} />
        <Stat label="Average loss" value={money(s.average_loss)} />
        <Stat label="Profit factor" value={profitFactor(s)} />
        <Stat label="Best / worst" value={`${signedUsdt(s.best)} / ${signedUsdt(s.worst)}`} />
        <Stat label="Fees paid" value={`${Number(s.fees).toFixed(2)} USDT`} />
        <Stat label="Funding" value={money(s.funding)} className={tone(Number(s.funding))} />
        <Stat
          label="Deepest fall"
          value={`${drawdown.toFixed(2)} USDT${results.drawdown_fraction ? ` (${rate(results.drawdown_fraction)})` : ""}`}
        />
        <Stat label="Now" value={streakText(results.current_streak)} />
        <Stat label="Longest winning run" value={String(results.longest_wins)} />
        <Stat label="Longest losing run" value={String(results.longest_losses)} />
        <Stat
          label="Median time in trade"
          value={results.median_hold_hours ? `${Number(results.median_hold_hours).toFixed(1)} h` : "–"}
        />
        <Stat label="Still open" value={String(results.open_trades)} />
      </dl>
      <p className="mt-2 text-xs text-muted">
        From Binance&apos;s own fills: profit Binance booked, less fees, plus funding. A trade is won when
        that is above zero. Profit factor is what wins made divided by what losses lost. Test funds;
        past results are not a promise.
        {results.not_from_bot > 0
          ? ` ${results.not_from_bot} completed trade${results.not_from_bot === 1 ? "" : "s"} not opened by the bot left out.`
          : ""}
        {Object.keys(results.other_fees).length > 0
          ? ` Fees in other assets, not counted: ${Object.entries(results.other_fees)
              .map(([asset, amount]) => `${amount} ${asset}`)
              .join(", ")}.`
          : ""}
        {results.last_fill_at ? ` Last fill from Binance ${formatUtc(results.last_fill_at)}.` : ""}
      </p>
    </section>
  );
}

function GroupTable({
  caption,
  kind,
  groups,
}: {
  caption: string;
  kind: "coin" | "strategy" | "side" | "day";
  groups: ResultGroup[];
}) {
  return (
    <div className="overflow-x-auto rounded border border-line bg-panel">
      <table className="w-full text-left text-sm tabular-nums">
        <caption className="p-2 text-left text-sm font-semibold">{caption}</caption>
        <thead className="text-xs text-muted">
          <tr>
            <th scope="col" className="p-2">{{ coin: "Coin", strategy: "Strategy", side: "Side", day: "Day (UTC)" }[kind]}</th>
            <th scope="col" className="p-2 text-right">Trades</th>
            <th scope="col" className="p-2 text-right">Win rate</th>
            <th scope="col" className="p-2 text-right">Net USDT</th>
            <th scope="col" className="p-2 text-right">Avg R</th>
            <th scope="col" className="p-2 text-right">Profit factor</th>
            <th scope="col" className="p-2 text-right">Fees</th>
            <th scope="col" className="p-2 text-right">Funding</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <tr key={group.name} className="border-t border-line">
              <th scope="row" className="p-2 font-normal">{groupLabel(kind, group.name)}</th>
              <td className="p-2 text-right">{`${group.stats.trades} (${group.stats.wins}W ${group.stats.losses}L)`}</td>
              <td className="p-2 text-right">{rate(group.stats.win_rate)}</td>
              <td className={`p-2 text-right ${tone(Number(group.stats.net))}`}>{signedUsdt(group.stats.net)}</td>
              <td className="p-2 text-right">{signedR(group.stats.average_r)}</td>
              <td className="p-2 text-right">{profitFactor(group.stats)}</td>
              <td className="p-2 text-right">{Number(group.stats.fees).toFixed(2)}</td>
              <td className={`p-2 text-right ${tone(Number(group.stats.funding))}`}>{signedUsdt(group.stats.funding)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function cellText(stats: ResultStats | null): string {
  return stats ? `${signedUsdt(stats.net)} · ${stats.trades} (${rate(stats.win_rate)})` : "";
}

function Grid({ results }: { results: Results }) {
  const { strategies, symbols, cell } = gridMatrix(results);
  return (
    <div className="overflow-x-auto rounded border border-line bg-panel">
      <table className="w-full text-left text-xs tabular-nums">
        <caption className="p-2 text-left text-sm font-semibold">
          Strategy by coin: net USDT · trades (win rate)
        </caption>
        <thead className="text-muted">
          <tr>
            <th scope="col" className="p-2">Strategy</th>
            {symbols.map((symbol) => (
              <th key={symbol} scope="col" className="p-2 text-right">{symbol.replace("USDT", "")}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {strategies.map((strategy) => (
            <tr key={strategy} className="border-t border-line">
              <th scope="row" className="p-2 font-normal">{strategyLabel(strategy)}</th>
              {symbols.map((symbol) => {
                const stats = cell(strategy, symbol);
                return (
                  <td key={symbol} className={`p-2 text-right ${stats ? tone(Number(stats.net)) : "text-muted"}`}>
                    {cellText(stats) || "–"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type ShowOnChart = (trade: ClosedTrade) => void;

/** `onChart` opens a trade on the chart above, as the Binance app does (D065). */
function TradesTable({ trades, onChart }: { trades: ClosedTrade[]; onChart?: ShowOnChart }) {
  return (
    // Relative, so the hidden column name stays inside the scrolling box on a phone.
    <div className="relative overflow-x-auto rounded border border-line bg-panel">
      <table className="w-full text-left text-sm tabular-nums">
        <caption className="p-2 text-left text-sm font-semibold">Completed trades, newest first</caption>
        <thead className="text-xs text-muted">
          <tr>
            <th scope="col" className="p-2">Closed</th>
            <th scope="col" className="p-2">Coin</th>
            <th scope="col" className="p-2">Strategy</th>
            <th scope="col" className="p-2">Side</th>
            <th scope="col" className="p-2 text-right">Entry</th>
            <th scope="col" className="p-2 text-right">Exit</th>
            <th scope="col" className="p-2 text-right">Net USDT</th>
            <th scope="col" className="p-2 text-right">R</th>
            <th scope="col" className="p-2 text-right">Fees</th>
            <th scope="col" className="p-2 text-right">Funding</th>
            {onChart ? (
              <th scope="col" className="p-2">
                <span className="sr-only">Chart</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={`${trade.symbol}:${trade.opened_at}`} className="border-t border-line">
              <td className="p-2">{formatUtc(trade.closed_at)}</td>
              <td className="p-2">{trade.symbol}</td>
              <td className="p-2">{strategyLabel(trade.strategy)}</td>
              <td className="p-2">{sideLabel(trade.side)}</td>
              <td className="p-2 text-right">{trade.entry_price ? formatPrice(trade.entry_price, null) : "–"}</td>
              <td className="p-2 text-right">{trade.exit_price ? formatPrice(trade.exit_price, null) : "–"}</td>
              <td className={`p-2 text-right ${tone(Number(trade.net))}`}>{signedUsdt(trade.net)}</td>
              <td className="p-2 text-right">{signedR(trade.r)}</td>
              <td className="p-2 text-right">{Number(trade.fees).toFixed(3)}</td>
              <td className={`p-2 text-right ${tone(Number(trade.funding))}`}>{signedUsdt(trade.funding)}</td>
              {onChart ? (
                <td className="p-2">
                  <button
                    type="button"
                    onClick={() => onChart(trade)}
                    aria-label={`Show the ${trade.symbol} trade closed ${formatUtc(trade.closed_at)} on the chart`}
                    className="min-h-9 cursor-pointer rounded border border-line px-2 text-xs text-ink hover:border-ink"
                  >
                    Chart
                  </button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Everything else, below the chart: the equity curve and the breakdowns the owner chose. */
export function ResultsDetail({ results, onChart }: { results: Results; onChart?: ShowOnChart }) {
  if (results.summary.trades === 0) {
    return (
      <>
        <EquityChart results={results} />
        <p className="rounded border border-line bg-panel p-3 text-sm text-muted">
          No completed trades on this account in this period yet. Each trade appears here once Binance
          closes it at its stop or a target; the worker reads Binance&apos;s fills every 5 minutes.
        </p>
      </>
    );
  }
  return (
    <>
      <EquityChart results={results} />
      <GroupTable caption="By coin" kind="coin" groups={results.by_coin} />
      <GroupTable caption="By strategy" kind="strategy" groups={results.by_strategy} />
      <Grid results={results} />
      <GroupTable caption="Long and short" kind="side" groups={results.by_side} />
      <GroupTable caption="By day" kind="day" groups={results.by_day} />
      <TradesTable trades={results.trades} onChart={onChart} />
    </>
  );
}
