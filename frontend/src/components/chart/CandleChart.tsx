"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  LineStyle,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type ISeriesPrimitive,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { Candle } from "@/lib/api/client";
import type { LiveCandle } from "@/features/market/useLiveMarket";

import { DOWN, UP, closedBar, formingBar } from "./bars";

/** A horizontal level, such as an open trade's entry, stop or target. */
export type PriceLevel = { price: number; color: string; title: string; dashed: boolean };

type Props = {
  candles: Candle[];
  live: LiveCandle | null;
  onNeedOlder: () => void;
  onHover: (time: number | null) => void;
  markers?: SeriesMarker<Time>[];
  levels?: PriceLevel[];
  /** Extra drawings on the candles, such as Python's analysis on the Bot page. */
  primitive?: ISeriesPrimitive<Time> | null;
  /** Empty bars kept on the right, for drawings that reach past the last candle. */
  rightOffset?: number;
  /**
   * A span to scroll to once, in UTC seconds, such as a trade opened from a table (D065). A new
   * key scrolls again; after that the owner scrolls freely.
   */
  focus?: { key: string; from: number; to: number } | null;
};

const NO_MARKERS: SeriesMarker<Time>[] = [];
const NO_LEVELS: PriceLevel[] = [];

const OLDER_THRESHOLD_BARS = 30;

export function CandleChart({
  candles,
  live,
  onNeedOlder,
  onHover,
  markers = NO_MARKERS,
  levels = NO_LEVELS,
  primitive = null,
  rightOffset = 0,
  focus = null,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const focused = useRef<string | null>(null);
  const times = useRef<number[]>([]);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const linesRef = useRef<IPriceLine[]>([]);
  const newestDrawn = useRef(0);
  const handlers = useRef({ onNeedOlder, onHover });

  useEffect(() => {
    handlers.current = { onNeedOlder, onHover };
  }, [onNeedOlder, onHover]);

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
      grid: {
        vertLines: { color: "#1a1e2f" },
        horzLines: { color: "#1a1e2f" },
      },
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155", timeVisible: true, secondsVisible: false },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
    });
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range && range.from < OLDER_THRESHOLD_BARS) {
        handlers.current.onNeedOlder();
      }
    });
    chart.subscribeCrosshairMove((parameter) => {
      handlers.current.onHover(parameter.time ? Number(parameter.time) : null);
    });
    chartRef.current = chart;
    seriesRef.current = series;
    markersRef.current = createSeriesMarkers(series, []);
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      markersRef.current = null;
      linesRef.current = [];
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !primitive) {
      return;
    }
    series.attachPrimitive(primitive);
    return () => seriesRef.current?.detachPrimitive(primitive);
  }, [primitive]);

  // Setting the room on the right scrolls to the newest bar, so it waits while a trade is in
  // view. Once the trade is cleared, the chart returns to the newest bars at the usual zoom.
  const focusKey = focus?.key ?? null;
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || focusKey !== null) {
      return;
    }
    chart.applyOptions({ timeScale: { rightOffset } });
    if (focused.current !== null) {
      focused.current = null;
      chart.timeScale().resetTimeScale();
    }
  }, [rightOffset, focusKey]);

  useEffect(() => {
    markersRef.current?.setMarkers(markers);
  }, [markers, candles]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) {
      return;
    }
    linesRef.current.forEach((line) => series.removePriceLine(line));
    linesRef.current = levels.map((level) =>
      series.createPriceLine({
        price: level.price,
        color: level.color,
        title: level.title,
        lineWidth: 1,
        lineStyle: level.dashed ? LineStyle.Dashed : LineStyle.Solid,
        axisLabelVisible: true,
      }),
    );
  }, [levels]);

  useEffect(() => {
    const bars = candles.map(closedBar);
    seriesRef.current?.setData(bars);
    newestDrawn.current = bars[bars.length - 1]?.time ?? 0;
    times.current = bars.map((bar) => bar.time);
  }, [candles]);

  // After the data, so the span is measured on the bars just drawn. A span that reaches the
  // newest bar keeps the room on the right, so the labels there never cover the trade; a new
  // room moves the view back to the trade.
  useEffect(() => {
    const chart = chartRef.current;
    const drawn = times.current;
    const applied = focus ? `${focus.key}:${rightOffset}` : null;
    if (!chart || !focus || drawn.length === 0 || focused.current === applied) {
      return;
    }
    focused.current = applied;
    const last = drawn.length - 1;
    const first = drawn.findIndex((time) => time >= focus.from);
    const from = first === -1 ? last : first;
    const to = focus.to >= drawn[last]! ? last + rightOffset : drawn.findLastIndex((time) => time <= focus.to);
    chart.timeScale().setVisibleLogicalRange({ from, to: Math.max(to, from + 1) });
  }, [focus, candles, rightOffset]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !live) {
      return;
    }
    const source = { ...live, time: live.openTime };
    const bar = live.isClosed
      ? { ...formingBar(source), color: undefined, borderColor: undefined, wickColor: undefined }
      : formingBar(source);
    if (bar.time < newestDrawn.current) {
      return; // The chart library rejects updates to older bars, and history refills them.
    }
    newestDrawn.current = bar.time;
    series.update(bar);
  }, [live, candles]);

  return (
    <div
      ref={container}
      className="h-full w-full"
      role="img"
      aria-label="Candlestick chart. Exact values are shown in the text above it."
    />
  );
}
