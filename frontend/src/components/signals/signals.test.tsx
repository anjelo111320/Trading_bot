// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Instrument, Signal } from "@/lib/api/client";

import { apiFilters, cleared, filtersQuery, readFilters, signalResult, tally, tallyText } from "./filters";
import { SignalsScreen } from "./SignalsScreen";
import { SignalsTable } from "./SignalsTable";

const navigation = vi.hoisted(() => ({ replace: vi.fn(), query: "" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navigation.replace, push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(navigation.query),
}));

/** Test data, not market data. */
function signal(id: string, overrides: Partial<Signal> = {}): Signal {
  return {
    id,
    provider: "binance_usdm",
    strategy: "trend_break_baseline",
    instrument_id: 1,
    timeframe: "15m",
    action: "BUY",
    entry_type: "MARKET",
    state: "ACTIVE",
    market_price: "91200",
    entry_price: "91200.00",
    stop_loss: "90800.00",
    targets: [
      { price: "92000.00", allocation: "0.5", net_reward_risk: "1.9" },
      { price: "92400.00", allocation: "0.5", net_reward_risk: "2.8" },
    ],
    quantity: "0.002",
    notional: "182.4",
    max_account_risk: "0.8",
    estimated_fees: "0.07",
    estimated_funding: "0",
    reward_risk_net: "2.34",
    risk_share: null,
    decision: "APPROVED",
    rejection_codes: [],
    setup_quality_score: "70",
    news_alignment: "neutral",
    data_reliability_score: "100",
    probability_status: "unavailable",
    technical_explanation: "BOS with both higher timeframes up",
    fundamental_explanation: "News was neutral.",
    supporting_evidence: [],
    conflicting_evidence: [],
    invalidation_conditions: ["close below 90800"],
    created_at: "2026-11-13T12:15:00Z",
    expires_at: "2026-11-13T12:45:00Z",
    data_as_of: "2026-11-13T12:15:00Z",
    trade: null,
    ...overrides,
  };
}

const WON = signal("won", {
  trade: {
    state: "won",
    opened_at: "2026-11-13T12:15:02Z",
    closed_at: "2026-11-13T14:00:00Z",
    entry_price: "91210.5",
    exit_price: "92200",
    net: "1.9512",
  },
});
const REJECTED = signal("rejected", {
  instrument_id: 2,
  action: "SELL",
  decision: "REJECTED",
  rejection_codes: ["EXPOSURE_EXCEEDED"],
  created_at: "2026-11-13T12:00:00Z",
});
const WAITING = signal("waiting", {
  entry_type: "LIMIT",
  trade: { state: "waiting", opened_at: null, closed_at: null, entry_price: null, exit_price: null, net: null },
});
const COINS = new Map([
  [1, { symbol: "BTCUSDT", tickSize: "0.1" }],
  [2, { symbol: "ETHUSDT", tickSize: "0.01" }],
]);

function withQueries(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  navigation.replace.mockReset();
  navigation.query = "";
});

describe("the Signals page's filters (D065)", () => {
  it("read from the address, ignoring anything unknown, and write back only what is set", () => {
    const params = new URLSearchParams(
      "account=binance&coin=ETHUSDT&strategy=daily_trend&side=SELL&decision=REJECTED&result=lost&period=7d",
    );
    const filters = readFilters(params, "binance_live", ["BTCUSDT", "ETHUSDT"]);
    expect(filters).toEqual({
      account: "binance",
      coin: "ETHUSDT",
      strategy: "daily_trend",
      side: "SELL",
      decision: "REJECTED",
      result: "lost",
      period: "7d",
    });
    expect(new URLSearchParams(filtersQuery(filters)).toString()).toBe(params.toString());
    const junk = new URLSearchParams("account=bank&coin=DOGE&strategy=x&side=HOLD&result=lucky&period=1y&toString=1");
    expect(readFilters(junk, "binance_live", ["BTCUSDT"])).toEqual(cleared({ ...filters, account: "binance_live" }));
    expect(filtersQuery(cleared(filters))).toBe("account=binance");
  });

  it("ask the API for a coin by its instrument ID", () => {
    const filters = readFilters(new URLSearchParams("coin=ETHUSDT&result=entered"), "binance", ["ETHUSDT"]);
    expect(apiFilters(filters, new Map([["ETHUSDT", 2]]))).toEqual({ instrument_id: 2, result: "entered", period: "all" });
  });

  it("total the trades shown, counting only closed ones in the net", () => {
    const lost = signal("lost", { trade: { ...WON.trade!, state: "lost", net: "-0.75" } });
    const open = signal("open", { trade: { ...WON.trade!, state: "open", closed_at: null, net: "0.40" } });
    const totals = tally([WON, lost, open, REJECTED, WAITING]);
    expect(totals).toMatchObject({ signals: 5, entered: 3, won: 1, lost: 1, open: 1, even: 0 });
    expect(totals.net).toBeCloseTo(1.2012);
    expect(tallyText(totals, 500)).toBe(
      "5 signals. 3 entered a trade: 1 won, 1 lost, 1 open. Closed trades made +1.20 USDT after fees and funding.",
    );
    expect(tallyText(tally([REJECTED]), 500)).toBe("1 signal. None entered a trade.");
    expect(tallyText(tally([REJECTED]), 1)).toBe("The newest 1 signals. None entered a trade.");
  });

  it("say what became of each signal", () => {
    expect(signalResult(WON)).toBe("Won +1.95 USDT");
    expect(signalResult(REJECTED)).toBe("Not traded");
    expect(signalResult(signal("unsent"))).toBe("No entry sent");
    expect(signalResult(WAITING)).toBe("Waiting to fill");
  });
});

describe("the Signals table (D065)", () => {
  it("links only an entered trade to the chart, on its account", () => {
    render(<SignalsTable signals={[WON, REJECTED, WAITING]} account="binance_live" accountLabel="Binance real" coins={COINS} />);
    const [link] = screen.getAllByRole("link", { name: /on the chart/ });
    expect(screen.getAllByRole("link", { name: /on the chart/ })).toHaveLength(1);
    expect(link!.getAttribute("href")).toBe(`/bot?account=binance_live&signal=won&coin=BTCUSDT&tf=15m`);
    expect(screen.getByText("Won +1.95 USDT")).toBeTruthy();
    expect(screen.getByText("filled 91210.5")).toBeTruthy();
    expect(screen.getByText("EXPOSURE_EXCEEDED")).toBeTruthy();
    // Prices at each coin's own tick: BTC to 0.1 on two rows, ETH to 0.01.
    expect(screen.getAllByText("92000.0 / 92400.0")).toHaveLength(2);
    expect(screen.getByText("92000.00 / 92400.00")).toBeTruthy();
  });

  it("opens a row to everything the risk engine weighed", () => {
    render(<SignalsTable signals={[WON]} account="binance" accountLabel="Binance demo" coins={COINS} />);
    expect(screen.queryByText("BOS with both higher timeframes up")).toBeNull();
    const toggle = screen.getByRole("button", { name: /Details of the BUY BTCUSDT signal/ });
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("BOS with both higher timeframes up")).toBeTruthy();
    expect(screen.getByText("Unavailable")).toBeTruthy(); // Never a win chance.
  });
});

describe("the Signals page (D065)", () => {
  const instruments: Instrument[] = [
    { id: 1, provider: "binance_usdm", symbol: "BTCUSDT", instrument_type: "linear_perpetual", tick_size: "0.1" },
    { id: 2, provider: "binance_usdm", symbol: "ETHUSDT", instrument_type: "linear_perpetual", tick_size: "0.01" },
  ] as Instrument[];
  let asked: string[];

  beforeEach(() => {
    asked = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string) => {
        if (path.startsWith("/api/v1/instruments")) return new Response(JSON.stringify(instruments));
        asked.push(path);
        return new Response(JSON.stringify(path.includes("result=won") ? [WON] : [WON, REJECTED]));
      }),
    );
  });

  it("opens on the real account and asks the API with the address's filters", async () => {
    navigation.query = "coin=ETHUSDT&result=won";
    render(withQueries(<SignalsScreen />));
    expect(await screen.findByText(/1 signal\. 1 entered a trade/)).toBeTruthy();
    const query = new URLSearchParams(asked.at(-1)!.split("?")[1]);
    expect(Object.fromEntries(query)).toMatchObject({
      account: "binance_live",
      instrument_id: "2",
      result: "won",
      period: "all",
      limit: "500",
    });
    expect(screen.getByText("Real money in your Binance futures wallet.")).toBeTruthy();
  });

  it("keeps a changed filter in the address, so Back from the chart returns to it", async () => {
    render(withQueries(<SignalsScreen />));
    const filters = await screen.findByRole("region", { name: "Filters" });
    fireEvent.change(within(filters).getByLabelText("Side"), { target: { value: "SELL" } });
    expect(navigation.replace).toHaveBeenCalledWith("/signals?account=binance_live&side=SELL", { scroll: false });
    fireEvent.change(within(filters).getByLabelText("Account"), { target: { value: "binance" } });
    expect(navigation.replace).toHaveBeenLastCalledWith("/signals?account=binance", { scroll: false });
  });
});
