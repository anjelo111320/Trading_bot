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
  usePaperSummary,
  useSignals,
  useTrades,
} from "@/features/trading/queries";
import { ApiError, type Instrument, type Timeframe } from "@/lib/api/client";

import { ANALYSIS_SPAN, botMarkers, chartSlots, rightRoom } from "./analysis";
import { binanceLines, binanceMarkers } from "./binance";
import { BinanceAccount, BinanceOrders, BinancePosition } from "./BinancePanels";
import { BotAnalysis } from "./BotAnalysis";
import { BotAccount, Decisions, OpenTrade, TradeHistory, lookups } from "./BotPanels";
import { inOpenTrades, isOpen, openLines, tradeMarkers } from "./trades";

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h"];
const PROVIDER = "binance_usdm";

type BotAccountName = "portfolio" | "demo" | "binance";
type SideView = "trades" | "analysis";

const SIDE_VIEWS: Record<SideView, string> = { trades: "Trades", analysis: "Analysis" };

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

const ACCOUNTS: Record<BotAccountName, { label: string; title: string; note: string }> = {
  portfolio: {
    label: "Money plan, 1,000 USDT",
    title: "Money plan account",
    note:
      "Money plan, simulated. Python runs four strategies on all six coins in a 1,000 USDT " +
      "paper account. The daily trend risks the full 1% per trade, the 1H pattern and the 4H gap " +
      "with 15M CHoCH half, and the 15M rule a quarter, set by six-coin backtests. Signals at the " +
      "same close share the room, " +
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
  binance: {
    label: "Binance demo, 100 USDT",
    title: "Binance demo account",
    note:
      "Binance demo trading, test funds. Python's money plan sends real orders to Binance's demo " +
      "exchange, trading as if the account held 100 USDT: at most 1% risk per trade, isolated " +
      "margin at the lowest leverage that fits, with the stop and targets held by Binance. The " +
      "risk engine decides every trade. Backtests are not proof of future profit. No real money " +
      "is used.",
  },
};

const ACCOUNT_LABELS: Record<BotAccountName, string> = {
  portfolio: ACCOUNTS.portfolio.label,
  demo: ACCOUNTS.demo.label,
  binance: ACCOUNTS.binance.label,
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
  const [side, setSide] = useState<SideView>("trades");
  const [layers, setLayers] = useState<Layers>(ALL_LAYERS);
  const [overlay] = useState(() => new ForecastOverlay());
  const coin = coins.find((item) => item.id === selectedId) ?? coins[0];

  const history = useCandles(PROVIDER, coin?.id ?? 0, timeframe);
  const live = useLiveMarket(PROVIDER, coin?.id ?? 0, timeframe);
  const status = useMarketStatus();
  const onBinance = account === "binance";
  // Paper data is not read for the Binance account, whose positions live on Binance.
  const paperAccount = account === "binance" ? "portfolio" : account;
  const summary = usePaperSummary(paperAccount, !onBinance);
  const trades = useTrades(paperAccount, !onBinance);
  const exchange = useExchangeStatus(onBinance);
  const exchangeOrders = useExchangeOrders(onBinance);
  const signals = useSignals(account, 8);
  const forecast = useForecastView(PROVIDER, coin?.id ?? 0);

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

  const allTrades = useMemo(() => (onBinance ? [] : (trades.data ?? [])), [onBinance, trades.data]);
  const coinTrades = useMemo(
    () => allTrades.filter((trade) => trade.instrument_id === coin?.id),
    [allTrades, coin?.id],
  );
  const view = forecast.data ?? null;
  const sent = exchangeOrders.data;
  const markers = useMemo(() => {
    const step = STEP_SECONDS[timeframe];
    const own = onBinance ? binanceMarkers(sent ?? [], coin?.symbol ?? "", step) : tradeMarkers(coinTrades, step);
    return botMarkers(own, view, layers, timeframe);
  }, [onBinance, sent, coin?.symbol, coinTrades, timeframe, view, layers]);
  const liveOpen = live.candle?.openTime ?? null;
  const slots = useMemo(() => chartSlots(candles, liveOpen), [candles, liveOpen]);
  useEffect(() => {
    overlay.setState({ view, layers, span: ANALYSIS_SPAN, slots, barSeconds: STEP_SECONDS[timeframe] });
  }, [overlay, view, layers, slots, timeframe]);
  const missing = forecast.error instanceof ApiError && forecast.error.status === 404;
  const levels = useMemo(
    () => (onBinance ? binanceLines(exchange.data, coin?.symbol ?? "") : openLines(coinTrades)),
    [onBinance, exchange.data, coin?.symbol, coinTrades],
  );
  const openHere = coinTrades.filter(isOpen);
  const { ticks, symbols } = useMemo(() => lookups(coins), [coins]);
  const ticksBySymbol = useMemo(() => new Map(coins.map((item) => [item.symbol, item.tick_size] as const)), [coins]);

  const price = live.price;
  const mid = price ? (Number(price.bid) + Number(price.ask)) / 2 : null;
  const feed = status.data?.feeds.find((item) => item.provider === PROVIDER);
  const problem =
    live.connection !== "open"
      ? "the live connection is down, reconnecting"
      : feed && feed.state !== "HEALTHY"
        ? `the ${PROVIDER} feed is ${feed.state}`
        : onBinance && (exchange.isError || exchangeOrders.isError)
          ? "the Binance demo account cannot be read"
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
        <Switch
          label="Account"
          options={ACCOUNT_LABELS}
          value={account}
          onChange={setAccount}
          className="ml-auto"
        />
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
          {onBinance ? (
            <BinanceOrders orders={exchangeOrders.data ?? []} ticks={ticksBySymbol} />
          ) : (
            <TradeHistory trades={allTrades} balance={balance} ticks={ticks} />
          )}
        </main>

        <aside className="flex w-full shrink-0 flex-col gap-3 lg:w-80 xl:w-96">
          <Switch label="Side panel" options={SIDE_VIEWS} value={side} onChange={setSide} />
          {side === "analysis" ? (
            <BotAnalysis
              view={forecast.data}
              symbol={coin.symbol}
              missing={missing}
              failed={forecast.isError && !missing}
            />
          ) : onBinance ? (
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
              {exchange.data && !exchange.data.positions.some((item) => item.symbol === coin.symbol) ? (
                <p className="rounded border border-line bg-panel p-3 text-sm text-muted">
                  No open {coin.symbol} position on Binance.
                  {exchange.data.positions.length
                    ? ` Open on: ${exchange.data.positions.map((item) => item.symbol).join(", ")}.`
                    : ""}{" "}
                  Python checks again at the next 15M close.
                </p>
              ) : null}
              <Decisions signals={signals.data ?? []} symbols={symbols} />
            </>
          ) : (
            <>
              {summary.data ? (
                <BotAccount summary={summary.data} title={shown.title} inTrades={inOpenTrades(allTrades)} />
              ) : null}
              {openHere.map((trade) => (
                <OpenTrade key={trade.id} trade={trade} mid={mid} tickSize={coin.tick_size} balance={balance} />
              ))}
              {openHere.length === 0 ? (
                <p className="rounded border border-line bg-panel p-3 text-sm text-muted">
                  No open {coin.symbol} trade. Python checks again at the next 15M close.
                </p>
              ) : null}
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
