// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ExchangeStatus } from "@/lib/api/client";

import { protection, waitingEntry } from "./binance";
import { BinanceAccount, BinancePosition } from "./BinancePanels";
import { CloseTrade } from "./CloseTrade";
import { LimitsPanel } from "./LimitsPanel";
import { TradingSwitch } from "./TradingSwitch";

/** The owner's real futures wallet as the quant worker saves it (D060). Test data, not market data. */
const LIVE: ExchangeStatus = {
  test_funds: false,
  connected: true,
  taken_at: "2026-11-13T10:00:05Z",
  age_seconds: 15,
  binance_equity: "151.15",
  binance_available: "9.25",
  capital: "150",
  equity: "151.15",
  day_start_equity: "150",
  available: "9.25",
  loss_floor: "120",
  loss_stopped_at: null,
  closing: [],
  armed: false,
  positions: [
    {
      symbol: "SOLUSDT",
      side: "SHORT",
      quantity: "0.5",
      entry_price: "84.10",
      mark_price: "83.80",
      notional: "41.90",
      margin: "14.00",
      unrealized: "0.15",
      liquidation: null,
      bot: true,
    },
    {
      symbol: "ETHUSDT",
      side: "SHORT",
      quantity: "0.1",
      entry_price: "3000",
      mark_price: "2990",
      notional: "299",
      margin: "100",
      unrealized: "1",
      liquidation: null,
      bot: false,
    },
  ],
  orders: [
    { symbol: "SOLUSDT", type: "STOP_MARKET", side: "BUY", trigger: "86.10", quantity: null, close_position: true, bot: true },
    { symbol: "ETHUSDT", type: "STOP_MARKET", side: "BUY", trigger: "3300", quantity: null, close_position: true, bot: false },
    { symbol: "XRPUSDT", type: "LIMIT", side: "BUY", trigger: "2.1", quantity: "10", close_position: false, bot: false },
  ],
  live: { armed: false, problems: [], ip_restricted: false },
};

function withQueries(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("the real account on the Bot page (D060)", () => {
  it("shows how to connect it until the bot has seen USDT in the futures wallet", () => {
    render(<BinanceAccount status={{ ...LIVE, connected: false, live: null }} venue="live" />);
    expect(screen.getByText("Binance real account")).toBeTruthy();
    expect(screen.getByText(/tick Enable Futures only/)).toBeTruthy();
    expect(screen.getByText(/BINANCE_LIVE_API_KEY/)).toBeTruthy();
  });

  it("shows what was put in, that it is not armed, and counts the owner's own positions apart", () => {
    render(<BinanceAccount status={LIVE} venue="live" />);
    expect(screen.getByText("Put in")).toBeTruthy();
    expect(screen.getByText("150.00 USDT")).toBeTruthy();
    expect(screen.getByText(/Not armed: no new trades/)).toBeTruthy();
    expect(screen.getByText("Your own positions")).toBeTruthy();
    expect(screen.getByText("41.90 USDT"), "only the bot's position is in its trades").toBeTruthy();
    expect(screen.getByText(/never Spot, Funding or the Overview/)).toBeTruthy();
    expect(screen.getByText(/not restricted to this computer's IP/)).toBeTruthy();
    expect(screen.queryByText(/Test funds on Binance/)).toBeNull();
  });

  it("raises every problem the hourly check found", () => {
    const refused = { ...LIVE, live: { armed: true, problems: ["the key can withdraw: turn it off"], ip_restricted: true } };
    render(<BinanceAccount status={refused} venue="live" />);
    expect(screen.getByRole("alert").textContent).toMatch(/The key can withdraw: turn it off\. No new trades/);
    expect(screen.getByText(/Armed: the bot opens trades/)).toBeTruthy();
  });

  it("keeps the owner's own orders apart from the bot's", () => {
    expect(protection(LIVE, "SOLUSDT").stop?.trigger).toBe("86.10");
    expect(protection(LIVE, "ETHUSDT").stop?.trigger).toBe("3300");
    expect(waitingEntry(LIVE, "XRPUSDT"), "the owner's resting order is not the bot's entry").toBeNull();
  });

  it("offers no close for the owner's own position", () => {
    render(
      <BinancePosition
        status={LIVE}
        position={LIVE.positions[1]!}
        tickSize="0.01"
        action={<button type="button">Close at market</button>}
      />,
    );
    expect(screen.getByText(/your own position/)).toBeTruthy();
    expect(screen.getByText(/close it in the Binance app/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Close at market" })).toBeNull();
  });

  it("closes the bot's trade only after it is confirmed", async () => {
    const sent: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          sent.push(path);
          return new Response(
            JSON.stringify({ id: "c1", symbol: "SOLUSDT", requested_at: "2026-11-13T10:01:00Z" }),
            { status: 202 },
          );
        }
        return new Response("[]", { status: 200 });
      }),
    );
    render(
      withQueries(
        <BinancePosition
          status={LIVE}
          position={LIVE.positions[0]!}
          tickSize="0.01"
          action={
            <CloseTrade venue="live" symbol="SOLUSDT" label="Close at market" question="Close it now?" closing={false} />
          }
        />,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Close at market" }));
    expect(sent, "the first click only asks").toEqual([]);
    expect(screen.getByText("Close it now?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(screen.queryByText("Close it now?")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Close at market" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm: close at market" }));
    await waitFor(() => expect(sent).toEqual(["/api/v1/exchange-live/positions/SOLUSDT/close"]));
  });

  it("says a close is under way, and why one was refused", async () => {
    render(withQueries(<CloseTrade venue="live" symbol="SOLUSDT" label="Close at market" question="?" closing />));
    expect(screen.getByRole("status").textContent).toBe("Closing SOLUSDT on Binance…");
    cleanup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_path: string, init?: RequestInit) =>
        init?.method === "POST"
          ? new Response(
              JSON.stringify({ error: { code: "not_found", message: "The bot has no open trade on SOLUSDT." } }),
              { status: 404 },
            )
          : new Response("[]", { status: 200 }),
      ),
    );
    render(withQueries(<CloseTrade venue="live" symbol="SOLUSDT" label="Close at market" question="?" closing={false} />));
    fireEvent.click(screen.getByRole("button", { name: "Close at market" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm: close at market" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The bot has no open trade on SOLUSDT.");
  });

  it("names the real account's limits, and says when it is not connected yet", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ error: { code: "not_found", message: "No account." } }), { status: 404 })),
    );
    render(withQueries(<LimitsPanel venue="live" />));
    expect(await screen.findByText(/The real account is not connected yet/)).toBeTruthy();
  });
});

describe("the real account's on/off switch (D063)", () => {
  function armingCalls(reply: { status: number; body: unknown }) {
    const sent: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_path: string, init?: RequestInit) => {
        if (init?.method === "PUT") {
          sent.push(JSON.parse(String(init.body)));
          return new Response(JSON.stringify(reply.body), { status: reply.status });
        }
        return new Response("{}", { status: 200 });
      }),
    );
    return sent;
  }

  it("turns on only with the password, after a confirm", async () => {
    const sent = armingCalls({ status: 200, body: { armed: true, armed_at: "2026-11-13T11:00:00Z" } });
    render(withQueries(<TradingSwitch venue="live" status={LIVE} />));
    const toggle = screen.getByRole("switch", { name: "Real trading" });
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getByText(/Turn real trading on\?/)).toBeTruthy();
    const turnOn = screen.getByRole("button", { name: "Turn on" }) as HTMLButtonElement;
    expect(turnOn.disabled, "no password yet").toBe(true);
    fireEvent.change(screen.getByLabelText("Your dashboard password"), { target: { value: "secret-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(sent).toEqual([{ armed: true, password: "secret-pass" }]));
  });

  it("turns off with a confirm and no password", async () => {
    const sent = armingCalls({ status: 200, body: { armed: false, armed_at: null } });
    const on = { ...LIVE, armed: true, live: { ...LIVE.live!, armed: true } };
    render(withQueries(<TradingSwitch venue="live" status={on} />));
    fireEvent.click(screen.getByRole("switch", { name: "Real trading" }));
    expect(screen.getByText(/Open trades keep their stops and targets on Binance/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(sent).toEqual([{ armed: false }]));
  });

  it("cannot be turned on while the check found a problem, and says why the API refused", async () => {
    const refused = { ...LIVE, live: { ...LIVE.live!, problems: ["the key can withdraw: turn it off"] } };
    render(withQueries(<TradingSwitch venue="live" status={refused} />));
    expect((screen.getByRole("switch", { name: "Real trading" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Fix the problems above on Binance first/)).toBeTruthy();
    cleanup();
    armingCalls({ status: 403, body: { error: { code: "forbidden", message: "The password is not right." } } });
    render(withQueries(<TradingSwitch venue="live" status={LIVE} />));
    fireEvent.click(screen.getByRole("switch", { name: "Real trading" }));
    fireEvent.change(screen.getByLabelText("Your dashboard password"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect((await screen.findByRole("alert")).textContent).toBe("The password is not right.");
  });
});

describe("demo trading's on/off switch (D064)", () => {
  it("turns off and on with a confirm and no password", async () => {
    const sent: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        if (init?.method === "PUT") sent.push([path, JSON.parse(String(init.body))]);
        return new Response(JSON.stringify({ armed: false, armed_at: null }), { status: 200 });
      }),
    );
    const demo = { ...LIVE, test_funds: true, armed: true, live: null };
    render(withQueries(<TradingSwitch venue="demo" status={demo} />));
    const toggle = screen.getByRole("switch", { name: "Demo trading" });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(toggle);
    fireEvent.click(screen.getByRole("button", { name: "Turn off" }));
    await waitFor(() => expect(sent).toEqual([["/api/v1/exchange-demo/arming", { armed: false }]]));
    cleanup();
    render(withQueries(<TradingSwitch venue="demo" status={{ ...demo, armed: false }} />));
    expect(screen.getByText(/the demo bot opens no new trades/)).toBeTruthy();
    fireEvent.click(screen.getByRole("switch", { name: "Demo trading" }));
    expect(screen.queryByLabelText("Your dashboard password"), "no password for test funds").toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toEqual(["/api/v1/exchange-demo/arming", { armed: true }]);
  });
});
