"use client";

import {
  ColorType,
  createChart,
  createSeriesMarkers,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

import { DOWN, UP } from "@/components/chart/bars";
import type { Results } from "@/lib/api/client";
import { formatUtc } from "@/lib/format";

import { equitySeries } from "./results";

const LINE = "#93c5fd";
const MUTED = "#94a3b8";

/** The account's equity after each closed trade, from its start for the period (D057). */
export function EquityChart({ results }: { results: Results }) {
  const element = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const [hovered, setHovered] = useState<{ time: number; value: number } | null>(null);

  useEffect(() => {
    if (!element.current) return;
    const chart = createChart(element.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0e1223" }, textColor: MUTED },
      grid: { vertLines: { visible: false }, horzLines: { color: "#1a1e2f" } },
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155", timeVisible: true, secondsVisible: false },
    });
    const series = chart.addSeries(LineSeries, { color: LINE, lineWidth: 2, priceLineVisible: false });
    chart.subscribeCrosshairMove((parameter) => {
      const point = parameter.seriesData.get(series) as { value?: number } | undefined;
      setHovered(
        parameter.time !== undefined && point?.value !== undefined
          ? { time: Number(parameter.time), value: point.value }
          : null,
      );
    });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const points = equitySeries(results);
    series.setData(points.map((point) => ({ time: point.time as UTCTimestamp, value: point.value })));
    const start = Number(results.start_equity);
    const line = series.createPriceLine({
      price: start,
      color: MUTED,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: "Start",
    });
    const markers: SeriesMarker<Time>[] = results.trades
      .map((trade) => ({
        time: Math.floor(Date.parse(trade.closed_at) / 1000) as UTCTimestamp,
        position: "inBar" as const,
        shape: "circle" as const,
        color: trade.won ? UP : DOWN,
        size: 1,
      }))
      .sort((a, b) => Number(a.time) - Number(b.time));
    const plugin = createSeriesMarkers(series, markers);
    chartRef.current?.timeScale().fitContent();
    return () => {
      series.removePriceLine(line);
      plugin.detach();
    };
  }, [results]);

  const last = equitySeries(results).at(-1);
  const shown = hovered ?? last ?? null;
  return (
    <section aria-label="Equity curve" className="flex flex-col rounded border border-line bg-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-3 py-2">
        <h2 className="text-sm font-semibold">Equity after each closed trade, USDT</h2>
        <span className="text-xs text-muted tabular-nums">
          {shown
            ? `${shown.value.toFixed(2)} USDT at ${formatUtc(new Date(shown.time * 1000).toISOString())}`
            : ""}
        </span>
      </div>
      <div ref={element} className="h-56 min-h-40" />
      <p className="px-3 py-2 text-xs text-muted">
        Starts at {Number(results.start_equity).toFixed(2)} USDT, the dashed line. Dots mark closed
        trades: green won, red lost. Open trades are not included. Test funds.
      </p>
    </section>
  );
}
