import { describe, expect, it } from "vitest";

import type { ClosedTrade, Signal } from "@/lib/api/client";

import {
  chartHref,
  chartTimeframe,
  focusMarkers,
  focusOfSignal,
  focusOfTrade,
  focusRange,
  readChartLink,
  tradeText,
  tradeTone,
  withFocus,
} from "./focus";

/** A BUY that entered at 12:15:02 and closed at 13:40. Test data, not market data. */
const ENTERED: Signal = {
  id: "01a1d571-addf-7186-8d0e-a8cc456d6694",
  provider: "binance_usdm",
  strategy: "trend_break_baseline",
  instrument_id: 3,
  timeframe: "15m",
  action: "BUY",
  entry_type: "MARKET",
  state: "STOPPED",
  market_price: "91200",
  entry_price: "91200.0",
  stop_loss: "90800.0",
  targets: [{ price: "92000.0", allocation: "1", net_reward_risk: "2.1" }],
  quantity: "0.002",
  notional: "182.4",
  max_account_risk: "0.8",
  estimated_fees: "0.07",
  estimated_funding: "0",
  reward_risk_net: "2.1",
  risk_share: null,
  decision: "APPROVED",
  rejection_codes: [],
  setup_quality_score: "70",
  news_alignment: "neutral",
  data_reliability_score: "100",
  probability_status: "unavailable",
  technical_explanation: "BOS",
  fundamental_explanation: "",
  supporting_evidence: [],
  conflicting_evidence: [],
  invalidation_conditions: [],
  created_at: "2026-11-13T12:15:00Z",
  expires_at: "2026-11-13T12:45:00Z",
  data_as_of: "2026-11-13T12:15:00Z",
  trade: {
    state: "lost",
    opened_at: "2026-11-13T12:15:02Z",
    closed_at: "2026-11-13T13:40:00Z",
    entry_price: "91234.5",
    exit_price: "90800.1",
    net: "-0.8123",
  },
};

const STEP = 900; // 15M bars.
const at = (iso: string) => Date.parse(iso) / 1000;

describe("a trade on the Bot page's chart (D065)", () => {
  it("links only an entered trade, on its account, coin and the chart's nearest timeframe", () => {
    expect(chartHref({ ...ENTERED, trade: { ...ENTERED.trade!, state: "waiting", opened_at: null } }, "binance", "BTCUSDT")).toBeNull();
    expect(chartHref({ ...ENTERED, trade: null }, "binance", "BTCUSDT")).toBeNull();
    const href = chartHref({ ...ENTERED, timeframe: "1d" }, "binance_live", "BTCUSDT")!;
    const query = new URLSearchParams(href.split("?")[1]);
    expect(href.startsWith("/bot?")).toBe(true);
    expect(Object.fromEntries(query)).toEqual({
      account: "binance_live",
      signal: ENTERED.id,
      coin: "BTCUSDT",
      tf: "1h",
    });
    expect(chartTimeframe("15m")).toBe("15m");
    expect(chartTimeframe("4h")).toBe("1h");
  });

  it("reads a whole link from the address and ignores a broken one", () => {
    const good = new URLSearchParams({ account: "binance", signal: "s1", coin: "ETHUSDT", tf: "5m" });
    expect(readChartLink(good)).toEqual({ account: "binance", signalId: "s1", symbol: "ETHUSDT", timeframe: "5m" });
    expect(readChartLink(new URLSearchParams({ account: "binance", signal: "s1", coin: "ETHUSDT", tf: "1w" }))?.timeframe).toBe(
      "15m",
    );
    expect(readChartLink(new URLSearchParams({ account: "bank", signal: "s1", coin: "ETHUSDT" }))).toBeNull();
    expect(readChartLink(new URLSearchParams({ account: "binance", coin: "ETHUSDT" }))).toBeNull();
    expect(readChartLink(new URLSearchParams())).toBeNull();
  });

  it("takes the fills' times and prices, not the plan's", () => {
    const focus = focusOfSignal(ENTERED, "BTCUSDT", "binance_live")!;
    expect(focus).toMatchObject({
      symbol: "BTCUSDT",
      side: "BUY",
      account: "Binance real",
      openedAt: "2026-11-13T12:15:02Z",
      closedAt: "2026-11-13T13:40:00Z",
      entryPrice: "91234.5",
      exitPrice: "90800.1",
      net: "-0.8123",
      state: "lost",
    });
    expect(focusOfSignal({ ...ENTERED, trade: { ...ENTERED.trade!, opened_at: null } }, "BTCUSDT", "binance")).toBeNull();
  });

  it("turns a Results row into the same focus", () => {
    const trade: ClosedTrade = {
      symbol: "SOLUSDT",
      side: "SHORT",
      strategy: "daily_trend",
      opened_at: "2026-11-12T00:00:05Z",
      closed_at: "2026-11-12T09:30:00Z",
      size: "0.5",
      entry_price: "84.10",
      exit_price: "83.50",
      pnl: "0.30",
      fees: "0.04",
      funding: "0",
      net: "0.26",
      r: "0.26",
      won: true,
    };
    expect(focusOfTrade(trade, "Binance demo")).toMatchObject({ side: "SELL", state: "won", net: "0.26", account: "Binance demo" });
  });

  it("scrolls to the trade with room on both sides, an open one up to the newest bar", () => {
    const focus = focusOfSignal(ENTERED, "BTCUSDT", "binance")!;
    const { from, to } = focusRange(focus, STEP, at("2026-11-13T20:00:00Z"));
    expect(from).toBe(at("2026-11-13T12:15:00Z") - 20 * STEP);
    expect(to).toBe(at("2026-11-13T13:30:00Z") + 20 * STEP);
    const open = { ...focus, closedAt: null };
    expect(focusRange(open, STEP, at("2026-11-13T20:00:00Z")).to).toBe(at("2026-11-13T20:00:00Z") + 20 * STEP);
    const long = { ...focus, closedAt: "2026-11-18T12:15:00Z" }; // 480 bars: a quarter is more than 20.
    expect(focusRange(long, STEP, 0).to - at("2026-11-18T12:15:00Z")).toBe(120 * STEP);
  });

  it("marks the entry with its fill price and the exit with the result", () => {
    const [entry, exit] = focusMarkers(focusOfSignal(ENTERED, "BTCUSDT", "binance")!, STEP, "0.1");
    expect(entry).toMatchObject({ time: at("2026-11-13T12:15:00Z"), shape: "arrowUp", position: "belowBar", text: "BUY 91234.5" });
    expect(exit).toMatchObject({ time: at("2026-11-13T13:30:00Z"), shape: "circle", text: "LOST -0.81" });
    const open = focusMarkers({ ...focusOfSignal(ENTERED, "BTCUSDT", "binance")!, closedAt: null }, STEP, null);
    expect(open).toHaveLength(1);
  });

  it("draws each fill once: the focused entry replaces the orders list's arrow on that bar", () => {
    const focused = focusMarkers(focusOfSignal(ENTERED, "BTCUSDT", "binance")!, STEP, null);
    const arrow = { id: "o", time: focused[0]!.time, position: "belowBar", shape: "arrowUp", color: "#fff", text: "BUY" } as const;
    const other = { ...arrow, id: "p", time: (Number(arrow.time) - STEP) as typeof arrow.time };
    const merged = withFocus([other, arrow], focused);
    expect(merged.map((marker) => marker.id)).toEqual(["p", focused[0]!.id, focused[1]!.id]);
  });

  it("says what became of a trade, in USDT", () => {
    expect(tradeText("won", "1.2345")).toBe("Won +1.23 USDT");
    expect(tradeText("lost", "-0.8")).toBe("Lost -0.80 USDT");
    expect(tradeText("open", "0.42")).toBe("Open, +0.42 USDT now");
    expect(tradeText("open", null)).toBe("Open");
    expect(tradeText("not filled", null)).toBe("Not filled");
    expect(tradeText("refused", null)).toBe("Refused by Binance");
    expect([tradeTone("won", "1"), tradeTone("lost", "-1"), tradeTone("open", "-0.1"), tradeTone("waiting", null)]).toEqual([
      "text-good",
      "text-bad",
      "text-bad",
      "text-muted",
    ]);
  });
});
