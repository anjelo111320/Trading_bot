// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import type { SeriesMarker, Time, UTCTimestamp } from "lightweight-charts";
import { afterEach, describe, expect, it } from "vitest";

import { LayerToggles } from "@/components/forecast/ForecastPanels";
import { ALL_LAYERS } from "@/components/forecast/overlay";
import type { Candle, ForecastView } from "@/lib/api/client";

import { botMarkers, chartSlots, hoursBehind, rightRoom } from "./analysis";
import { BotAnalysis } from "./BotAnalysis";

const band = (p10: number, p50: number, p90: number) => ({ p10, p50, p90 });

/** Python's view at a 1H close, with Kronos off (D040). Test data, not market data. */
const VIEW: ForecastView = {
  provider: "binance_usdm",
  instrument_id: 3,
  symbol: "BTCUSDT",
  timeframe: "1h",
  analysis_as_of: "2026-11-10T09:59:59.999Z",
  analysis_close: "79100",
  projection: {
    as_of: "2026-11-10T09:59:59.999Z",
    last_close: "79100",
    atr: 520,
    paths: 10000,
    steps: [{ open_time: "2026-11-10T10:00:00Z", close: band(78800, 79090, 79400) }],
    horizons: [
      {
        candles: 4,
        baseline: { share_ending_higher: 0.47, highest: band(79200, 79500, 80100), lowest: band(78300, 78800, 79000), close: band(78600, 79080, 79600) },
      },
    ],
  },
  levels: [
    { id: "L1", price: "79400", kind: "resistance", position: "above", evidence: "test", distance_atr: 0.58, reach: [{ candles: 4, model: null, baseline: 0.3 }] },
  ],
  patterns: [],
  candle_signals: [
    { type: "shooting_star", direction: "bearish", open_time: "2026-11-10T08:00:00Z" },
    { type: "bullish_engulfing", direction: "bullish", open_time: "2026-11-10T06:00:00Z" },
  ],
  context: {
    trend_4h: "up",
    trend_1d: "down",
    regime_trend: "transition",
    regime_volatility: "normal",
    adx_1d: 21.8,
    volatility_percentile: 28.5,
    rsi_1h: 61.2,
    rsi_4h: 55.0,
    strategies: [{ name: "1H pattern breakout", action: "NO_TRADE", reasons: ["no pattern breakout"] }],
  },
  plan: null,
  kronos_enabled: false,
  kronos: null,
};

const candle = (open_time: string) => ({ open_time }) as Candle;
const at = (iso: string) => (Date.parse(iso) / 1000) as UTCTimestamp;

afterEach(cleanup);

describe("Python's analysis on the Bot chart", () => {
  it("places the overlay between the chart's own bars, including a newer live bar", () => {
    const candles = [candle("2026-11-10T09:45:00Z"), candle("2026-11-10T10:00:00Z")];
    expect(chartSlots(candles, "2026-11-10T10:15:00Z")).toEqual([at("2026-11-10T09:45:00Z"), at("2026-11-10T10:00:00Z"), at("2026-11-10T10:15:00Z")]);
    expect(chartSlots(candles, "2026-11-10T10:00:00Z")).toHaveLength(2);
    expect(chartSlots([], null)).toEqual([]);
  });

  it("keeps room on the right only while a drawing needs it", () => {
    expect(rightRoom(ALL_LAYERS, "15m", null)).toBe(0);
    expect(rightRoom(ALL_LAYERS, "15m", VIEW)).toBe(20 + 16);
    expect(rightRoom(ALL_LAYERS, "1h", VIEW)).toBe(20 + 4);
    expect(rightRoom(ALL_LAYERS, "1m", VIEW)).toBe(20 + 24);
    expect(rightRoom({ ...ALL_LAYERS, baseline: false }, "15m", VIEW)).toBe(20);
    const none = { ...ALL_LAYERS, zones: false, baseline: false, plan: false, patterns: false };
    expect(rightRoom(none, "15m", VIEW)).toBe(0);
  });

  it("adds candle signals as squares in time order, apart from the trade arrows", () => {
    const entry: SeriesMarker<Time> = { time: at("2026-11-10T07:00:00Z"), position: "belowBar", shape: "arrowUp", color: "green", id: "t:entry" };
    const markers = botMarkers([entry], VIEW, ALL_LAYERS, "1h");
    expect(markers.map((m) => m.shape)).toEqual(["square", "arrowUp", "square"]);
    expect(markers.map((m) => m.position)).toEqual(["belowBar", "belowBar", "aboveBar"]);
    expect(botMarkers([entry], VIEW, { ...ALL_LAYERS, signals: false }, "1h")).toEqual([entry]);
    expect(botMarkers([entry], null, ALL_LAYERS, "1h")).toEqual([entry]);
  });

  it("names the candle-signal switch with a square", () => {
    render(<LayerToggles layers={ALL_LAYERS} onChange={() => {}} squareSignals />);
    expect(screen.getByRole("button", { name: /Candle signals/ }).textContent).toContain("■");
    expect(screen.queryByRole("button", { name: /Kronos/ })).toBeNull();
  });

  it("counts whole hours since the latest 1H close", () => {
    expect(hoursBehind(VIEW, Date.parse("2026-11-10T13:30:00Z"))).toBe(3);
  });
});

describe("the Analysis tab", () => {
  it("shows the chosen Forecast panels, Python first", () => {
    render(<BotAnalysis view={VIEW} symbol="BTCUSDT" missing={false} failed={false} />);
    const titles = screen.getAllByRole("heading").map((heading) => heading.textContent);
    expect(titles).toEqual([
      "Python signal · 09:59 UTC close",
      "Next 4 hours · from 09:59 UTC",
      "Python levels · reached within 4h",
      "What Python sees",
      "Candle signals · last 24h",
    ]);
    expect(screen.getByText(/Information only/)).toBeTruthy();
    expect(screen.queryByText(/Claude's plan/)).toBeNull();
  });

  it("says when there is no analysis, or when it failed", () => {
    render(<BotAnalysis view={undefined} symbol="DOGEUSDT" missing failed={false} />);
    expect(screen.getByText(/No Python analysis for DOGEUSDT yet/)).toBeTruthy();
    cleanup();
    render(<BotAnalysis view={undefined} symbol="DOGEUSDT" missing={false} failed />);
    expect(screen.getByRole("alert").textContent).toMatch(/could not be loaded/);
  });
});
