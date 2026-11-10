// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { PaperSummary, Signal, Trade } from "@/lib/api/client";

import { BotAccount, Decisions, TradeHistory } from "./BotPanels";
import {
  averageExit,
  openLines,
  openPnl,
  percentOf,
  resultOf,
  riskPercent,
  scoreText,
  strategyLabel,
  today,
  tradeMarkers,
} from "./trades";

const OPEN: Trade = {
  simulated: true,
  id: "p1",
  instrument_id: 3,
  symbol: "SOLUSDT",
  strategy: "trend_break_baseline",
  timeframe: "15m",
  side: "LONG",
  status: "open",
  signal_state: "TP1_HIT",
  created_at: "2026-11-07T10:15:10Z",
  expires_at: "2026-11-07T12:15:10Z",
  planned_entry: "100.00",
  average_entry: "100.03",
  stop_loss: "98.00",
  current_stop: "98.00",
  targets: ["104.00", "106.00", "108.00"],
  planned_quantity: "0.40",
  open_quantity: "0.20",
  realized_pnl: "0.70",
  costs_paid: "0.06",
  opened_at: "2026-11-07T10:15:10Z",
  closed_at: null,
  outcome: null,
  r_multiple: null,
  explanation: "BOS with both higher timeframes up",
  max_account_risk: "0.98",
  risk_share: null,
  evidence_share: null,
  fills: [
    { kind: "entry", at: "2026-11-07T10:15:10Z", price: "100.03", quantity: "0.40", fee: "0.02", funding: "0", reconstructed: false },
    { kind: "tp1", at: "2026-11-07T10:31:59.999Z", price: "104.00", quantity: "0.20", fee: "0.01", funding: "0", reconstructed: false },
  ],
};

const STOPPED: Trade = {
  ...OPEN,
  id: "p2",
  side: "SHORT",
  status: "closed",
  signal_state: "STOPPED",
  open_quantity: "0",
  realized_pnl: "-1.02",
  closed_at: "2026-11-07T11:02:59.999Z",
  outcome: "LOSS",
  fills: [
    { kind: "entry", at: "2026-11-07T10:45:10Z", price: "99.97", quantity: "0.40", fee: "0.02", funding: "0", reconstructed: false },
    { kind: "stop", at: "2026-11-07T11:02:59.999Z", price: "102.06", quantity: "0.40", fee: "0.02", funding: "0", reconstructed: false },
  ],
};

const SUMMARY: PaperSummary = {
  simulated: true,
  account: "demo",
  starting_balance: "100",
  equity: "99.50",
  open_positions: 1,
  resolved_trades: 1,
  wins: 0,
  losses: 1,
  unfilled: 0,
  net_pnl: "-1.02",
  costs: "0.06",
  win_rate: 0,
  expectancy_r: -1,
  day_start_equity: "100",
  open_risk: "0.98",
  max_open_risk: null,
  daily_profit_stop: null,
};

const PLAN: PaperSummary = {
  ...SUMMARY,
  account: "portfolio",
  starting_balance: "1000",
  day_start_equity: "1000",
  equity: "1015",
  open_risk: "12.5",
  max_open_risk: "0.03",
  daily_profit_stop: "0.03",
};

const PLAN_TRADE: Trade = {
  ...OPEN,
  id: "p3",
  strategy: "daily_trend",
  timeframe: "1d",
  max_account_risk: "9.97",
  risk_share: "1",
  evidence_share: "1",
};

afterEach(cleanup);

describe("demo bot trades", () => {
  it("marks a buy below the bar and a short's sell above it, on the bar that holds the fill", () => {
    const marks = tradeMarkers([STOPPED, OPEN], 900);
    expect(marks.map((mark) => [mark.text, mark.time, mark.position])).toEqual([
      ["BUY", Date.parse("2026-11-07T10:15:00Z") / 1000, "belowBar"],
      ["TP1", Date.parse("2026-11-07T10:30:00Z") / 1000, "aboveBar"],
      ["SELL", Date.parse("2026-11-07T10:45:00Z") / 1000, "aboveBar"],
      ["STOP", Date.parse("2026-11-07T11:00:00Z") / 1000, "belowBar"],
    ]);
  });

  it("draws the open trade's entry, stop and only the targets still ahead", () => {
    expect(openLines([OPEN, STOPPED]).map((line) => [line.title, line.price])).toEqual([
      ["BUY entry", 100.03],
      ["Stop", 98],
      ["TP2", 106],
      ["TP3", 108],
    ]);
  });

  it("values open profit at the live mid and shows it against 100 USDT", () => {
    expect(openPnl(OPEN, 101.03)).toBeCloseTo(0.2);
    expect(openPnl(OPEN, null)).toBeNull();
    expect(openPnl(STOPPED, 101)).toBeNull();
    expect(percentOf(-1.02, "100")).toBeCloseTo(-1.02);
  });

  it("averages exits by quantity and says how a trade ended", () => {
    expect(averageExit(STOPPED)).toBeCloseTo(102.06);
    expect(averageExit({ ...OPEN, fills: [OPEN.fills[0]!] })).toBeNull();
    expect(resultOf(STOPPED)).toBe("LOSS at STOP");
    expect(resultOf(OPEN)).toBe("Open, part taken");
  });

  it("shows the account's profit on its 100 USDT start", () => {
    render(<BotAccount summary={SUMMARY} title="Demo account" />);
    expect(screen.getByText("100.00 USDT")).toBeTruthy();
    expect(screen.getByText("-0.50 USDT")).toBeTruthy();
    expect(screen.getByText("-0.50%")).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("shows the money plan's day against its +3% stop and the risk in open trades", () => {
    const day = today(PLAN);
    expect(day.pnl).toBeCloseTo(15);
    expect(day.percent).toBeCloseTo(1.5);
    expect(day.progress).toBeCloseTo(0.5);
    expect(day.riskLimit).toBeCloseTo(30.45);
    expect(today({ ...PLAN, equity: "990" }).progress).toBe(0);
    expect(today({ ...PLAN, equity: "1040" }).progress).toBe(1);
    render(<BotAccount summary={PLAN} title="Money plan account" />);
    expect(screen.getByText("+15.00 USDT, +1.50%")).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("50");
    expect(screen.getByText(/12\.50 of 30\.45 USDT allowed/)).toBeTruthy();
  });

  it("names each strategy and the plan's risk on a trade or signal", () => {
    expect(strategyLabel("daily_trend")).toBe("Daily trend");
    expect(strategyLabel("something_new")).toBe("something_new");
    expect(riskPercent("0.5")).toBe(0.5);
    expect(riskPercent(null)).toBeNull();
    render(<TradeHistory trades={[PLAN_TRADE]} balance="1000" ticks={new Map([[3, "0.01"]])} />);
    expect(screen.getByText("Daily trend")).toBeTruthy();
    expect(screen.getByText("9.97")).toBeTruthy();
    expect(screen.getByText("On 1000 USDT")).toBeTruthy();
    cleanup();
    const signal = {
      id: "s1",
      instrument_id: 3,
      action: "SELL",
      strategy: "pattern_breakout",
      created_at: "2026-11-09T10:00:10Z",
      decision: "APPROVED",
      rejection_codes: [],
      risk_share: "0.25",
    } as unknown as Signal;
    render(<Decisions signals={[signal]} symbols={new Map([[3, "SOLUSDT"]])} />);
    expect(screen.getByText("Approved, traded at 0.25% risk")).toBeTruthy();
  });

  it("lists every trade with its side, exit and profit", () => {
    render(<TradeHistory trades={[OPEN, STOPPED]} balance="100" ticks={new Map([[3, "0.01"]])} />);
    expect(screen.getByText("LOSS at STOP")).toBeTruthy();
    expect(screen.getByText("102.06")).toBeTruthy();
    expect(screen.getByText("-1.02")).toBeTruthy();
    expect(screen.getByText("+0.70 so far")).toBeTruthy();
    expect(screen.getAllByText("SELL")).toHaveLength(1);
  });

  it("says plainly when there are no trades yet", () => {
    render(<TradeHistory trades={[]} balance="100" ticks={new Map()} />);
    expect(screen.getByText(/No trades yet in this account/)).toBeTruthy();
  });

  it("shows each signal's score as information, and nothing for older signals", () => {
    const base = { version: 1, against: 2, weak: true, long_term_trend: true, volume: false };
    const weak = { ...base, bitcoin_trend: false, bitcoin_applies: true, funding: true };
    expect(scoreText(weak)).toBe(
      "Score weak, 2 of 4 against: coin's trend for, Bitcoin's trend against, volume against, funding for.",
    );
    const bitcoin = { ...base, against: 1, weak: false, bitcoin_trend: null, bitcoin_applies: false, funding: null };
    expect(scoreText(bitcoin)).toBe(
      "Score strong, 1 of 3 against: coin's trend for, volume against, funding unknown.",
    );
    expect(scoreText({ ...bitcoin, weak: null })).toMatch(/^Score incomplete/);
    expect(scoreText(null)).toBeNull();
    const signal = {
      id: "s2",
      instrument_id: 3,
      action: "BUY",
      strategy: "daily_trend",
      created_at: "2026-11-10T00:00:10Z",
      decision: "REJECTED",
      rejection_codes: ["RR_BELOW_MIN"],
      risk_share: "1",
      signal_score: weak,
    } as unknown as Signal;
    render(<Decisions signals={[signal]} symbols={new Map([[3, "SOLUSDT"]])} />);
    expect(screen.getByText(/^Score weak, 2 of 4 against/)).toBeTruthy();
    expect(screen.getByText(/never changes a trade's size/)).toBeTruthy();
  });
});
