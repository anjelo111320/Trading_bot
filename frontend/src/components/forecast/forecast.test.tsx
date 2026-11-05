// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AnalysisJob, ForecastPlan, ForecastView } from "@/lib/api/client";

import { liveBar, signalMarkers } from "./ForecastChart";
import { LiveStatus, ReanalyseButton, analysisText } from "./LiveControls";
import {
  CandleSignalsPanel,
  HoverReadout,
  LayerToggles,
  LevelsPanel,
  PlanPanel,
  SummaryPanel,
  TrackRecordPanel,
} from "./ForecastPanels";
import { ALL_LAYERS, planRoles } from "./overlay";

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
  analysis_as_of: "2026-11-05T02:59:59.999Z",
  analysis_close: "80544.2",
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

const RUNNING: AnalysisJob = {
  state: "running",
  instrument_id: 3,
  symbol: "BTCUSDT",
  as_of: "2026-11-05T07:59:59.999Z",
  started_at: "2026-11-05T08:01:00Z",
  finished_at: null,
  message: null,
};

describe("re-analysis", () => {
  it("counts the elapsed time while Kronos runs, and names the close", () => {
    const now = Date.parse("2026-11-05T08:01:42Z");
    expect(analysisText(RUNNING, now)).toBe(
      "Analysing BTCUSDT from the 07:59 UTC close · 0:42, about 1:30 for Kronos",
    );
    expect(analysisText({ ...RUNNING, state: "failed", message: "too old" }, now)).toBe(
      "Analysis failed: too old",
    );
    expect(analysisText({ ...RUNNING, state: "succeeded" }, now)).toBe(
      "Analysed BTCUSDT from the 07:59 UTC close",
    );
    expect(analysisText(undefined, now)).toBeNull();
  });

  it("disables the button while one runs, and asks for one otherwise", () => {
    const onClick = vi.fn();
    const { rerender } = render(<ReanalyseButton job={RUNNING} now={Date.now()} error={null} onClick={onClick} />);
    expect((screen.getByRole("button") as HTMLButtonElement).disabled).toBe(true);
    rerender(<ReanalyseButton job={{ ...RUNNING, state: "idle" }} now={Date.now()} error={null} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: "Re-analyse" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("shows a refusal from the server", () => {
    render(<ReanalyseButton job={undefined} now={0} error="An analysis of ETHUSDT is already running." onClick={() => {}} />);
    expect(screen.getByRole("status").textContent).toContain("already running");
  });
});

describe("live chart", () => {
  it("says when the feed is live and shows the mid price", () => {
    const { rerender } = render(
      <LiveStatus connection="open" price={{ bid: "80600.1", ask: "80600.3", receivedAt: "" }} />,
    );
    expect(screen.getByRole("status").textContent).toBe("●Live80,600.2");
    rerender(<LiveStatus connection="connecting" price={null} />);
    expect(screen.getByRole("status").textContent).toContain("Reconnecting");
  });

  it("draws the forming candle hollow and a closed one filled", () => {
    const candle = { openTime: "2026-11-05T07:00:00Z", open: "1", high: "3", low: "1", close: "2", isClosed: false };
    expect(liveBar(candle).color).toBe("rgba(0, 0, 0, 0)");
    expect(liveBar({ ...candle, isClosed: true }).color).toBeUndefined();
    expect(Number(liveBar(candle).time)).toBe(Date.parse("2026-11-05T07:00:00Z") / 1000);
  });
});

describe("planRoles", () => {
  it("matches the plan to today's levels by price, not by stale IDs", () => {
    const later: ForecastView = {
      ...VIEW,
      analysis_as_of: "2026-11-05T09:59:59.999Z",
      levels: [
        { ...VIEW.levels[0]!, id: "L2", price: "80982.5" },
        { ...VIEW.levels[1]!, id: "L3", price: "80927.5" },
      ],
    };
    const roles = planRoles(later);
    expect(roles.get("L2")).toBe("entry");
    expect(roles.has("L3")).toBe(false);
    expect([...roles.values()]).not.toContain("stop beyond");
  });

  it("trusts the stop's level ID while the analysis is at the plan's close", () => {
    expect(planRoles(VIEW).get("L6")).toBe("stop beyond");
  });
});
