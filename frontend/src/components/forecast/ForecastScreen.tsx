"use client";

import { useMemo, useState } from "react";

import { AppNav } from "@/components/AppNav";
import { useForecastView, useRecentCandles } from "@/features/forecast/queries";
import { ApiError, type Instrument, type Timeframe } from "@/lib/api/client";
import { formatUtc } from "@/lib/format";

import { ForecastChart } from "./ForecastChart";
import {
  CandleSignalsPanel,
  ContextPanel,
  HoverReadout,
  LayerToggles,
  LevelsPanel,
  PlanPanel,
  SummaryPanel,
  TrackRecordPanel,
} from "./ForecastPanels";
import { STEP_SECONDS, type Span } from "./geometry";
import { ALL_LAYERS, type Layers } from "./overlay";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h", "1d"];
const SPANS: Span[] = [4, 24];

function Choice<T extends string | number>({
  label,
  values,
  value,
  onChange,
  format,
}: {
  label: string;
  values: T[];
  value: T;
  onChange: (value: T) => void;
  format: (value: T) => string;
}) {
  return (
    <div role="group" aria-label={label} className="flex items-center gap-1">
      <span className="mr-1 text-xs text-muted">{label}</span>
      {values.map((item) => (
        <button
          key={item}
          type="button"
          aria-pressed={item === value}
          onClick={() => onChange(item)}
          className={`min-h-9 min-w-9 cursor-pointer rounded border px-2 text-xs transition-colors duration-150 ${
            item === value ? "border-ink bg-raised font-semibold text-ink" : "border-line text-muted hover:text-ink"
          }`}
        >
          {format(item)}
        </button>
      ))}
    </div>
  );
}

export function ForecastScreen({ instruments }: { instruments: Instrument[] }) {
  const perpetuals = instruments.filter((item) => item.instrument_type === "linear_perpetual");
  const initial = perpetuals.find((item) => item.symbol === "BTCUSDT") ?? perpetuals[0];
  const [selectedId, setSelectedId] = useState(initial?.id ?? 0);
  const [timeframe, setTimeframe] = useState<Timeframe>("1h");
  const [span, setSpan] = useState<Span>(4);
  const [layers, setLayers] = useState<Layers>(ALL_LAYERS);
  const [hoverTime, setHoverTime] = useState<number | null>(null);

  const instrument = perpetuals.find((item) => item.id === selectedId) ?? initial;
  const provider = instrument?.provider ?? "binance_usdm";
  const forecast = useForecastView(provider, instrument?.id ?? 0);
  const recent = useRecentCandles(provider, instrument?.id ?? 0, timeframe);
  const candles = useMemo(() => recent.data?.items ?? [], [recent.data]);
  const view = forecast.data;
  const horizon = view?.horizons.find((h) => h.candles === span) ?? view?.horizons[0];
  const lastCandle = candles[candles.length - 1];

  const missing = forecast.error instanceof ApiError && forecast.error.status === 404;

  return (
    <div className="flex min-h-screen flex-col xl:h-screen">
      <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-2">
        <AppNav current="/forecast" />
        <label className="ml-auto flex items-center gap-2 text-xs text-muted">
          Coin
          <select
            value={instrument?.id ?? 0}
            onChange={(event) => setSelectedId(Number(event.target.value))}
            className="min-h-9 rounded border border-line bg-panel px-2 text-sm text-ink"
          >
            {perpetuals.map((item) => (
              <option key={item.id} value={item.id}>
                {item.symbol} perpetual
              </option>
            ))}
          </select>
        </label>
        <Choice label="Candles" values={TIMEFRAMES} value={timeframe} onChange={setTimeframe} format={(v) => v} />
        <Choice label="Forecast" values={SPANS} value={span} onChange={setSpan} format={(v) => `${v}h`} />
      </header>

      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2">
        <LayerToggles layers={layers} onChange={setLayers} />
      </div>

      {missing ? (
        <p className="p-6 text-sm text-muted">
          No forecast is stored for {instrument?.symbol} yet. One is made at a setup, or by running{" "}
          <code className="rounded bg-raised px-1">forecast run {instrument?.symbol}</code>.
        </p>
      ) : forecast.isError ? (
        <p role="alert" className="p-6 text-sm text-bad">
          The forecast could not be loaded.
        </p>
      ) : !view || !horizon ? (
        <p className="p-6 text-sm text-muted">Loading the forecast…</p>
      ) : (
        <div className="flex flex-col gap-3 p-3 xl:min-h-0 xl:flex-1 xl:flex-row">
          <main className="flex h-[620px] min-w-0 flex-1 flex-col rounded border border-line bg-panel xl:h-auto">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
              <HoverReadout view={view} hoverTime={hoverTime} span={span} barSeconds={STEP_SECONDS[timeframe]} />
              <span className="text-xs text-muted">
                {view.symbol} · forecast {formatUtc(view.as_of)} · last candle{" "}
                {lastCandle ? formatUtc(lastCandle.close_time) : "none"}
              </span>
            </div>
            <div className="min-h-0 flex-1">
              <ForecastChart
                candles={candles}
                timeframe={timeframe}
                view={view}
                layers={layers}
                span={span}
                onHover={setHoverTime}
              />
            </div>
            <p className="border-t border-line px-3 py-2 text-xs text-muted">
              {view.label}: Kronos ({view.model_paths} paths) beside the no-edge baseline ({view.baseline_paths.toLocaleString("en-US")} paths)
              {view.baseline_rebuilt ? "" : ", baseline redrawn from changed candles"}. Prices to trade come only from Python&apos;s levels and the
              risk engine. Times in UTC. Chart by{" "}
              <a className="underline" href="https://www.tradingview.com/" rel="noreferrer" target="_blank">
                TradingView Lightweight Charts
              </a>
              .
            </p>
          </main>
          <aside className="flex w-full shrink-0 flex-col gap-3 xl:w-96 xl:overflow-y-auto">
            {view.plan ? <PlanPanel plan={view.plan} /> : null}
            <SummaryPanel horizon={horizon} lastClose={Number(view.last_close)} atr={view.atr} />
            <TrackRecordPanel view={view} />
            <LevelsPanel view={view} span={span} />
            <CandleSignalsPanel view={view} />
            <ContextPanel view={view} />
          </aside>
        </div>
      )}
    </div>
  );
}
