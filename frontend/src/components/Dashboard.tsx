"use client";

import { useCallback, useMemo, useState } from "react";

import { CandleChart } from "@/components/chart/CandleChart";
import { OhlcLegend } from "@/components/chart/OhlcLegend";
import { mergeCandles } from "@/components/chart/bars";
import { DataWarning, SyntheticBanner } from "@/components/status/Banners";
import { DataQualityPanel } from "@/components/status/DataQualityPanel";
import { PricePanel } from "@/components/status/PricePanel";
import { useCandles, useMarketStatus } from "@/features/market/queries";
import { useLiveMarket } from "@/features/market/useLiveMarket";
import { useNow } from "@/features/market/useNow";
import type { Instrument, Timeframe } from "@/lib/api/client";

const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

function label(instrument: Instrument): string {
  const kind = instrument.instrument_type === "spot" ? "Spot" : "Perpetual";
  const suffix = instrument.is_synthetic ? " (synthetic)" : "";
  return `${instrument.symbol} ${kind}${suffix}`;
}

function keyOf(instrument: Instrument): string {
  return `${instrument.provider}:${instrument.id}`;
}

export function Dashboard({ instruments }: { instruments: Instrument[] }) {
  const defaultInstrument =
    instruments.find((item) => item.instrument_type === "linear_perpetual") ?? instruments[0]!;
  const [selectedKey, setSelectedKey] = useState(keyOf(defaultInstrument));
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [hoverTime, setHoverTime] = useState<number | null>(null);

  const instrument = instruments.find((item) => keyOf(item) === selectedKey) ?? defaultInstrument;
  const { provider, id: instrumentId, tick_size: tickSize } = instrument;

  const history = useCandles(provider, instrumentId, timeframe);
  const live = useLiveMarket(provider, instrumentId, timeframe);
  const status = useMarketStatus();
  const now = useNow();

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

  const feed = status.data?.feeds.find((item) => item.provider === provider);
  const feedHealthy = feed?.state === "HEALTHY";

  const problem = useMemo(() => {
    if (live.connection !== "open") {
      return "the live connection is down, reconnecting";
    }
    if (status.isError) {
      return "status cannot be read";
    }
    if (feed && !feedHealthy) {
      return `${instrument.symbol} feed is ${feed.state}`;
    }
    return null;
  }, [live.connection, status.isError, feed, feedHealthy, instrument.symbol]);

  const hovered = hoverTime
    ? candles.find((candle) => Date.parse(candle.open_time) / 1000 === hoverTime)
    : undefined;
  const lastClosed = candles[candles.length - 1];
  const showForming = !hovered && Boolean(live.candle) && !live.candle?.isClosed;
  const legendValues = hovered ?? (showForming ? live.candle : lastClosed) ?? null;

  return (
    <div className="flex h-screen flex-col">
      <SyntheticBanner visible={instrument.is_synthetic} />
      <DataWarning problem={problem} />

      <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2">
        <h1 className="text-sm font-semibold">AI Trading Intelligence</h1>
        <span className="rounded border border-line px-2 py-0.5 text-xs text-muted">Paper only</span>

        <label className="ml-auto flex items-center gap-2 text-xs text-muted">
          Instrument
          <select
            value={selectedKey}
            onChange={(event) => setSelectedKey(event.target.value)}
            className="min-h-9 rounded border border-line bg-panel px-2 text-sm text-ink"
          >
            {instruments.map((item) => (
              <option key={keyOf(item)} value={keyOf(item)}>
                {label(item)}
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

      <div className="flex min-h-0 flex-1 flex-col gap-3 p-3 lg:flex-row">
        <main className="flex min-h-80 min-w-0 flex-1 flex-col rounded border border-line bg-panel">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
            <OhlcLegend values={legendValues} tickSize={tickSize} forming={showForming} />
            <span className="text-xs text-muted">Times in UTC</span>
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
              />
            )}
          </div>
        </main>

        <aside className="flex w-full shrink-0 flex-col gap-3 overflow-y-auto lg:w-72">
          <PricePanel
            price={live.price}
            tickSize={tickSize}
            now={now}
            isCurrentFeed={live.connection === "open" && feedHealthy}
          />
          <DataQualityPanel feeds={status.data?.feeds} />
          <p className="px-1 text-xs text-muted">
            Chart by{" "}
            <a className="underline" href="https://www.tradingview.com/" rel="noreferrer" target="_blank">
              TradingView Lightweight Charts
            </a>
            . Analysis only. Not financial advice.
          </p>
        </aside>
      </div>
    </div>
  );
}
