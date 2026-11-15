"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AppNav } from "@/components/AppNav";
import { CandleChart } from "@/components/chart/CandleChart";
import { OhlcLegend } from "@/components/chart/OhlcLegend";
import { mergeCandles } from "@/components/chart/bars";
import { LayerToggles } from "@/components/forecast/ForecastPanels";
import { STEP_SECONDS, toSeconds } from "@/components/forecast/geometry";
import { ALL_LAYERS, ForecastOverlay, type Layers } from "@/components/forecast/overlay";
import { DataWarning } from "@/components/status/Banners";
import { useForecastView } from "@/features/forecast/queries";
import { useCandles, useMarketStatus } from "@/features/market/queries";
import { useLiveMarket } from "@/features/market/useLiveMarket";
import {
  type ExchangeVenue,
  type SignalAccount,
  useAiBudget,
  useExchangeOrders,
  useExchangeResults,
  useExchangeStatus,
  useExitReviews,
  useNewsSignal,
  useSignal,
  useSignals,
} from "@/features/trading/queries";
import { storeVenue, useStoredVenue } from "@/features/trading/venue";
import { ApiError, type ClosedTrade, type Instrument, type Timeframe } from "@/lib/api/client";

import { ANALYSIS_SPAN, botMarkers, chartSlots, rightRoom } from "./analysis";
import { binanceLines, binanceMarkers, waitingEntry } from "./binance";
import { BinanceAccount, BinanceOrders, BinancePosition } from "./BinancePanels";
import { BotAnalysis } from "./BotAnalysis";
import { ClaudeAdvice } from "./ClaudeAdvice";
import { ClaudeBudgetPanel } from "./ClaudeBudgetPanel";
import { CloseTrade } from "./CloseTrade";
import { Decisions, NewsSignalCard, lookups } from "./BotPanels";
import { FocusBar } from "./FocusBar";
import {
  ACCOUNT_LABEL,
  CHART_TIMEFRAMES,
  type ChartFocus,
  type ChartLink,
  focusMarkers,
  focusOfSignal,
  focusOfTrade,
  focusRange,
  withFocus,
} from "./focus";
import { LimitsPanel } from "./LimitsPanel";
import { TradingSwitch } from "./TradingSwitch";
import { type Period, ResultsDetail, ResultsSummary } from "./ResultsPanels";

const PROVIDER = "binance_usdm";
// A trade older than this many pages of candles opens on the oldest one loaded.
const MAX_FOCUS_PAGES = 20;

type SideView = "trades" | "analysis" | "claude" | "results" | "limits";

const SIDE_VIEWS: Record<SideView, string> = {
  trades: "Trades",
  analysis: "Analysis",
  claude: "Claude",
  results: "Results",
  limits: "Settings",
};

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

// The Bot page shows the bot's Binance accounts: the owner's real futures wallet (D060) and
// demo trading's test funds (D054). The paper accounts still run, for comparison and Claude's
// shadow exit advice.
const VENUES: Record<ExchangeVenue, string> = { live: "Real", demo: "Demo" };
const VENUE_ACCOUNT: Record<ExchangeVenue, SignalAccount> = { live: "binance_live", demo: "binance" };
// A Signals page link to a Binance trade opens that account; a paper one keeps the choice.
const LINK_VENUE: Partial<Record<SignalAccount, ExchangeVenue>> = { binance_live: "live", binance: "demo" };

const NOTES: Record<ExchangeVenue, string> = {
  live:
    "Your real Binance futures wallet: real money. Python's money plan trades it only after you " +
    "arm it with binance_live arm, within the limits on the Settings tab, starting at 1% a trade " +
    "with a 20% loss stop. The bot reads this futures wallet only, never Spot, Funding or the " +
    "Overview, and refuses a key that can withdraw or transfer. It touches only its own orders " +
    "and trades: your own positions stay yours. Close a trade here or in the Binance app; " +
    "either way its margin is free for the next trade. Isolated margin, with the stop and " +
    "targets held by Binance. The risk engine decides every trade, and Claude places none. " +
    "Backtests are not proof of future profit.",
  demo:
    "Binance demo trading, test funds. Python's money plan sends real orders to Binance's demo " +
    "exchange, trading as if the account held 100 USDT, within the owner's limits on the " +
    "Settings tab: risk per trade, risk across open trades, the position cap, leverage, the " +
    "daily stops and the loss stop. A trade too big for the position cap is shrunk to fit. " +
    "Isolated margin at the lowest leverage that fits, with the stop and targets held by " +
    "Binance. Six strategies trade here, on ten coins; the news move and the loose copy of the " +
    "15M rule are untested and trade at the smallest share. Leverage changes the margin held, " +
    "not what a stop loses. The risk engine decides every trade. Backtests are not proof of " +
    "future profit. No real money is used.",
};

/**
 * `link` is a Signals page link (D065): the page opens on its coin, timeframe and account, and
 * the chart shows its trade.
 */
export function BotScreen({ instruments, link = null }: { instruments: Instrument[]; link?: ChartLink | null }) {
  const router = useRouter();
  const coins = useMemo(
    () =>
      instruments.filter(
        (item) => item.provider === PROVIDER && item.instrument_type === "linear_perpetual",
      ),
    [instruments],
  );
  const [selectedId, setSelectedId] = useState(
    () => coins.find((item) => item.symbol === link?.symbol)?.id ?? coins[0]?.id ?? 0,
  );
  const [timeframe, setTimeframe] = useState<Timeframe>(link?.timeframe ?? "15m");
  const [hoverTime, setHoverTime] = useState<number | null>(null);
  const [side, setSide] = useState<SideView>("trades");
  const [period, setPeriod] = useState<Period>("all");
  const [layers, setLayers] = useState<Layers>(ALL_LAYERS);
  const [overlay] = useState(() => new ForecastOverlay());
  // The real account first, as the owner asked on 2026-11-13. The choice is remembered here.
  const stored = useStoredVenue();
  const [chosen, setChosen] = useState<ExchangeVenue | null>(link ? (LINK_VENUE[link.account] ?? null) : null);
  const venue = chosen ?? stored ?? "live";
  // The trade on the chart: picked on the Results tab, or the link's, until cleared (D065).
  const [picked, setPicked] = useState<ChartFocus | null>(null);
  const [linkShown, setLinkShown] = useState(link !== null);
  const clearFocus = useCallback(() => {
    setPicked(null);
    setLinkShown(false);
  }, []);
  const chooseVenue = useCallback(
    (next: ExchangeVenue) => {
      setChosen(next);
      storeVenue(next);
      clearFocus();
    },
    [clearFocus],
  );
  const coin = coins.find((item) => item.id === selectedId) ?? coins[0];
  const chartSection = useRef<HTMLElement>(null);

  const history = useCandles(PROVIDER, coin?.id ?? 0, timeframe);
  const live = useLiveMarket(PROVIDER, coin?.id ?? 0, timeframe);
  const status = useMarketStatus();
  const exchange = useExchangeStatus(venue, true);
  const exchangeOrders = useExchangeOrders(venue, exchange.data?.connected ?? false);
  const signals = useSignals(venue === "live" ? "binance_live" : "binance", 8);
  const exitReviews = useExitReviews(side === "claude");
  const aiBudget = useAiBudget(side === "claude");
  const forecast = useForecastView(PROVIDER, coin?.id ?? 0);
  const news = useNewsSignal(coin?.id ?? 0);
  const results = useExchangeResults(venue, period, side === "results" && (exchange.data?.connected ?? false));
  const linked = useSignal(link?.account ?? null, link?.signalId ?? null);

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

  const linkedFocus = useMemo(
    () => (link && linked.data ? focusOfSignal(linked.data, link.symbol, link.account) : null),
    [link, linked.data],
  );
  const focus = picked ?? (linkShown ? linkedFocus : null);
  const shownFocus = focus && focus.symbol === coin?.symbol ? focus : null;
  const linkNote =
    !link || !linkShown || picked
      ? null
      : linked.isError
        ? "The linked trade could not be loaded."
        : !linked.data
          ? "Loading the trade…"
          : !linkedFocus
            ? "That signal has not entered a trade, so there is nothing to show on the chart."
            : null;
  const step = STEP_SECONDS[timeframe];
  const oldest = candles[0] ? toSeconds(candles[0].open_time) : null;
  const newest = candles.at(-1) ? toSeconds(candles.at(-1)!.open_time) : null;
  const range = useMemo(
    () => (shownFocus && newest !== null ? focusRange(shownFocus, step, newest) : null),
    [shownFocus, step, newest],
  );
  // Older candles load page by page until the trade's start is on the chart.
  const covered = range !== null && oldest !== null && oldest <= range.from;
  const exhausted = !hasNextPage || history.isError || (history.data?.pages.length ?? 0) >= MAX_FOCUS_PAGES;
  useEffect(() => {
    if (range && oldest !== null && !covered && !exhausted && !isFetchingNextPage) {
      void fetchNextPage();
    }
  }, [range, oldest, covered, exhausted, isFetchingNextPage, fetchNextPage]);
  const chartFocus =
    range && shownFocus && oldest !== null && (covered || exhausted)
      ? { key: `${shownFocus.key}:${timeframe}`, ...range }
      : null;
  const showTrade = useCallback(
    (trade: ClosedTrade) => {
      const target = coins.find((item) => item.symbol === trade.symbol);
      if (!target) return;
      setSelectedId(target.id);
      setPicked(focusOfTrade(trade, ACCOUNT_LABEL[VENUE_ACCOUNT[venue]]));
      setLinkShown(false);
      chartSection.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    },
    [coins, venue],
  );
  const backToSignals = useCallback(() => {
    if (window.history.length > 1) {
      router.back();
    } else {
      router.push("/signals");
    }
  }, [router]);

  const view = forecast.data ?? null;
  const sent = exchangeOrders.data;
  const markers = useMemo(() => {
    const base = botMarkers(binanceMarkers(sent ?? [], coin?.symbol ?? "", step), view, layers, timeframe);
    return shownFocus ? withFocus(base, focusMarkers(shownFocus, step, coin?.tick_size ?? null)) : base;
  }, [sent, coin?.symbol, coin?.tick_size, step, timeframe, view, layers, shownFocus]);
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
          ? `the Binance ${venue === "live" ? "real" : "demo"} account cannot be read`
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
        <Switch label="Binance account" options={VENUES} value={venue} onChange={chooseVenue} className="ml-auto" />
        <label className="flex items-center gap-2 text-xs text-muted">
          Coin
          <select
            value={coin.id}
            onChange={(event) => {
              setSelectedId(Number(event.target.value));
              clearFocus();
            }}
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
          {CHART_TIMEFRAMES.map((value) => (
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
        {NOTES[venue]}
      </p>

      <div className="flex flex-1 flex-col gap-3 p-3 lg:flex-row">
        <main className="flex min-w-0 flex-1 flex-col gap-3">
          <section
            ref={chartSection}
            aria-label={`${coin.symbol} chart`}
            className="flex h-[60vh] min-h-80 scroll-mt-3 flex-col rounded border border-line bg-panel"
          >
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
              <OhlcLegend values={legendValues} tickSize={coin.tick_size} forming={showForming} />
              <span className="text-xs text-muted">
                Arrows: entries. Dots: exits. Coloured lines: the open trade. Times in UTC
              </span>
            </div>
            {shownFocus ? (
              <FocusBar
                focus={shownFocus}
                tickSize={coin.tick_size}
                onBack={link && !picked ? backToSignals : undefined}
                onClear={clearFocus}
              />
            ) : linkNote ? (
              <p
                role={linked.isError ? "alert" : "status"}
                className={`border-b border-line px-3 py-2 text-xs ${linked.isError ? "text-bad" : "text-muted"}`}
              >
                {linkNote}
              </p>
            ) : null}
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
                  focus={chartFocus}
                />
              )}
            </div>
          </section>
          {side === "results" ? (
            results.data ? (
              <ResultsDetail results={results.data} onChart={showTrade} />
            ) : (
              <p className="rounded border border-line bg-panel p-3 text-sm text-muted">
                {exchange.data && !exchange.data.connected
                  ? "Results appear once the account is connected and has finished trades."
                  : results.isError
                    ? "The results could not be loaded."
                    : "Loading results…"}
              </p>
            )
          ) : (
            <BinanceOrders orders={exchangeOrders.data ?? []} ticks={ticksBySymbol} venue={venue} />
          )}
        </main>

        <aside className="flex w-full shrink-0 flex-col gap-3 lg:w-80 xl:w-96">
          <Switch label="Side panel" options={SIDE_VIEWS} value={side} onChange={setSide} />
          {side === "limits" ? (
            <>
              <LimitsPanel key={venue} venue={venue} />
              <ClaudeBudgetPanel />
            </>
          ) : side === "results" ? (
            results.data ? (
              <ResultsSummary results={results.data} period={period} onPeriod={setPeriod} />
            ) : null
          ) : side === "claude" ? (
            <ClaudeAdvice data={exitReviews.data} symbol={coin.symbol} budget={aiBudget.data} />
          ) : side === "analysis" ? (
            <BotAnalysis
              view={forecast.data}
              symbol={coin.symbol}
              missing={missing}
              failed={forecast.isError && !missing}
            />
          ) : (
            <>
              {exchange.data ? (
                <BinanceAccount
                  status={exchange.data}
                  venue={venue}
                  control={exchange.data.connected ? <TradingSwitch venue={venue} status={exchange.data} /> : null}
                />
              ) : null}
              {exchange.data?.positions
                .filter((position) => position.symbol === coin.symbol)
                .map((position) => (
                  <BinancePosition
                    key={position.symbol}
                    status={exchange.data!}
                    position={position}
                    tickSize={coin.tick_size}
                    action={
                      <CloseTrade
                        key={`${venue}:${position.symbol}`}
                        venue={venue}
                        symbol={position.symbol}
                        label="Close at market"
                        question={
                          `Close the bot's ${position.side.toLowerCase()} ${position.symbol} at market now? ` +
                          `Open profit ${Number(position.unrealized) > 0 ? "+" : ""}${Number(position.unrealized).toFixed(2)} USDT ` +
                          "before fees. Its stop and targets are cancelled once it is closed."
                        }
                        closing={exchange.data!.closing.includes(position.symbol)}
                      />
                    }
                  />
                ))}
              {waiting && !exchange.data?.positions.some((item) => item.symbol === coin.symbol) ? (
                <div className="space-y-2 rounded border border-line bg-panel p-3 text-sm">
                  <p>
                    A {waiting.side} limit for {waiting.quantity} {coin.symbol} at {waiting.trigger} is waiting on
                    Binance. Its stop and targets are already placed, so it is protected from the moment it fills.
                    Binance cancels it if it has not filled when the signal expires.
                  </p>
                  <CloseTrade
                    key={`${venue}:${coin.symbol}:entry`}
                    venue={venue}
                    symbol={coin.symbol}
                    label="Cancel the entry"
                    question={`Cancel the waiting ${coin.symbol} entry, with its stop and targets? Anything already filled is closed at market.`}
                    closing={exchange.data?.closing.includes(coin.symbol) ?? false}
                  />
                </div>
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
