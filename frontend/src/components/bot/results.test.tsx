// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Results, ResultStats } from "@/lib/api/client";

import { equitySeries, gridMatrix, profitFactor, rate, signedR, signedUsdt, streakText } from "./results";
import { ResultsDetail, ResultsSummary } from "./ResultsPanels";

vi.mock("./EquityChart", () => ({ EquityChart: () => <div>equity chart</div> }));

/** Binance demo results as the API gives them (D057). Test data, not market data. */
const STATS: ResultStats = {
  trades: 3,
  wins: 2,
  losses: 1,
  win_rate: "0.6667",
  net: "2.5",
  pnl: "2.8",
  fees: "0.25",
  funding: "-0.05",
  average_r: "1.25",
  average_win: "1.75",
  average_loss: "-1",
  profit_factor: "3.5",
  best: "2",
  worst: "-1",
};

const RESULTS: Results = {
  test_funds: true,
  period: "all",
  since: "2026-11-10T16:00:00Z",
  start_equity: "100",
  summary: STATS,
  by_coin: [{ name: "XRPUSDT", stats: STATS }],
  by_strategy: [{ name: "pattern_breakout", stats: STATS }],
  by_side: [{ name: "SHORT", stats: STATS }],
  by_day: [{ name: "2026-11-11", stats: STATS }],
  grid: [
    { strategy: "pattern_breakout", symbol: "XRPUSDT", stats: STATS },
    { strategy: "daily_trend", symbol: "SOLUSDT", stats: { ...STATS, net: "-1", trades: 1, wins: 0, losses: 1, win_rate: "0" } },
  ],
  equity: [
    { at: "2026-11-10T16:00:00Z", equity: "100" },
    { at: "2026-11-11T02:00:00Z", equity: "101" },
    { at: "2026-11-11T02:00:00.400Z", equity: "102.5" },
  ],
  drawdown: "1",
  drawdown_fraction: "0.0099",
  longest_wins: 2,
  longest_losses: 1,
  current_streak: -1,
  median_hold_hours: "6.5",
  open_trades: 3,
  not_from_bot: 1,
  other_fees: {},
  last_fill_at: "2026-11-11T02:00:00Z",
  trades: [
    {
      symbol: "XRPUSDT",
      side: "SHORT",
      strategy: "pattern_breakout",
      opened_at: "2026-11-10T16:00:13Z",
      closed_at: "2026-11-11T02:00:00Z",
      size: "6.1",
      entry_price: "0.9912",
      exit_price: "0.8650",
      pnl: "0.77",
      fees: "0.006",
      funding: "0.001",
      net: "0.765",
      r: "1.55",
      won: true,
    },
  ],
};

afterEach(cleanup);

describe("Binance demo results", () => {
  it("formats rates, money, R, profit factor and streaks", () => {
    expect(rate("0.6667")).toBe("67%");
    expect(rate(null)).toBe("–");
    expect(signedUsdt("2.5")).toBe("+2.50");
    expect(signedUsdt("-1")).toBe("-1.00");
    expect(signedUsdt("-0.0022")).toBe("-0.0022"); // Funding on one trade, not "-0.00".
    expect(signedUsdt("0")).toBe("0.00");
    expect(signedR("1.25")).toBe("+1.25R");
    expect(profitFactor(STATS)).toBe("3.50");
    expect(profitFactor({ ...STATS, profit_factor: null })).toBe("no losses");
    expect(profitFactor({ ...STATS, trades: 0, profit_factor: null })).toBe("–");
    expect(streakText(-2)).toBe("2 lost in a row");
    expect(streakText(0)).toBe("–");
  });

  it("keeps one equity point per second, the later one, in time order", () => {
    expect(equitySeries(RESULTS).map((point) => point.value)).toEqual([100, 102.5]);
  });

  it("lays out every strategy against every coin, empty cells included", () => {
    const { strategies, symbols, cell } = gridMatrix(RESULTS);
    expect(strategies).toEqual(["daily_trend", "pattern_breakout"]);
    expect(symbols).toEqual(["SOLUSDT", "XRPUSDT"]);
    expect(cell("daily_trend", "XRPUSDT")).toBeNull();
    expect(cell("daily_trend", "SOLUSDT")?.net).toBe("-1");
  });

  it("shows the headline figures and what was left out", () => {
    render(<ResultsSummary results={RESULTS} period="all" onPeriod={() => undefined} />);
    expect(screen.getByText("3 (2 won, 1 lost)")).toBeTruthy();
    expect(screen.getByText("67%")).toBeTruthy();
    expect(screen.getByText("+2.50 USDT")).toBeTruthy();
    expect(screen.getByText("+1.25R")).toBeTruthy();
    expect(screen.getByText("1 lost in a row")).toBeTruthy();
    expect(screen.getByText(/1 completed trade not opened by the bot left out/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "All time" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("shows each breakdown and the completed trades with full prices", () => {
    render(<ResultsDetail results={RESULTS} />);
    for (const caption of ["By coin", "By strategy", "Long and short", "By day", "Completed trades, newest first"]) {
      expect(screen.getByText(caption)).toBeTruthy();
    }
    expect(screen.getByText(/Strategy by coin/)).toBeTruthy();
    expect(screen.getAllByText("1H pattern").length).toBeGreaterThan(0);
    expect(screen.getByText("0.8650")).toBeTruthy();
    expect(screen.getAllByText("Short (sell)")).toHaveLength(2); // Long and short, and the trade.
  });

  it("says plainly when nothing has closed yet", () => {
    render(<ResultsDetail results={{ ...RESULTS, summary: { ...STATS, trades: 0, wins: 0, losses: 0 } }} />);
    expect(screen.getByText(/No completed trades on this account in this period yet/)).toBeTruthy();
  });

  it("opens a completed trade on the chart, as the Binance app does (D065)", () => {
    const onChart = vi.fn();
    render(<ResultsDetail results={RESULTS} onChart={onChart} />);
    const [trade] = RESULTS.trades;
    fireEvent.click(screen.getByRole("button", { name: new RegExp(`Show the ${trade!.symbol} trade closed .* on the chart`) }));
    expect(onChart).toHaveBeenCalledWith(trade);
  });
});
