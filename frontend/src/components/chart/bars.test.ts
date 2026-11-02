import { describe, expect, it } from "vitest";

import type { Candle } from "@/lib/api/client";

import { closedBar, formingBar, mergeCandles, UP, DOWN } from "./bars";

function candle(openTime: string, close = "105"): Candle {
  return {
    open_time: openTime,
    close_time: openTime,
    open: "100",
    high: "110",
    low: "90",
    close,
    volume: "1",
    quote_volume: "1",
    trade_count: 1,
    data_origin: "live",
  };
}

const SOURCE = { time: "2026-01-01T00:00:00Z", open: "100", high: "110", low: "90", close: "105" };

describe("bars", () => {
  it("uses UTC epoch seconds", () => {
    expect(closedBar(candle("2026-01-01T00:00:00Z")).time).toBe(1767225600);
  });

  it("draws a forming candle hollow and a closed one filled", () => {
    expect(formingBar(SOURCE).color).toBe("rgba(0, 0, 0, 0)");
    expect(closedBar(candle("2026-01-01T00:00:00Z")).color).toBeUndefined();
  });

  it("colours the forming outline by direction", () => {
    expect(formingBar(SOURCE).borderColor).toBe(UP);
    expect(formingBar({ ...SOURCE, close: "95" }).borderColor).toBe(DOWN);
  });

  it("merges overlapping pages into one ordered series", () => {
    const merged = mergeCandles([
      [candle("2026-01-01T00:02:00Z"), candle("2026-01-01T00:03:00Z")],
      [candle("2026-01-01T00:01:00Z"), candle("2026-01-01T00:02:00Z", "106")],
    ]);
    expect(merged.map((c) => c.open_time.slice(14, 16))).toEqual(["01", "02", "03"]);
    expect(merged).toHaveLength(3);
  });
});
