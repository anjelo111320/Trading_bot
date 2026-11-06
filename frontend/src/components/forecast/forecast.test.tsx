// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AnalysisJob, ForecastKronos, ForecastPlan, ForecastProjection, ForecastStrategy, ForecastView } from "@/lib/api/client";

import { liveBar, signalMarkers } from "./ForecastChart";
import { LiveStatus, ReanalyseButton, analysisText, duration } from "./LiveControls";
import {
  CandleSignalsPanel,
  HoverReadout,
  LayerToggles,
  LevelsPanel,
  PlanPanel,
  PythonSignalPanel,
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
  python_at_close: null,
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

const PROJECTION: ForecastProjection = {
  as_of: "2026-11-05T02:59:59.999Z",
  last_close: "80544.2",
  atr: 523.73,
  paths: 10000,
  steps: [{ open_time: "2026-11-05T03:00:00Z", close: band(80247, 80543, 80813) }],
  horizons: [
    {
      candles: 4,
      baseline: { share_ending_higher: 0.49, highest: band(80607, 80848, 81445), lowest: band(79586, 80220, 80481), close: band(79900, 80534, 81157) },
    },
  ],
};

const KRONOS: ForecastKronos = {
  label: "unvalidated model forecast",
  as_of: "2026-11-05T02:59:59.999Z",
  current: true,
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
  track_record: { resolved: 3, status: "too few forecasts", brier_model: 0.898, brier_baseline: 0.258, crps_model_pct: 3.2, crps_baseline_pct: 0.9 },
};

/** A view from before Kronos was retired, with a current run. */
const VIEW: ForecastView = {
  provider: "binance_usdm",
  instrument_id: 3,
  symbol: "BTCUSDT",
  timeframe: "1h",
  analysis_as_of: "2026-11-05T02:59:59.999Z",
  analysis_close: "80544.2",
  projection: PROJECTION,
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
  plan: PLAN,
  kronos_enabled: true,
  kronos: KRONOS,
};

/** Seven hours later: Python has moved on, and the Kronos run is still from 02:59. */
const LATER: ForecastView = {
  ...VIEW,
  analysis_as_of: "2026-11-05T09:59:59.999Z",
  analysis_close: "79100",
  kronos: { ...KRONOS, current: false },
  projection: {
    ...PROJECTION,
    as_of: "2026-11-05T09:59:59.999Z",
    last_close: "79100",
    steps: [{ open_time: "2026-11-05T10:00:00Z", close: band(78800, 79090, 79400) }],
    horizons: [
      {
        candles: 4,
        baseline: { share_ending_higher: 0.47, highest: band(79200, 79500, 80100), lowest: band(78300, 78800, 79000), close: band(78600, 79080, 79600) },
      },
    ],
  },
  levels: VIEW.levels.map((level) => ({ ...level, reach: [{ candles: 4, model: null, baseline: 0.2 }] })),
};

/** Since 2026-11-06 Kronos is off (D040): Python's view alone. */
const PYTHON_ONLY: ForecastView = {
  ...LATER,
  kronos_enabled: false,
  kronos: null,
  levels: VIEW.levels.map((level) => ({ ...level, reach: [{ candles: 4, model: null, baseline: 0.3 }] })),
};

afterEach(cleanup);

describe("with Kronos off", () => {
  it("shows the baseline from the latest close and no Kronos column", () => {
    render(<SummaryPanel view={PYTHON_ONLY} span={4} />);
    expect(screen.getByText("47%")).toBeTruthy();
    expect(screen.queryByText("Kronos")).toBeNull();
    expect(screen.queryByText("–")).toBeNull();
  });

  it("lists levels with the baseline's reach only", () => {
    render(<LevelsPanel view={PYTHON_ONLY} span={4} />);
    expect(screen.queryByText("Kronos")).toBeNull();
    expect(screen.getAllByText("30%")).toHaveLength(2);
  });

  it("hides the Kronos track record, readout and layer switches", () => {
    const { container } = render(<TrackRecordPanel view={PYTHON_ONLY} />);
    expect(container.textContent).toBe("");
    render(<HoverReadout view={PYTHON_ONLY} hoverTime={null} span={4} barSeconds={3600} />);
    expect(screen.getByText(/baseline 47% of paths end higher/)).toBeTruthy();
    expect(screen.queryByText(/Kronos/)).toBeNull();
    render(<LayerToggles layers={ALL_LAYERS} onChange={() => {}} />);
    expect(screen.queryByRole("button", { name: /Kronos/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Baseline/ })).toBeTruthy();
  });
});

describe("forecast panels", () => {
  it("compares a current Kronos run with the baseline from the latest close", () => {
    render(<SummaryPanel view={VIEW} span={4} />);
    expect(screen.getByText("Next 4 hours · from 02:59 UTC")).toBeTruthy();
    expect(screen.getByText("33%")).toBeTruthy();
    expect(screen.getByText("49%")).toBeTruthy();
  });

  it("projects from the latest close and leaves an old Kronos run out, saying how old", () => {
    render(<SummaryPanel view={LATER} span={4} />);
    expect(screen.getByText("Next 4 hours · from 09:59 UTC")).toBeTruthy();
    expect(screen.getByText("47%")).toBeTruthy();
    expect(screen.getAllByText("–")).toHaveLength(5);
    expect(screen.getByText(/Kronos last ran from the 02:59 UTC close, 7h earlier/)).toBeTruthy();
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

  it("shows Python's own signal first, with Python's prices when it has one", () => {
    const trend: ForecastStrategy = {
      name: "Daily trend",
      action: "BUY",
      reasons: ["close beyond the 20-day range"],
      proposal: { side: "LONG", entry_type: "MARKET", entry: "80544.2", stop: "79500", targets: ["90988.2"] },
    };
    const view: ForecastView = { ...VIEW, context: { ...VIEW.context, strategies: [VIEW.context.strategies[0]!, trend] } };
    render(<PythonSignalPanel view={view} />);
    expect(screen.getByText("Python signal · 02:59 UTC close")).toBeTruthy();
    expect(screen.getByText("Buy market 80,544.2 · stop 79,500 · target 90,988.2")).toBeTruthy();
    expect(screen.getByText(/Claude only reviews a Python signal and never sets a price/)).toBeTruthy();
  });

  it("says when Claude planned without a Python signal at that close", () => {
    // Regression: the BTC plan of 2026-11-05 was made while both strategies said no trade.
    const python: ForecastStrategy[] = [
      { name: "1H pattern breakout", action: "NO_TRADE", reasons: ["no pattern breakout"], proposal: null },
      { name: "Daily trend", action: "NO_TRADE", reasons: ["no 20-day breakout"], proposal: null },
    ];
    const { rerender } = render(<PlanPanel plan={{ ...PLAN, python_at_close: python }} />);
    expect(screen.getByText(/Python first, at the 02:59 UTC close/)).toBeTruthy();
    expect(screen.getByText(/Python had no signal at this close, so this plan was Claude's own idea/)).toBeTruthy();
    rerender(<PlanPanel plan={PLAN} />);
    expect(screen.getByText("No Python calculation was saved with this plan.")).toBeTruthy();
  });

  it("marks the levels the plan uses and how often each source reaches them", () => {
    render(<LevelsPanel view={VIEW} span={4} />);
    expect(screen.getByText("entry")).toBeTruthy();
    expect(screen.getByText("42%")).toBeTruthy();
    expect(screen.getByText("35%")).toBeTruthy();
  });

  it("gives no Kronos reach for today's levels from an old run", () => {
    render(<LevelsPanel view={LATER} span={4} />);
    expect(screen.getAllByText("–")).toHaveLength(2);
    expect(screen.getAllByText("20%")).toHaveLength(2);
    expect(screen.getByText(/within 4h of the 09:59 UTC close/)).toBeTruthy();
  });

  it("reads the projection and Kronos under the cursor, and the span summary otherwise", () => {
    const { rerender } = render(
      <HoverReadout view={VIEW} hoverTime={Date.parse("2026-11-05T03:00:00Z") / 1000} span={4} barSeconds={3600} />,
    );
    expect(screen.getByText(/03:00 UTC candle · Baseline 80,543/)).toBeTruthy();
    expect(screen.getByText(/Kronos 80,480/)).toBeTruthy();
    rerender(<HoverReadout view={VIEW} hoverTime={Date.parse("2026-11-05T00:00:00Z") / 1000} span={4} barSeconds={3600} />);
    expect(screen.getByText(/Shooting star/)).toBeTruthy();
    rerender(<HoverReadout view={VIEW} hoverTime={null} span={4} barSeconds={3600} />);
    expect(screen.getByText(/Next 4h from the 02:59 UTC close: baseline 49% of paths end higher/)).toBeTruthy();
    expect(screen.getByText(/Kronos 33%/)).toBeTruthy();
  });

  it("names an old Kronos run as old, and reads the future from the latest close", () => {
    const { rerender } = render(<HoverReadout view={LATER} hoverTime={null} span={4} barSeconds={3600} />);
    expect(screen.getByText(/Next 4h from the 09:59 UTC close: baseline 47%/)).toBeTruthy();
    expect(screen.getByText(/Kronos run is 7h old/)).toBeTruthy();
    rerender(<HoverReadout view={LATER} hoverTime={Date.parse("2026-11-05T10:00:00Z") / 1000} span={4} barSeconds={3600} />);
    expect(screen.getByText(/10:00 UTC candle · Baseline 79,090/)).toBeTruthy();
    expect(screen.queryByText(/Kronos/)).toBeNull();
    rerender(<HoverReadout view={LATER} hoverTime={Date.parse("2026-11-05T03:00:00Z") / 1000} span={4} barSeconds={3600} />);
    expect(screen.getByText(/Kronos run from 02:59 UTC: 80,480/)).toBeTruthy();
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
    render(<LayerToggles layers={ALL_LAYERS} onChange={onChange} kronos />);
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
  const now = Date.parse("2026-11-06T01:46:00Z");

  it("says when the feed is live and shows the mid price", () => {
    const price = { bid: "80600.1", ask: "80600.3", receivedAt: "2026-11-06T01:45:50Z" };
    const { rerender } = render(<LiveStatus connection="open" price={price} now={now} />);
    expect(screen.getByRole("status").textContent).toBe("●Live80,600.2");
    rerender(<LiveStatus connection="connecting" price={null} now={now} />);
    expect(screen.getByRole("status").textContent).toContain("Reconnecting");
    rerender(<LiveStatus connection="open" price={null} now={now} />);
    expect(screen.getByRole("status").textContent).toContain("waiting for prices");
  });

  it("says the feed has stopped when prices stop, though the socket stays open", () => {
    // Regression: the page said Live through a night with no data, while the Mac slept.
    const price = { bid: "80600.1", ask: "80600.3", receivedAt: "2026-11-05T15:41:00Z" };
    render(<LiveStatus connection="open" price={price} now={now} />);
    expect(screen.getByRole("status").textContent).toBe("●No new prices for 10 h");
    expect(duration(90)).toBe("2 min");
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

  it("gives today's levels no roles from a finished plan", () => {
    const expired = { ...PLAN, status: { ...PLAN.status, state: "not_filled" as const, exit_reason: "expiry" } };
    expect(planRoles({ ...VIEW, plan: expired }).size).toBe(0);
  });
});
