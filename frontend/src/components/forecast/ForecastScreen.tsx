"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { AppNav } from "@/components/AppNav";
import {
  useAnalysisJob,
  useForecastView,
  useRecentCandles,
  useStartAnalysis,
} from "@/features/forecast/queries";
import { useLiveMarket } from "@/features/market/useLiveMarket";
import { useNow } from "@/features/market/useNow";
import { ApiError, type Instrument, type Timeframe } from "@/lib/api/client";

import { ForecastChart } from "./ForecastChart";
import {
  CandleSignalsPanel,
  ContextPanel,
  HoverReadout,
  LayerToggles,
  LevelsPanel,
  PlanPanel,
  PythonSignalPanel,
  SummaryPanel,
  TrackRecordPanel,
} from "./ForecastPanels";
import { STEP_SECONDS, hoursBetween, type Span } from "./geometry";
import { LiveStatus, ReanalyseButton } from "./LiveControls";
import { ALL_LAYERS, type Layers } from "./overlay";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h", "1d"];
const SPANS: Span[] = [4, 24];
/** A latest 1H close older than this means the data feed has stopped, as when the Mac sleeps. */
const BEHIND_HOURS = 2;

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
  const instrumentId = instrument?.id ?? 0;
  const forecast = useForecastView(provider, instrumentId);
  const recent = useRecentCandles(provider, instrumentId, timeframe);
  const live = useLiveMarket(provider, instrumentId, timeframe);
  const job = useAnalysisJob();
  const start = useStartAnalysis();
  const now = useNow();
  const client = useQueryClient();

  // A closed candle moves Python's analysis and the plan's status, so reload both.
  const closedAt = live.candle?.isClosed ? live.candle.openTime : null;
  useEffect(() => {
    if (!closedAt) return;
    void client.invalidateQueries({ queryKey: ["recent-candles", provider, instrumentId, timeframe] });
    void client.invalidateQueries({ queryKey: ["forecast-view", provider, instrumentId] });
  }, [client, closedAt, provider, instrumentId, timeframe]);

  // A finished re-analysis brings a new forecast.
  const finishedAt = job.data?.finished_at ?? null;
  useEffect(() => {
    if (!finishedAt) return;
    void client.invalidateQueries({ queryKey: ["forecast-view"] });
  }, [client, finishedAt]);

  const startError = start.error instanceof ApiError ? start.error.message : start.error ? "Could not start the analysis." : null;
  const reanalyse = () => {
    start.reset();
    start.mutate({ provider, instrument_id: instrumentId });
  };
  const candles = useMemo(() => recent.data?.items ?? [], [recent.data]);
  const view = forecast.data;
  const behind = view ? (now - Date.parse(view.analysis_as_of)) / 3_600_000 : 0;

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

      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2">
        <LayerToggles layers={layers} onChange={setLayers} />
        <ReanalyseButton job={job.data} now={now} error={startError} onClick={reanalyse} />
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
      ) : !view ? (
        <p className="p-6 text-sm text-muted">Loading the forecast…</p>
      ) : (
        <div className="flex flex-col gap-3 p-3 xl:min-h-0 xl:flex-1 xl:flex-row">
          <main className="flex h-[620px] min-w-0 flex-1 flex-col rounded border border-line bg-panel xl:h-auto">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
              <HoverReadout view={view} hoverTime={hoverTime} span={span} barSeconds={STEP_SECONDS[timeframe]} />
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-xs text-muted">
                  Python {view.analysis_as_of.slice(11, 16)} UTC close · Kronos {view.as_of.slice(11, 16)} UTC close
                  {view.forecast_current ? "" : `, ${hoursBetween(view.as_of, view.analysis_as_of)}h old`}
                </span>
                {behind > BEHIND_HOURS ? (
                  <span role="alert" className="text-xs text-warn">
                    No new 1H close for {Math.floor(behind)}h: the data feed may be stopped
                  </span>
                ) : null}
                <LiveStatus connection={live.connection} price={live.price} now={now} />
              </div>
            </div>
            <div className="min-h-0 flex-1">
              <ForecastChart
                candles={candles}
                live={live.candle}
                timeframe={timeframe}
                view={view}
                layers={layers}
                span={span}
                onHover={setHoverTime}
              />
            </div>
            <p className="border-t border-line px-3 py-2 text-xs text-muted">
              {view.label}: Kronos ({view.model_paths} paths) from the {view.as_of.slice(11, 16)} UTC close, and the no-edge baseline (
              {(view.projection?.paths ?? view.baseline_paths).toLocaleString("en-US")} paths) from the latest close
              {view.baseline_rebuilt ? "" : ", baseline redrawn from changed candles"}. Prices to trade come only from Python&apos;s levels and the
              risk engine. Times in UTC. Chart by{" "}
              <a className="underline" href="https://www.tradingview.com/" rel="noreferrer" target="_blank">
                TradingView Lightweight Charts
              </a>
              .
            </p>
          </main>
          <aside className="flex w-full shrink-0 flex-col gap-3 xl:w-96 xl:overflow-y-auto">
            {/* Python's signal comes first; Claude's plan, when there is one, follows it. */}
            <PythonSignalPanel view={view} />
            {view.plan ? <PlanPanel plan={view.plan} /> : null}
            <SummaryPanel view={view} span={span} />
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
