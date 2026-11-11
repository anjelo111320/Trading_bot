"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { AppNav } from "@/components/AppNav";
import { CandleChart } from "@/components/chart/CandleChart";
import { OhlcLegend } from "@/components/chart/OhlcLegend";
import { mergeCandles } from "@/components/chart/bars";
import { LayerToggles } from "@/components/forecast/ForecastPanels";
import { STEP_SECONDS } from "@/components/forecast/geometry";
import { ALL_LAYERS, ForecastOverlay, type Layers } from "@/components/forecast/overlay";
import { DataWarning } from "@/components/status/Banners";
import { useForecastView } from "@/features/forecast/queries";
import { useCandles, useMarketStatus } from "@/features/market/queries";
import { useLiveMarket } from "@/features/market/useLiveMarket";
import {
  useExchangeOrders,
  useExchangeStatus,
  useExitReviews,
  useNewsSignal,
  useSignals,
} from "@/features/trading/queries";
import { ApiError, type Instrument, type Timeframe } from "@/lib/api/client";

import { ANALYSIS_SPAN, botMarkers, chartSlots, rightRoom } from "./analysis";
import { binanceLines, binanceMarkers, waitingEntry } from "./binance";
import { BinanceAccount, BinanceOrders, BinancePosition } from "./BinancePanels";
import { BotAnalysis } from "./BotAnalysis";
import { ClaudeAdvice } from "./ClaudeAdvice";
import { Decisions, NewsSignalCard, lookups } from "./BotPanels";

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h"];
const PROVIDER = "binance_usdm";

type SideView = "trades" | "analysis" | "claude";

const SIDE_VIEWS: Record<SideView, string> = { trades: "Trades", analysis: "Analysis", claude: "Claude" };

function Switch<T extends string>({
  label,
  options,
  value,
  onChange,
  className = "",
}: {
  label: string;
  options: Record<T, string>;
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label} className={`flex gap-1 ${className}`}>
      {(Object.keys(options) as T[]).map((item) => (
        <button
          key={item}
          type="button"
          aria-pressed={item === value}
          onClick={() => onChange(item)}
          className={`min-h-9 cursor-pointer rounded border px-2 text-xs transition-colors duration-150 ${
            item === value ? "border-ink bg-raised font-semibold text-ink" : "border-line text-muted hover:text-ink"
          }`}
        >
          {options[item]}
        </button>
      ))}
    </div>
  );
}

// The Bot page shows the Binance demo account only, at the owner's request on 2026-11-11.
// The paper accounts still run, for comparison and Claude's shadow exit advice.
const NOTE =
  "Binance demo trading, test funds. Python's money plan sends real orders to Binance's demo " +
  "exchange, trading as if the account held 100 USDT, with the owner's limits: at most 2% " +
  "risk per trade and 3% across open trades, positions up to 3 times the budget, isolated " +
  "margin at the lowest leverage that fits, up to 3x, with the stop and targets held by " +
  "Binance. New trades stop for good once 20 USDT is lost, until the owner decides again. " +
  "Leverage changes the margin held, not what a stop loses. The risk engine decides every " +
  "trade. Backtests are not proof of future profit. No real money is used.";

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
  const [hoverTime, setHoverTime] = useState<number | null>(null);
  const [side, setSide] = useState<SideView>("trades");
  const [layers, setLayers] = useState<Layers>(ALL_LAYERS);
  const [overlay] = useState(() => new ForecastOverlay());
  const coin = coins.find((item) => item.id === selectedId) ?? coins[0];

  const history = useCandles(PROVIDER, coin?.id ?? 0, timeframe);
  const live = useLiveMarket(PROVIDER, coin?.id ?? 0, timeframe);
  const status = useMarketStatus();
  const exchange = useExchangeStatus(true);
  const exchangeOrders = useExchangeOrders(true);
  const signals = useSignals("binance", 8);
  const exitReviews = useExitReviews(side === "claude");
  const forecast = useForecastView(PROVIDER, coin?.id ?? 0);
  const news = useNewsSignal(coin?.id ?? 0);

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

  const view = forecast.data ?? null;
  const sent = exchangeOrders.data;
  const markers = useMemo(() => {
    const step = STEP_SECONDS[timeframe];
    return botMarkers(binanceMarkers(sent ?? [], coin?.symbol ?? "", step), view, layers, timeframe);
  }, [sent, coin?.symbol, timeframe, view, layers]);
  const liveOpen = live.candle?.openTime ?? null;
  const slots = useMemo(() => chartSlots(candles, liveOpen), [candles, liveOpen]);
  useEffect(() => {
    overlay.setState({ view, layers, span: ANALYSIS_SPAN, slots, barSeconds: STEP_SECONDS[timeframe] });
  }, [overlay, view, layers, slots, timeframe]);
  const missing = forecast.error instanceof ApiError && forecast.error.status === 404;
  const levels = useMemo(() => binanceLines(exchange.data, coin?.symbol ?? ""), [exchange.data, coin?.symbol]);
  const { symbols } = useMemo(() => lookups(coins), [coins]);
  const waiting = waitingEntry(exchange.data, coin?.symbol ?? "");
  const ticksBySymbol = useMemo(() => new Map(coins.map((item) => [item.symbol, item.tick_size] as const)), [coins]);

  const feed = status.data?.feeds.find((item) => item.provider === PROVIDER);
  const problem =
    live.connection !== "open"
      ? "the live connection is down, reconnecting"
      : feed && feed.state !== "HEALTHY"
        ? `the ${PROVIDER} feed is ${feed.state}`
        : exchange.isError || exchangeOrders.isError
          ? "the Binance demo account cannot be read"
          : null;

  const hovered = hoverTime
    ? candles.find((candle) => Date.parse(candle.open_time) / 1000 === hoverTime)
    : undefined;
  const showForming = !hovered && Boolean(live.candle) && !live.candle?.isClosed;
  const legendValues = hovered ?? (showForming ? live.candle : candles.at(-1)) ?? null;

  if (!coin) {
    return <p className="p-6 text-sm text-muted">No perpetual coins are listed.</p>;
  }
  return (
    <div className="flex min-h-screen flex-col">
      <DataWarning problem={problem} />
      <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2">
        <AppNav current="/bot" />
        <span className="ml-auto text-sm font-semibold">Binance demo, 100 USDT</span>
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
        {NOTE}
      </p>

      <div className="flex flex-1 flex-col gap-3 p-3 lg:flex-row">
        <main className="flex min-w-0 flex-1 flex-col gap-3">
          <section className="flex h-[60vh] min-h-80 flex-col rounded border border-line bg-panel">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
              <OhlcLegend values={legendValues} tickSize={coin.tick_size} forming={showForming} />
              <span className="text-xs text-muted">
                Arrows: entries. Dots: exits. Coloured lines: the open trade. Times in UTC
              </span>
            </div>
            {view ? (
              <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
                <span className="text-xs text-muted">
                  Python&apos;s {view.analysis_as_of.slice(11, 16)} UTC 1H analysis:
                </span>
                <LayerToggles layers={layers} onChange={setLayers} squareSignals />
              </div>
            ) : null}
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
                  primitive={overlay}
                  rightOffset={rightRoom(layers, timeframe, view)}
                />
              )}
            </div>
          </section>
          <BinanceOrders orders={exchangeOrders.data ?? []} ticks={ticksBySymbol} />
        </main>

        <aside className="flex w-full shrink-0 flex-col gap-3 lg:w-80 xl:w-96">
          <Switch label="Side panel" options={SIDE_VIEWS} value={side} onChange={setSide} />
          {side === "claude" ? (
            <ClaudeAdvice data={exitReviews.data} symbol={coin.symbol} />
          ) : side === "analysis" ? (
            <BotAnalysis
              view={forecast.data}
              symbol={coin.symbol}
              missing={missing}
              failed={forecast.isError && !missing}
            />
          ) : (
            <>
              {exchange.data ? <BinanceAccount status={exchange.data} /> : null}
              {exchange.data?.positions
                .filter((position) => position.symbol === coin.symbol)
                .map((position) => (
                  <BinancePosition
                    key={position.symbol}
                    status={exchange.data!}
                    position={position}
                    tickSize={coin.tick_size}
                  />
                ))}
              {waiting && !exchange.data?.positions.some((item) => item.symbol === coin.symbol) ? (
                <p className="rounded border border-line bg-panel p-3 text-sm">
                  A {waiting.side} limit for {waiting.quantity} {coin.symbol} at {waiting.trigger} is waiting on
                  Binance. Its stop and targets are already placed, so it is protected from the moment it fills.
                  Binance cancels it if it has not filled when the signal expires.
                </p>
              ) : null}
              {exchange.data && !waiting && !exchange.data.positions.some((item) => item.symbol === coin.symbol) ? (
                <p className="rounded border border-line bg-panel p-3 text-sm text-muted">
                  No open {coin.symbol} position on Binance.
                  {exchange.data.positions.length
                    ? ` Open on: ${exchange.data.positions.map((item) => item.symbol).join(", ")}.`
                    : ""}{" "}
                  Python checks again at the next 15M close.
                </p>
              ) : null}
              {news.data ? <NewsSignalCard reading={news.data} symbol={coin.symbol} /> : null}
              <Decisions signals={signals.data ?? []} symbols={symbols} />
            </>
          )}
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
