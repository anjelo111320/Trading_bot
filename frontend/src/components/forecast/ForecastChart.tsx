"use client";

import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";

import { DOWN, UP, closedBar, formingBar } from "@/components/chart/bars";
import type { LiveCandle } from "@/features/market/useLiveMarket";
import type { Candle, CandleSignal, ForecastView, Timeframe } from "@/lib/api/client";

import { STEP_SECONDS, floorTo, futureSlots, toSeconds, visibleWindow, type Span } from "./geometry";
import { ForecastOverlay, type Layers } from "./overlay";

type Props = {
  candles: Candle[];
  live: LiveCandle | null;
  timeframe: Timeframe;
  view: ForecastView;
  layers: Layers;
  span: Span;
  onHover: (time: number | null) => void;
};

/** The live candle: hollow while it forms, filled once it closes. */
export function liveBar(live: LiveCandle): CandlestickData<UTCTimestamp> {
  const bar = formingBar({ ...live, time: live.openTime });
  return live.isClosed
    ? { ...bar, color: undefined, borderColor: undefined, wickColor: undefined }
    : bar;
}

/**
 * Candle signals as arrows: bearish above the bar, bullish below it. Names stay off the
 * chart, where they would cover candles, and appear in the panel and under the cursor.
 */
export function signalMarkers(signals: CandleSignal[], step: number): SeriesMarker<Time>[] {
  const seen = new Set<string>();
  return signals
    .filter((signal) => {
      // One arrow per direction per bar: several 1H signals can fall in one 4H or 1D bar.
      const key = `${floorTo(toSeconds(signal.open_time), step)}:${signal.direction}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .map((signal) => {
      const bearish = signal.direction === "bearish";
      return {
        time: floorTo(toSeconds(signal.open_time), step) as UTCTimestamp,
        position: bearish ? "aboveBar" : "belowBar",
        shape: bearish ? "arrowDown" : "arrowUp",
        color: bearish ? DOWN : UP,
        id: `${signal.type}:${signal.open_time}`,
      } satisfies SeriesMarker<Time>;
    })
    .sort((a, b) => Number(a.time) - Number(b.time));
}

export function ForecastChart({ candles, live, timeframe, view, layers, span, onHover }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  // Empty future slots live on their own series, so the candle series can update in place.
  const slotsRef = useRef<ISeriesApi<"Line"> | null>(null);
  const newest = useRef(0);
  const overlayRef = useRef<ForecastOverlay | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const hover = useRef(onHover);

  useEffect(() => {
    hover.current = onHover;
  }, [onHover]);

  useEffect(() => {
    const element = container.current;
    if (!element) {
      return;
    }
    const chart = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#0e1223" },
        textColor: "#94a3b8",
        fontSize: 12,
      },
      grid: { vertLines: { color: "#1a1e2f" }, horzLines: { color: "#1a1e2f" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#334155", scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: "#334155", timeVisible: true, secondsVisible: false },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceLineVisible: false,
    });
    const slotSeries = chart.addSeries(LineSeries, {
      lastValueVisible: false,
      priceLineVisible: false,
      crosshairMarkerVisible: false,
      autoscaleInfoProvider: () => null,
    });
    const overlay = new ForecastOverlay();
    series.attachPrimitive(overlay);
    chart.subscribeCrosshairMove((parameter) => {
      hover.current(parameter.time ? Number(parameter.time) : null);
    });
    chartRef.current = chart;
    seriesRef.current = series;
    slotsRef.current = slotSeries;
    overlayRef.current = overlay;
    markersRef.current = createSeriesMarkers(series, []);
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      slotsRef.current = null;
      overlayRef.current = null;
      markersRef.current = null;
    };
  }, []);

  const step = STEP_SECONDS[timeframe];
  // The chart is anchored at the latest close, where the projection starts. Kronos may be older.
  const now = toSeconds(view.analysis_as_of);
  const horizon = Math.max(view.projection?.steps.length ?? 0, view.kronos?.steps.length ?? 0);
  const bars = useMemo(() => candles.map(closedBar), [candles]);
  const slots = useMemo(() => {
    const lastOpen = bars.length > 0 ? Number(bars[bars.length - 1]!.time) : floorTo(now, step);
    // Room for the whole projection and the label column, for either span.
    const until = Math.max(
      floorTo(now + horizon * 3600, step) + 3 * step,
      visibleWindow(now, 4, timeframe).to,
      visibleWindow(now, 24, timeframe).to,
    );
    const future = futureSlots(lastOpen, step, until);
    return { future, all: [...bars.map((bar) => Number(bar.time)), ...future] };
  }, [bars, now, step, timeframe, horizon]);

  useEffect(() => {
    seriesRef.current?.setData(bars);
    slotsRef.current?.setData(slots.future.map((time) => ({ time: time as UTCTimestamp })));
    newest.current = bars.length > 0 ? Number(bars[bars.length - 1]!.time) : 0;
    overlayRef.current?.setState({ view, layers, span, slots: slots.all, barSeconds: step });
  }, [bars, slots, view, layers, span, step]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !live) {
      return;
    }
    const bar = liveBar(live);
    if (Number(bar.time) < newest.current) {
      return; // The chart only updates its newest bar. History refills older ones.
    }
    newest.current = Number(bar.time);
    series.update(bar);
  }, [live, bars]);

  useEffect(() => {
    markersRef.current?.setMarkers(layers.signals ? signalMarkers(view.candle_signals, step) : []);
  }, [view.candle_signals, layers.signals, step]);

  // Reframed when Python moves to a new close, so the latest candles and their future stay in view.
  const hasBars = bars.length > 0;
  useEffect(() => {
    if (!hasBars) {
      return;
    }
    const range = visibleWindow(now, span, timeframe);
    chartRef.current
      ?.timeScale()
      .setVisibleRange({ from: range.from as UTCTimestamp, to: range.to as UTCTimestamp });
  }, [now, span, timeframe, hasBars]);

  return (
    <div
      ref={container}
      className="h-full w-full"
      role="img"
      aria-label="Candles with the baseline projected from the latest close, Python's levels, patterns and the plan. The same values are listed in the panels beside the chart."
    />
  );
}
