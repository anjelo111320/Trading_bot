// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ExchangeOrder, ExchangeStatus } from "@/lib/api/client";

import { binanceLines, binanceMarkers, budgetProfit, heldOnBinance, protection } from "./binance";
import { BinanceAccount, BinanceOrders, BinancePosition } from "./BinancePanels";

/** A Binance demo snapshot, as the quant worker saves it. Test data, not market data. */
const STATUS: ExchangeStatus = {
  test_funds: true,
  connected: true,
  taken_at: "2026-11-10T15:00:05Z",
  age_seconds: 20,
  binance_equity: "5001.20",
  binance_available: "4958.40",
  capital: "100",
  equity: "101.20",
  day_start_equity: "100",
  available: "59.30",
  positions: [
    {
      symbol: "SOLUSDT",
      side: "SHORT",
      quantity: "0.5",
      entry_price: "84.10",
      mark_price: "83.80",
      notional: "41.90",
      margin: "41.90",
      unrealized: "0.15",
      liquidation: "160.2",
    },
  ],
  orders: [
    { symbol: "SOLUSDT", type: "STOP_MARKET", side: "BUY", trigger: "86.10", quantity: null, close_position: true },
    { symbol: "SOLUSDT", type: "TAKE_PROFIT_MARKET", side: "BUY", trigger: "78.10", quantity: "0.10", close_position: false },
    { symbol: "SOLUSDT", type: "TAKE_PROFIT_MARKET", side: "BUY", trigger: "80.10", quantity: "0.25", close_position: false },
  ],
};

function order(overrides: Partial<ExchangeOrder>): ExchangeOrder {
  return {
    created_at: "2026-11-10T14:45:10Z",
    symbol: "SOLUSDT",
    kind: "entry",
    side: "SELL",
    type: "MARKET",
    quantity: "0.5",
    trigger: null,
    executed: "0.5",
    average_price: "84.10",
    outcome: "accepted",
    error: null,
    ...overrides,
  };
}

afterEach(cleanup);

describe("Binance demo on the Bot page", () => {
  it("finds the stop and orders the targets nearest first", () => {
    const { stop, targets } = protection(STATUS, "SOLUSDT");
    expect(stop?.trigger).toBe("86.10");
    expect(targets.map((target) => target.trigger)).toEqual(["80.10", "78.10"]);
    expect(protection(STATUS, "BTCUSDT").stop).toBeNull();
  });

  it("draws the position's entry, stop and targets on its own coin only", () => {
    expect(binanceLines(STATUS, "SOLUSDT").map((line) => line.title)).toEqual(["SELL entry", "Stop", "TP1", "TP2"]);
    expect(binanceLines(STATUS, "BTCUSDT")).toEqual([]);
    expect(binanceLines(undefined, "SOLUSDT")).toEqual([]);
  });

  it("marks filled entries and closes, not refused orders or other coins", () => {
    const sent = [
      order({}),
      order({ kind: "close", side: "BUY", created_at: "2026-11-10T15:31:00Z" }),
      order({ kind: "stop", outcome: "refused", side: "BUY" }),
      order({ symbol: "XRPUSDT" }),
    ];
    const marks = binanceMarkers(sent, "SOLUSDT", 900);
    expect(marks.map((mark) => [mark.shape, mark.text])).toEqual([
      ["arrowDown", "SELL"],
      ["circle", "CLOSE"],
    ]);
    expect(Number(marks[0]!.time)).toBe(Date.parse("2026-11-10T14:45:00Z") / 1000);
  });

  it("adds up the USDT held and the profit on the budget", () => {
    expect(heldOnBinance(STATUS.positions)).toEqual({ value: 41.9, margin: 41.9 });
    expect(budgetProfit(STATUS)).toBeCloseTo(1.2, 6);
  });

  it("shows the budget, not all the test funds", () => {
    render(<BinanceAccount status={STATUS} />);
    expect(screen.getByText("100.00 USDT")).toBeTruthy();
    expect(screen.getByText("101.20 USDT")).toBeTruthy();
    expect(screen.getByText(/Test funds on Binance: 5001.20 USDT/)).toBeTruthy();
    expect(screen.getByText(/Checked on Binance 20s ago/)).toBeTruthy();
  });

  it("warns when the worker has stopped checking, and waits before the first check", () => {
    render(<BinanceAccount status={{ ...STATUS, age_seconds: 600 }} />);
    expect(screen.getByRole("alert").textContent).toMatch(/may be stopped/);
    cleanup();
    render(<BinanceAccount status={{ ...STATUS, connected: false }} />);
    expect(screen.getByText(/Waiting for the quant worker/)).toBeTruthy();
  });

  it("shows an open position with the stop and targets Binance holds", () => {
    render(<BinancePosition status={STATUS} position={STATUS.positions[0]!} tickSize="0.01" />);
    expect(screen.getByText("86.10")).toBeTruthy();
    expect(screen.getByText("80.10 / 78.10")).toBeTruthy();
    expect(screen.getByText("+0.15 USDT")).toBeTruthy();
  });

  it("lists every order with what Binance did with it", () => {
    const sent = [order({}), order({ kind: "stop", outcome: "refused", error: "Binance 400 -2021: would trigger" })];
    render(<BinanceOrders orders={sent} ticks={new Map([["SOLUSDT", "0.01"]])} />);
    expect(screen.getByText("Accepted")).toBeTruthy();
    expect(screen.getByText(/Refused: Binance 400 -2021/)).toBeTruthy();
  });
});
