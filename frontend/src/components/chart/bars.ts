import type { CandlestickData, UTCTimestamp } from "lightweight-charts";

import type { Candle } from "@/lib/api/client";

export const UP = "#26a69a";
export const DOWN = "#ef5350";

type Source = Pick<Candle, "open" | "high" | "low" | "close"> & { time: string };

function toTime(iso: string): UTCTimestamp {
  return (Date.parse(iso) / 1000) as UTCTimestamp;
}

/** Numbers here are for drawing only. Displayed values come from the original strings. */
function bar(source: Source): CandlestickData<UTCTimestamp> {
  return {
    time: toTime(source.time),
    open: Number(source.open),
    high: Number(source.high),
    low: Number(source.low),
    close: Number(source.close),
  };
}

export function closedBar(candle: Candle): CandlestickData<UTCTimestamp> {
  return bar({ ...candle, time: candle.open_time });
}

/** A forming candle is hollow, so it never reads as a finished one. */
export function formingBar(source: Source): CandlestickData<UTCTimestamp> {
  const drawn = bar(source);
  const direction = drawn.close >= drawn.open ? UP : DOWN;
  return { ...drawn, color: "rgba(0, 0, 0, 0)", borderColor: direction, wickColor: direction };
}

/** Oldest first, with one bar per open time. Pages can overlap after a refill. */
export function mergeCandles(pages: Candle[][]): Candle[] {
  const byTime = new Map<string, Candle>();
  for (const page of pages) {
    for (const candle of page) {
      byTime.set(candle.open_time, candle);
    }
  }
  return [...byTime.values()].sort((a, b) => a.open_time.localeCompare(b.open_time));
}
