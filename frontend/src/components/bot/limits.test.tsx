// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Limits } from "@/lib/api/client";

import { formOf, problems, twoLosses, updateOf } from "./limits";
import { LimitsPanel } from "./LimitsPanel";

/** Binance demo's limits as the API gives them (D058). */
const LIMITS: Limits = {
  version: 4,
  changed_at: "2026-11-12T03:00:00Z",
  risk_per_trade: "0.1",
  open_risk: "0.1",
  exposure: "0.8",
  max_leverage: "3",
  daily_loss: "0.1",
  daily_profit_stop: "0.03",
  loss_stop: "0.2",
  loss_stop_from_high: false,
  ceilings: { risk_per_trade: "0.1", open_risk: "0.1", daily_loss: "0.1", leverage: "5", exposure: "5" },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Binance demo limits", () => {
  it("shows fractions as percentages and sends them back as fractions", () => {
    const form = formOf(LIMITS);
    expect(form).toMatchObject({ risk: "10", openRisk: "10", exposure: "80", profitStop: "3", lossStop: "20" });
    expect(updateOf({ ...form, profitStop: "", risk: "5" })).toEqual({
      risk_per_trade: "0.05",
      open_risk: "0.1",
      exposure: "0.8",
      largest_trade: null,
      one_direction: null,
      max_leverage: "3",
      daily_loss: "0.1",
      daily_profit_stop: null,
      loss_stop: "0.2",
      loss_stop_from_high: false,
    });
  });

  it("names every problem before saving", () => {
    const form = formOf(LIMITS);
    expect(problems(form, LIMITS)).toEqual([]);
    expect(problems({ ...form, risk: "12" }, LIMITS)[0]).toMatch(/at most 10%/);
    expect(problems({ ...form, risk: "5", openRisk: "4" }, LIMITS)[0]).toMatch(/at least the risk per trade/);
    expect(problems({ ...form, leverage: "2.5" }, LIMITS)[0]).toMatch(/whole number/);
    expect(problems({ ...form, lossStop: "100" }, LIMITS)[0]).toMatch(/between 0% and 100%/);
    expect(problems({ ...form, largestTrade: "90" }, LIMITS)[0]).toMatch(/at most all positions together/);
  });

  it("limits one trade to a share of equity, so others still fit (D061)", () => {
    const room = formOf({ ...LIMITS, exposure: "3", largest_trade: "1" });
    expect(room).toMatchObject({ exposure: "300", largestTrade: "100" });
    expect(problems(room, LIMITS)).toEqual([]);
    expect(updateOf(room)).toMatchObject({ exposure: "3", largest_trade: "1" });
    expect(updateOf({ ...room, largestTrade: " " }).largest_trade).toBeNull();
  });

  it("limits all longs or all shorts together to a share of equity (D072)", () => {
    const capped = formOf({ ...LIMITS, one_direction: "0.6" });
    expect(capped.oneDirection).toBe("60");
    expect(problems(capped, LIMITS)).toEqual([]);
    expect(updateOf(capped).one_direction).toBe("0.6");
    expect(updateOf({ ...capped, oneDirection: "" }).one_direction).toBeNull();
    expect(problems({ ...capped, oneDirection: "90" }, LIMITS)[0]).toMatch(/One direction must be/);
  });

  it("says what two losses in a row cost at a risk", () => {
    expect(twoLosses("10")).toBe("19.0%");
    expect(twoLosses("2")).toBe("4.0%");
    expect(twoLosses("")).toBe("");
  });

  it("saves new limits and shows the new version", async () => {
    const sent: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_path: string, init?: RequestInit) => {
        if (init?.method === "PUT") {
          sent.push(JSON.parse(String(init.body)));
          return new Response(JSON.stringify({ ...LIMITS, version: 5, risk_per_trade: "0.05" }), { status: 200 });
        }
        return new Response(JSON.stringify(LIMITS), { status: 200 });
      }),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <LimitsPanel />
      </QueryClientProvider>,
    );
    const risk = await screen.findByLabelText("Risk per trade (%)");
    expect(screen.getByText(/Two losing trades in a row cost 19.0% of equity/)).toBeTruthy();
    fireEvent.change(risk, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save limits" }));
    await waitFor(() => expect(screen.getByText("Saved as version 5.")).toBeTruthy());
    expect(sent).toEqual([expect.objectContaining({ risk_per_trade: "0.05" })]);
  });

  it("will not save limits past a ceiling", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(LIMITS), { status: 200 })));
    render(
      <QueryClientProvider client={new QueryClient()}>
        <LimitsPanel />
      </QueryClientProvider>,
    );
    fireEvent.change(await screen.findByLabelText("Risk per trade (%)"), { target: { value: "15" } });
    expect(screen.getByRole("alert").textContent).toMatch(/at most 10%/);
    expect((screen.getByRole("button", { name: "Save limits" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
