// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ForecastPlan, ForecastView } from "@/lib/api/client";

import { signalMarkers } from "./ForecastChart";
import {
  CandleSignalsPanel,
  HoverReadout,
  LayerToggles,
  LevelsPanel,
  PlanPanel,
  SummaryPanel,
  TrackRecordPanel,
} from "./ForecastPanels";
import { ALL_LAYERS } from "./overlay";

const band = (p10: number, p50: number, p90: number) => ({ p10, p50, p90 });

const PLAN: ForecastPlan = {
  source: "manual analyst test: a Claude Code session standing in for the API",
  created_at: "2026-11-05T03:14:02Z",
  as_of: "2026-11-05T02:59:59.999Z",
  expires_at: "2026-11-05T07:00:00Z",
  action: "SELL",
  side: "SHORT",
  entry_type: "LIMIT",
  entry: "80982.5",
  stop: "81319",
  targets: ["79947.6", "79644"],
  entry_level_id: "L3",
  stop_level_id: "L6",
  target_level_ids: ["L4", "L10"],
  grade: "B",
  approved: true,
  rejection_codes: [],
  quantity: "0.119",
  max_loss: "49.93",
  reward_risk: ["2.33", "3.06"],
  bull_case: "case for",
  bear_case: "case against",
  pre_mortem: "pre-mortem",
  note: "",
  status: {
    state: "waiting",
    exit_reason: null,
    entry_price: null,
    entry_time: null,
    exit_price: null,
    exit_time: null,
    net_pnl: null,
    result_r: null,
    checked_until: null,
  },
};

const VIEW: ForecastView = {
  label: "unvalidated model forecast",
  provider: "binance_usdm",
  instrument_id: 3,
  symbol: "BTCUSDT",
  timeframe: "1h",
  as_of: "2026-11-05T02:59:59.999Z",
  created_at: "2026-11-05T03:08:00Z",
  reason: "manual",
  model: "NeoQuasar/Kronos-small",
  model_revision: "901c26c",
  last_close: "80544.2",
  atr: 523.73,
  model_paths: 30,
  baseline_paths: 10000,
  baseline_rebuilt: true,
  steps: [
    { open_time: "2026-11-05T03:00:00Z", model: band(80280, 80480, 80680), baseline: band(80247, 80543, 80813) },
  ],
  paths: [[80500]],
  horizons: [
    {
      candles: 4,
      model: { share_ending_higher: 0.33, highest: band(80600, 80921, 81445), lowest: band(79770, 80172, 80377), close: band(80083, 80450, 81068) },
      baseline: { share_ending_higher: 0.49, highest: band(80607, 80848, 81445), lowest: band(79586, 80220, 80481), close: band(79900, 80534, 81157) },
    },
  ],
  levels: [
    { id: "L3", price: "80982.5", kind: "resistance", position: "above", evidence: "test", distance_atr: 0.84, reach: [{ candles: 4, model: 0.42, baseline: 0.35 }] },
    { id: "L1", price: "80503.2", kind: "support", position: "below", evidence: "test", distance_atr: -0.08, reach: [{ candles: 4, model: 1, baseline: 0.93 }] },
  ],
  patterns: [],
  candle_signals: [
    { type: "shooting_star", direction: "bearish", open_time: "2026-11-05T00:00:00Z" },
    { type: "bullish_harami", direction: "bullish", open_time: "2026-11-04T03:00:00Z" },
  ],
  context: {
    trend_4h: "up",
    trend_1d: "down",
    regime_trend: "transition",
    regime_volatility: "normal",
    adx_1d: 21.8,
    volatility_percentile: 28.5,
    rsi_1h: 68.7,
    rsi_4h: 66.2,
    strategies: [{ name: "1H pattern breakout", action: "NO_TRADE", reasons: ["no pattern breakout"] }],
  },
  track_record: { resolved: 3, status: "too few forecasts", brier_model: 0.898, brier_baseline: 0.258, crps_model_pct: 3.2, crps_baseline_pct: 0.9 },
  plan: PLAN,
};

afterEach(cleanup);

describe("forecast panels", () => {
  it("compares Kronos with the baseline for the chosen span", () => {
    render(<SummaryPanel horizon={VIEW.horizons[0]!} lastClose={80544.2} atr={523.73} />);
    expect(screen.getByText("Next 4 hours")).toBeTruthy();
    expect(screen.getByText("33%")).toBeTruthy();
    expect(screen.getByText("49%")).toBeTruthy();
  });

  it("labels the model unvalidated and says the baseline has been better", () => {
    render(<TrackRecordPanel view={VIEW} />);
    expect(screen.getByRole("status").textContent).toContain("Unvalidated model output: too few forecasts, 3 resolved");
    expect(screen.getByText(/The baseline has been better so far/)).toBeTruthy();
  });

  it("shows the plan by level ID with its status, labelled as a manual paper test", () => {
    render(<PlanPanel plan={PLAN} />);
    expect(screen.getByText(/manual analyst test/).textContent).toContain("Paper only");
    expect(screen.getByText("Sell limit 80,982.5")).toBeTruthy();
    expect(screen.getByText("79,947.6 · 2.33R")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Waiting for fill until 07:00 UTC");
  });

  it("marks the levels the plan uses and how often each source reaches them", () => {
    render(<LevelsPanel view={VIEW} span={4} />);
    expect(screen.getByText("entry")).toBeTruthy();
    expect(screen.getByText("42%")).toBeTruthy();
    expect(screen.getByText("35%")).toBeTruthy();
  });

  it("reads the forecast under the cursor, and the span summary otherwise", () => {
    const { rerender } = render(
      <HoverReadout view={VIEW} hoverTime={Date.parse("2026-11-05T03:00:00Z") / 1000} span={4} barSeconds={3600} />,
    );
    expect(screen.getByText(/03:00 UTC close/)).toBeTruthy();
    rerender(<HoverReadout view={VIEW} hoverTime={Date.parse("2026-11-05T00:00:00Z") / 1000} span={4} barSeconds={3600} />);
    expect(screen.getByText(/Shooting star/)).toBeTruthy();
    rerender(<HoverReadout view={VIEW} hoverTime={null} span={4} barSeconds={3600} />);
    expect(screen.getByText(/Kronos 33% of paths end higher/)).toBeTruthy();
  });

  it("lists candle signals newest first, named, with their direction", () => {
    render(<CandleSignalsPanel view={VIEW} />);
    const items = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(items[0]).toContain("Shooting star");
    expect(items[1]).toContain("Bullish harami");
    expect(screen.getAllByLabelText("bearish").length).toBe(1);
  });

  it("turns layers off from the legend", () => {
    const onChange = vi.fn();
    render(<LayerToggles layers={ALL_LAYERS} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: /Kronos paths/ }));
    expect(onChange).toHaveBeenCalledWith({ ...ALL_LAYERS, paths: false });
  });
});

describe("signalMarkers", () => {
  it("puts bearish signals above the bar and bullish below, oldest first", () => {
    const markers = signalMarkers(VIEW.candle_signals, 3600);
    expect(markers.map((m) => m.position)).toEqual(["belowBar", "aboveBar"]);
    expect(markers[1]!.text).toBeUndefined();
  });

  it("draws one arrow per direction on a bar holding several signals", () => {
    const signals = [
      { type: "shooting_star", direction: "bearish", open_time: "2026-11-05T00:00:00Z" },
      { type: "pin_bar", direction: "bearish", open_time: "2026-11-05T01:00:00Z" },
      { type: "hammer", direction: "bullish", open_time: "2026-11-05T02:00:00Z" },
    ];
    expect(signalMarkers(signals, 4 * 3600).map((m) => m.position)).toEqual(["aboveBar", "belowBar"]);
    expect(signalMarkers(signals, 3600)).toHaveLength(3);
  });

  it("snaps a 1H signal onto the 4H bar that holds it", () => {
    const [marker] = signalMarkers([VIEW.candle_signals[0]!], 4 * 3600);
    expect(Number(marker!.time)).toBe(Date.parse("2026-11-05T00:00:00Z") / 1000);
  });
});
