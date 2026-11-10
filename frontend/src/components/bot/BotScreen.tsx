"use client";

import { useCallback, useMemo, useState } from "react";

import { AppNav } from "@/components/AppNav";
import { CandleChart } from "@/components/chart/CandleChart";
import { OhlcLegend } from "@/components/chart/OhlcLegend";
import { mergeCandles } from "@/components/chart/bars";
import { STEP_SECONDS } from "@/components/forecast/geometry";
import { DataWarning } from "@/components/status/Banners";
import { useCandles, useMarketStatus } from "@/features/market/queries";
import { useLiveMarket } from "@/features/market/useLiveMarket";
import { usePaperSummary, useSignals, useTrades } from "@/features/trading/queries";
import type { Instrument, Timeframe } from "@/lib/api/client";

import { BotAccount, Decisions, OpenTrade, TradeHistory, lookups } from "./BotPanels";
import { isOpen, openLines, tradeMarkers } from "./trades";

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h"];
const PROVIDER = "binance_usdm";

type BotAccountName = "portfolio" | "demo";

const ACCOUNTS: Record<BotAccountName, { label: string; title: string; note: string }> = {
  portfolio: {
    label: "Money plan, 1,000 USDT",
    title: "Money plan account",
    note:
      "Money plan, simulated. Python runs all three strategies on all six coins in a 1,000 USDT " +
      "paper account. The daily trend risks the full 1% per trade, the 1H pattern half and the " +
      "15M rule a quarter, set by a six-coin backtest. Signals at the same close share the room, " +
      "at most 3% is at risk at once, and new trades stop for the day at +3%. The risk engine " +
      "decides every trade. Backtests are not proof of future profit. No real orders are placed.",
  },
  demo: {
    label: "Demo, 100 USDT",
    title: "Demo account",
    note:
      "Demo bot, simulated. Python's 15M rule strategy trades all six coins on live Binance " +
      "prices, through the risk engine, in a 100 USDT paper account. This strategy is untested " +
      "and showed no edge in backtests. No real orders are placed.",
  },
};

export function BotScreen({ instruments }: { instruments: Instrument[] }) {
  const coins = useMemo(
    () =>
      instruments.filter(
        (item) => item.provider === PROVIDER && item.instrument_type === "linear_perpetual",
      ),
    [instruments],
  );
  const [selectedId, setSelectedId] = useState(coins[0]?.id ?? 0);
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [account, setAccount] = useState<BotAccountName>("portfolio");
  const [hoverTime, setHoverTime] = useState<number | null>(null);
  const coin = coins.find((item) => item.id === selectedId) ?? coins[0];

  const history = useCandles(PROVIDER, coin?.id ?? 0, timeframe);
  const live = useLiveMarket(PROVIDER, coin?.id ?? 0, timeframe);
  const status = useMarketStatus();
  const summary = usePaperSummary(account);
  const trades = useTrades(account);
  const signals = useSignals(account, 8);

  const candles = useMemo(
    () => mergeCandles((history.data?.pages ?? []).map((page) => page.items)),
    [history.data],
  );
  const { fetchNextPage, hasNextPage, isFetchingNextPage } = history;
  const loadOlder = useCallback(() => {
    if (hasNextPage && !isFetchingNextPage) {
      void fetchNextPage();
    }
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  const allTrades = useMemo(() => trades.data ?? [], [trades.data]);
  const coinTrades = useMemo(
    () => allTrades.filter((trade) => trade.instrument_id === coin?.id),
    [allTrades, coin?.id],
  );
  const markers = useMemo(
    () => tradeMarkers(coinTrades, STEP_SECONDS[timeframe]),
    [coinTrades, timeframe],
  );
  const levels = useMemo(() => openLines(coinTrades), [coinTrades]);
  const openHere = coinTrades.filter(isOpen);
  const { ticks, symbols } = useMemo(() => lookups(coins), [coins]);

  const price = live.price;
  const mid = price ? (Number(price.bid) + Number(price.ask)) / 2 : null;
  const feed = status.data?.feeds.find((item) => item.provider === PROVIDER);
  const problem =
    live.connection !== "open"
      ? "the live connection is down, reconnecting"
      : feed && feed.state !== "HEALTHY"
        ? `the ${PROVIDER} feed is ${feed.state}`
        : trades.isError || summary.isError
          ? "the bot account cannot be read"
          : null;

  const hovered = hoverTime
    ? candles.find((candle) => Date.parse(candle.open_time) / 1000 === hoverTime)
    : undefined;
  const showForming = !hovered && Boolean(live.candle) && !live.candle?.isClosed;
  const legendValues = hovered ?? (showForming ? live.candle : candles.at(-1)) ?? null;
  const balance = summary.data?.starting_balance ?? (account === "demo" ? "100" : "1000");
  const shown = ACCOUNTS[account];

  if (!coin) {
    return <p className="p-6 text-sm text-muted">No perpetual coins are listed.</p>;
  }
  return (
    <div className="flex min-h-screen flex-col">
      <DataWarning problem={problem} />
      <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2">
        <AppNav current="/bot" />
        <div role="group" aria-label="Account" className="ml-auto flex gap-1">
          {(Object.keys(ACCOUNTS) as BotAccountName[]).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={value === account}
              onClick={() => setAccount(value)}
              className={`min-h-9 cursor-pointer rounded border px-2 text-xs transition-colors duration-150 ${
                value === account
                  ? "border-ink bg-raised font-semibold text-ink"
                  : "border-line text-muted hover:text-ink"
              }`}
            >
              {ACCOUNTS[value].label}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-xs text-muted">
          Coin
          <select
            value={coin.id}
            onChange={(event) => setSelectedId(Number(event.target.value))}
            className="min-h-9 rounded border border-line bg-panel px-2 text-sm text-ink"
          >
            {coins.map((item) => (
              <option key={item.id} value={item.id}>
                {item.symbol} Perpetual
              </option>
            ))}
          </select>
        </label>
        <div role="group" aria-label="Timeframe" className="flex gap-1">
          {TIMEFRAMES.map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={value === timeframe}
              onClick={() => setTimeframe(value)}
              className={`min-h-9 min-w-9 cursor-pointer rounded border px-2 text-xs transition-colors duration-150 ${
                value === timeframe
                  ? "border-ink bg-raised font-semibold text-ink"
                  : "border-line text-muted hover:text-ink"
              }`}
            >
              {value}
            </button>
          ))}
        </div>
      </header>

      <p role="note" className="border-b border-line bg-raised px-4 py-2 text-xs text-warn">
        {shown.note}
      </p>

      <div className="flex flex-1 flex-col gap-3 p-3 lg:flex-row">
        <main className="flex min-w-0 flex-1 flex-col gap-3">
          <section className="flex h-[60vh] min-h-80 flex-col rounded border border-line bg-panel">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
              <OhlcLegend values={legendValues} tickSize={coin.tick_size} forming={showForming} />
              <span className="text-xs text-muted">
                Arrows: entries. Dots: exits. Lines: the open trade. Times in UTC
              </span>
            </div>
            <div className="min-h-0 flex-1">
              {history.isError ? (
                <p role="alert" className="p-4 text-sm text-bad">
                  Candles could not be loaded. They will retry on reconnection.
                </p>
              ) : (
                <CandleChart
                  candles={candles}
                  live={live.candle}
                  onNeedOlder={loadOlder}
                  onHover={setHoverTime}
                  markers={markers}
                  levels={levels}
                />
              )}
            </div>
          </section>
          <TradeHistory trades={allTrades} balance={balance} ticks={ticks} />
        </main>

        <aside className="flex w-full shrink-0 flex-col gap-3 lg:w-80">
          {summary.data ? <BotAccount summary={summary.data} title={shown.title} /> : null}
          {openHere.map((trade) => (
            <OpenTrade key={trade.id} trade={trade} mid={mid} tickSize={coin.tick_size} balance={balance} />
          ))}
          {openHere.length === 0 ? (
            <p className="rounded border border-line bg-panel p-3 text-sm text-muted">
              No open {coin.symbol} trade. Python checks again at the next 15M close.
            </p>
          ) : null}
          <Decisions signals={signals.data ?? []} symbols={symbols} />
          <p className="px-1 text-xs text-muted">
            Chart by{" "}
            <a className="underline" href="https://www.tradingview.com/" rel="noreferrer" target="_blank">
              TradingView Lightweight Charts
            </a>
            . Simulated results are not proof of future performance.
          </p>
        </aside>
      </div>
    </div>
  );
}
