/** Pure helpers for the forecast chart: time slots, coordinates, label spacing and styles. */

import type { Timeframe } from "@/lib/api/client";

export type Span = 4 | 24;

export const STEP_SECONDS: Record<Timeframe, number> = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "30m": 1800,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
};

/** Bars of history shown before the forecast, by timeframe and span. */
const HISTORY_BARS: Record<Timeframe, Record<Span, number>> = {
  "1m": { 4: 240, 24: 600 },
  "5m": { 4: 96, 24: 288 },
  "15m": { 4: 48, 24: 144 },
  "30m": { 4: 36, 24: 96 },
  "1h": { 4: 36, 24: 96 },
  "4h": { 4: 42, 24: 90 },
  "1d": { 4: 45, 24: 120 },
};

/** Share of the visible bars kept empty on the right, where labels go. */
const LABEL_ROOM = 0.22;

export function toSeconds(iso: string): number {
  return Date.parse(iso) / 1000;
}

export function floorTo(time: number, step: number): number {
  return Math.floor(time / step) * step;
}

/** Empty bar slots after the last candle, so the forecast has room on the time axis. */
export function futureSlots(lastOpen: number, step: number, until: number): number[] {
  const slots: number[] = [];
  for (let time = lastOpen + step; time <= until; time += step) {
    slots.push(time);
  }
  return slots;
}

/**
 * The x coordinate of any moment, interpolated between the bar slots around it.
 * A 1H forecast point on a 4H chart falls between two bars, so it is placed proportionally.
 * Past the last slot, the spacing of the last two slots continues.
 */
export function interpolateX(
  time: number,
  slots: readonly number[],
  xOf: (slot: number) => number | null,
): number | null {
  if (slots.length === 0 || time < slots[0]!) {
    return null;
  }
  let low = 0;
  let high = slots.length - 1;
  if (time >= slots[high]!) {
    if (time === slots[high]! || slots.length < 2) {
      return xOf(slots[high]!);
    }
    low = high - 1;
  } else {
    while (high - low > 1) {
      const middle = (low + high) >> 1;
      if (slots[middle]! <= time) {
        low = middle;
      } else {
        high = middle;
      }
    }
  }
  const from = slots[low]!;
  const to = slots[high]!;
  const xFrom = xOf(from);
  const xTo = xOf(to);
  if (xFrom === null || xTo === null) {
    return null;
  }
  return xFrom + ((xTo - xFrom) * (time - from)) / (to - from);
}

/**
 * The x coordinate of an exact moment, such as a close. A bar is drawn centred on its open
 * time and covers one bar of time, so a moment sits half a bar before its slot position.
 * A 1H close then lands on the right edge of the bar that holds it, on any timeframe.
 */
export function momentX(
  time: number,
  barSeconds: number,
  slots: readonly number[],
  xOf: (slot: number) => number | null,
): number | null {
  return interpolateX(time - barSeconds / 2, slots, xOf);
}

/** Whole hours from one close to a later one. */
export function hoursBetween(from: string, to: string): number {
  return Math.max(0, Math.round((toSeconds(to) - toSeconds(from)) / 3600));
}

/** Move labels apart so none overlap, keeping their order and staying inside the pane. */
export function spreadLabels(ys: readonly number[], gap: number, top: number, bottom: number): number[] {
  const order = ys.map((y, index) => ({ y, index })).sort((a, b) => a.y - b.y);
  const placed = order.map((item) => item.y);
  for (let i = 0; i < placed.length; i += 1) {
    const floor = i === 0 ? top : placed[i - 1]! + gap;
    placed[i] = Math.max(placed[i]!, floor);
  }
  for (let i = placed.length - 1; i >= 0; i -= 1) {
    const ceiling = i === placed.length - 1 ? bottom : placed[i + 1]! - gap;
    placed[i] = Math.min(placed[i]!, ceiling);
  }
  const result = new Array<number>(ys.length);
  order.forEach((item, i) => {
    result[item.index] = placed[i]!;
  });
  return result;
}

export type LevelStyle = { dash: number[]; label: string; structural: boolean };

const STYLES: Record<string, LevelStyle> = {
  support: { dash: [], label: "support", structural: true },
  resistance: { dash: [], label: "resistance", structural: true },
  swing_high: { dash: [], label: "swing high", structural: true },
  swing_low: { dash: [], label: "swing low", structural: true },
  fvg_edge: { dash: [2, 3], label: "gap edge", structural: false },
  atr_projection: { dash: [2, 3], label: "ATR projection", structural: false },
  measured_move: { dash: [6, 4], label: "measured move", structural: false },
  pattern_invalidation: { dash: [6, 4], label: "pattern invalidation", structural: false },
};

/** Solid lines for levels price has reacted at, dotted or dashed for calculated ones. */
export function levelStyle(kind: string): LevelStyle {
  return STYLES[kind] ?? { dash: [2, 3], label: kind.replaceAll("_", " "), structural: false };
}

/**
 * The time range to show: some history, the forecast span, then empty room on the right
 * for labels, so no label sits on a candle, the forecast or the plan.
 */
export function visibleWindow(
  asOf: number,
  span: Span,
  timeframe: Timeframe,
): { from: number; to: number } {
  const step = STEP_SECONDS[timeframe];
  const last = floorTo(asOf, step);
  const history = HISTORY_BARS[timeframe][span];
  const end = Math.max(last + step, floorTo(asOf + span * 3600, step) + step);
  const forecastBars = (end - last) / step;
  const room = Math.ceil((history + forecastBars) * LABEL_ROOM);
  return { from: last - history * step, to: end + room * step };
}

/** A distance from the last close in ATR, signed, for labels. */
export function atrDistance(price: number, lastClose: number, atr: number): string {
  const distance = (price - lastClose) / atr;
  return `${distance >= 0 ? "+" : "−"}${Math.abs(distance).toFixed(2)} ATR`;
}
