// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CoinCard, Scorecard, StrategyCell } from "@/lib/api/client";

import { CoinsScreen } from "./CoinsScreen";
import { CoinsTable, againstText, enteredBadly, liveText } from "./CoinsTable";

const scorecard = vi.hoisted(() => ({ value: { data: undefined as unknown, isError: false } }));
vi.mock("@/features/trading/queries", () => ({
  useScorecard: () => scorecard.value,
  useLiveArmed: () => true,
}));
vi.mock("next/link", () => ({ default: ({ children }: { children: unknown }) => children }));

const NONE = { trades: 0, slippage_r: null, first_hour_r: null, went_against: 0 };
const NOTHING = { entered: 0, closed: 0, won: 0, mean_r: null };

/** Test data, not market data. */
function cell(strategy: string, overrides: Partial<StrategyCell> = {}): StrategyCell {
  return { strategy, evidence: null, untested: null, left_out: false, live: NOTHING, entries: NONE, ...overrides };
}

function coin(symbol: string, overrides: Partial<CoinCard> = {}): CoinCard {
  return {
    symbol,
    instrument_id: 1,
    live: NOTHING,
    entries: NONE,
    conditions: {
      atr_percent: "1.68",
      spread_bps: "0.2",
      open_gaps: 0,
      signals_today: 0,
      approved_today: 0,
      top_refusal: null,
    },
    strategies: [cell("daily_trend", { untested: "Not tested on this coin: it was added untested (D052, D059)." })],
    ...overrides,
  };
}

const PEPE = coin("1000PEPEUSDT", {
  live: { entered: 5, closed: 5, won: 0, mean_r: "-1" },
  entries: { trades: 5, slippage_r: "0.01", first_hour_r: "0.55", went_against: 3 },
  conditions: {
    atr_percent: "1.68",
    spread_bps: "0.2",
    open_gaps: 1,
    signals_today: 3,
    approved_today: 1,
    top_refusal: "RR_BELOW_MIN",
  },
  strategies: [
    cell("trend_break_baseline", {
      untested: "Never tested: it fills on 1-minute candles, and none exist before the holdout (docs/33).",
      live: { entered: 4, closed: 4, won: 0, mean_r: "-1" },
      entries: { trades: 4, slippage_r: "0", first_hour_r: "0.73", went_against: 3 },
    }),
  ],
});
const BTC = coin("BTCUSDT", {
  conditions: {
    atr_percent: "0.79",
    spread_bps: "0",
    open_gaps: 0,
    signals_today: 10,
    approved_today: 0,
    top_refusal: "QTY_BELOW_MIN",
  },
  live: { entered: 4, closed: 3, won: 3, mean_r: "2.8" },
  entries: { trades: 4, slippage_r: "-0.01", first_hour_r: "0.07", went_against: 0 },
  strategies: [
    cell("daily_trend", {
      evidence: { trades: 71, mean_r: "0.439", low: "-0.03", high: "0.98", source: "docs/33" },
      live: { entered: 1, closed: 0, won: 0, mean_r: null },
    }),
    cell("fvg_choch", { left_out: true }),
  ],
});

afterEach(cleanup);

describe("the coin scorecard", () => {
  it("says what traded, and flags entries that often went half their risk against", () => {
    expect(liveText(NOTHING)).toBe("No trades yet");
    expect(liveText({ entered: 4, closed: 3, won: 3, mean_r: "2.8" })).toBe("3 of 3 won, 1 open");
    expect(liveText({ entered: 2, closed: 0, won: 0, mean_r: null })).toBe("None closed, 2 open");
    expect(againstText(PEPE.entries)).toBe("3 of 5 went 0.5R against");
    expect(againstText(NONE)).toBe("–");
    expect(enteredBadly(PEPE.entries)).toBe(true);
    expect(enteredBadly(BTC.entries)).toBe(false);
    expect(enteredBadly({ trades: 2, slippage_r: "0", first_hour_r: "0.9", went_against: 2 })).toBe(false);
  });

  it("shows each coin, and opens to every strategy with what backs it", () => {
    render(<CoinsTable coins={[BTC, PEPE]} />);
    const pepe = screen.getByText("1000PEPEUSDT").closest("tr")!;
    expect(within(pepe).getByText("None")).toBeTruthy();
    expect(within(pepe).getByText("0 of 5 won")).toBeTruthy();
    expect(within(pepe).getByText("0.55R").className).toContain("text-warn");
    expect(within(pepe).getByText("1 data gap")).toBeTruthy();
    expect(within(pepe).getByText("most refused: RR_BELOW_MIN")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Every strategy on 1000PEPEUSDT" }));
    expect(screen.getByText(/Never tested: it fills on 1-minute candles/)).toBeTruthy();
    expect(screen.getByText("0.73R against, 3 of 4 went 0.5R against")).toBeTruthy();
    expect(within(screen.getByText("BTCUSDT").closest("tr")!).getByText("under 0.1 bp spread")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Every strategy on BTCUSDT" }));
    expect(screen.getByText("+0.44R a trade over 71 trades, 95% range -0.03R to +0.98R (docs/33)")).toBeTruthy();
    expect(screen.getByText("Switched off after its study")).toBeTruthy();
  });

  it("loads, then names the account today's signals come from", () => {
    scorecard.value = { data: undefined, isError: false };
    const { rerender } = render(<CoinsScreen />);
    expect(screen.getByText("Loading…")).toBeTruthy();
    const body: Scorecard = { as_of: "2026-11-14T14:42:30Z", account: "binance_live", coins: [BTC] };
    scorecard.value = { data: body, isError: false };
    rerender(<CoinsScreen />);
    expect(screen.getByText(/Today's signals are Binance real's/)).toBeTruthy();
    scorecard.value = { data: undefined, isError: true };
    rerender(<CoinsScreen />);
    expect(screen.getByRole("alert").textContent).toContain("could not be loaded");
  });
});
