// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { NewsItem, PaperSummary, Position, Signal } from "@/lib/api/client";

import { NewsCard } from "./NewsCard";
import { PaperAccount, PositionsTable } from "./PaperPanels";
import { SignalCard } from "./SignalCard";

const SIGNAL: Signal = {
  id: "1",
  provider: "binance_usdm",
  strategy: "trend_break_baseline",
  instrument_id: 3,
  timeframe: "15m",
  action: "BUY",
  entry_type: "MARKET",
  state: "ACTIVE",
  market_price: "100",
  entry_price: "100.00",
  stop_loss: "98.00",
  targets: [{ price: "104.00", allocation: "1", net_reward_risk: "1.646" }],
  quantity: "43.70",
  notional: "4371",
  max_account_risk: "99.98",
  estimated_fees: "0.19",
  estimated_funding: "0",
  reward_risk_net: "2.257",
  risk_share: null,
  decision: "APPROVED",
  rejection_codes: [],
  setup_quality_score: "72",
  news_alignment: "unavailable",
  data_reliability_score: "100",
  probability_status: "unavailable",
  technical_explanation: "BOS with both higher timeframes up",
  fundamental_explanation: "News is not used by the rule baseline.",
  supporting_evidence: [],
  conflicting_evidence: [],
  invalidation_conditions: ["close below 98.00"],
  created_at: "2026-11-02T10:00:00Z",
  expires_at: "2026-11-02T12:00:00Z",
  data_as_of: "2026-11-02T10:00:00Z",
};

const SUMMARY: PaperSummary = {
  simulated: true,
  account: "paper",
  starting_balance: "10000",
  equity: "10000",
  open_positions: 0,
  resolved_trades: 0,
  wins: 0,
  losses: 0,
  unfilled: 0,
  net_pnl: "0",
  costs: "0",
  win_rate: null,
  expectancy_r: null,
  day_start_equity: "10000",
  open_risk: "0",
  max_open_risk: null,
  daily_profit_stop: null,
};

afterEach(cleanup);

describe("SignalCard", () => {
  it("keeps quality, news, data and probability separate", () => {
    render(<SignalCard signal={SIGNAL} />);
    expect(screen.getByText("Technical setup quality")).toBeTruthy();
    expect(screen.getByText("News alignment")).toBeTruthy();
    expect(screen.getByText("Data reliability")).toBeTruthy();
    expect(screen.getByText("Probability of success")).toBeTruthy();
  });

  it("never shows a quality score as a probability", () => {
    render(<SignalCard signal={SIGNAL} />);
    expect(screen.getByText("Unavailable")).toBeTruthy();
    expect(screen.queryByText(/72%/)).toBeNull();
  });

  it("shows direction as text as well as colour", () => {
    render(<SignalCard signal={SIGNAL} />);
    expect(screen.getByRole("heading").textContent).toContain("BUY");
  });

  it("shows why the risk engine rejected a signal", () => {
    render(
      <SignalCard
        signal={{ ...SIGNAL, decision: "REJECTED", rejection_codes: ["RR_BELOW_MIN"], state: "REJECTED" }}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain("RR_BELOW_MIN");
  });

  it("does not invent a target when none exists", () => {
    render(<SignalCard signal={{ ...SIGNAL, targets: [] }} />);
    expect(screen.getAllByText("Not available").length).toBeGreaterThan(0);
  });
});

describe("paper trading", () => {
  it("labels results as simulated and shows no made-up statistics", () => {
    render(<PaperAccount summary={SUMMARY} />);
    expect(screen.getByText("Simulated equity")).toBeTruthy();
    expect(screen.getAllByText("No resolved trades")).toHaveLength(2);
    expect(screen.getByRole("region").textContent).toContain("not proof of future performance");
  });

  it("says when there are no positions", () => {
    render(<PositionsTable positions={[]} />);
    expect(screen.getByText("No simulated positions yet.")).toBeTruthy();
  });

  it("flags reconstructed fills", () => {
    const position: Position = {
      id: "1",
      symbol: "BTCUSDT",
      side: "LONG",
      status: "closed",
      planned_quantity: "0.1",
      open_quantity: "0",
      average_entry: "100",
      stop_loss: "98",
      realized_pnl: "5",
      costs_paid: "1",
      opened_at: "2026-11-02T10:00:00Z",
      closed_at: "2026-11-02T11:00:00Z",
      signal_state: "TP3_HIT",
      reconstructed: true,
    };
    render(<PositionsTable positions={[position]} />);
    expect(screen.getByText(/reconstructed/)).toBeTruthy();
  });
});

describe("NewsCard", () => {
  const item: NewsItem = {
    id: "1",
    headline: "<img src=x onerror=alert(1)> Fed holds rates",
    source: "Federal Reserve Board",
    credibility_tier: "official",
    url: "javascript:alert(1)",
    published_at: "2026-10-28T18:00:00Z",
    retrieved_at: "2026-11-02T10:00:00Z",
    relevance: "0.4",
    event_type: null,
    sentiment: null,
    potential_impact: null,
    certainty: null,
    possibly_misleading: null,
    ai_summary: null,
    classified: false,
  };

  it("shows hostile text as text, not markup", () => {
    const { container } = render(<NewsCard item={item} />);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByRole("heading").textContent).toContain("onerror");
  });

  it("refuses to link to anything but https", () => {
    const { container } = render(<NewsCard item={item} />);
    expect(container.querySelector("a")).toBeNull();
  });

  it("keeps publication and retrieval times separate", () => {
    const { container } = render(<NewsCard item={{ ...item, url: "https://example.test" }} />);
    expect(container.textContent).toContain("Published 2026-10-28 18:00:00 UTC");
    expect(container.textContent).toContain("Retrieved 2026-11-02 10:00:00 UTC");
  });

  it("says when an item has not been classified", () => {
    render(<NewsCard item={item} />);
    expect(screen.getByText("Not classified.")).toBeTruthy();
  });
});
