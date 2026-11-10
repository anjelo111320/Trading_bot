/**
 * Python's 1H analysis drawn on the Bot chart: the Forecast page's overlay, placed between the
 * Bot chart's own bars. The analysis is information only. It never changes a bot trade.
 */

import type { SeriesMarker, Time } from "lightweight-charts";

import { signalMarkers } from "@/components/forecast/ForecastChart";
import { STEP_SECONDS, toSeconds, type Span } from "@/components/forecast/geometry";
import type { Layers } from "@/components/forecast/overlay";
import type { Candle, ForecastView, Timeframe } from "@/lib/api/client";

/** The Bot page shows the next 4 hours from the latest 1H close. */
export const ANALYSIS_SPAN: Span = 4;
/** Bars kept free on the right for the level labels. */
const LABEL_BARS = 20;
/** The most bars the projection may take on the right, so a 1M chart is not mostly empty. */
const MAX_PROJECTION_BARS = 24;

/** Open times of the bars on the chart, oldest first, including a newer live bar. */
export function chartSlots(candles: Candle[], liveOpen: string | null): number[] {
  const slots = candles.map((candle) => toSeconds(candle.open_time));
  if (liveOpen) {
    const live = toSeconds(liveOpen);
    if (slots.length === 0 || live > slots[slots.length - 1]!) {
      slots.push(live);
    }
  }
  return slots;
}

/** Room on the right for the labels and the projection, when either is drawn. */
export function rightRoom(layers: Layers, timeframe: Timeframe, view: ForecastView | null): number {
  if (!view || !(layers.zones || layers.baseline || layers.plan || layers.patterns)) {
    return 0;
  }
  const projection = layers.baseline && view.projection ? (ANALYSIS_SPAN * 3600) / STEP_SECONDS[timeframe] : 0;
  return LABEL_BARS + Math.min(Math.ceil(projection), MAX_PROJECTION_BARS);
}

/**
 * Trade arrows and dots, plus Python's candle signals as squares when that layer is on.
 * The squares keep the Forecast page's placement: bearish above the bar, bullish below it.
 */
export function botMarkers(
  trades: SeriesMarker<Time>[],
  view: ForecastView | null,
  layers: Layers,
  timeframe: Timeframe,
): SeriesMarker<Time>[] {
  if (!view || !layers.signals) {
    return trades;
  }
  const squares = signalMarkers(view.candle_signals, STEP_SECONDS[timeframe]).map(
    (marker) => ({ ...marker, shape: "square", size: 0.6 }) satisfies SeriesMarker<Time>,
  );
  return [...trades, ...squares].sort((a, b) => Number(a.time) - Number(b.time));
}

/** Whole hours since Python's latest 1H close, when the data feed may have stopped. */
export function hoursBehind(view: ForecastView, now: number): number {
  return Math.floor((now - Date.parse(view.analysis_as_of)) / 3_600_000);
}
