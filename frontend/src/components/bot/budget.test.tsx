// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AiBudget, ExitReviews } from "@/lib/api/client";

import { ClaudeAdvice } from "./ClaudeAdvice";
import { ClaudeBudgetPanel, limitProblem, spendLine, thousands } from "./ClaudeBudgetPanel";

/** Claude's daily limit and today's spend, as the API gives them (D062). Test data. */
const BUDGET: AiBudget = {
  daily_limit_usd: "0.5",
  ceiling_usd: "3",
  changed_at: "2026-11-13T04:00:00Z",
  spent_today_usd: "0.0023",
  calls_today: 12,
  input_tokens_today: 7050,
  output_tokens_today: 1791,
  reached: false,
  by_purpose: [],
};

const REVIEWS: ExitReviews = {
  shadow: true,
  model: "claude-haiku-5-5",
  asking: true,
  statuses: {},
  cost_usd: "0.0099",
  scored: 0,
  scored_not_hold: 0,
  mean_change_r: null,
  reviews: [],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Claude's daily limit (D062)", () => {
  it("says today's spend against the limit in one line", () => {
    expect(thousands(950)).toBe("950");
    expect(thousands(8841)).toBe("8.8k");
    expect(spendLine(BUDGET)).toBe("$0.0023 of $0.5 today, 12 calls, 8.8k tokens");
    expect(limitProblem("0.25", "3")).toBeNull();
    expect(limitProblem("0", "3")).toBeNull();
    expect(limitProblem("3.5", "3")).toMatch(/from \$0 to \$3/);
    expect(limitProblem("", "3")).toMatch(/from \$0 to \$3/);
  });

  it("shows on the Claude tab, and warns once it is reached", () => {
    render(<ClaudeAdvice data={REVIEWS} symbol="SOLUSDT" budget={BUDGET} />);
    expect(screen.getByText(/Claude's daily limit: \$0\.0023 of \$0\.5 today/)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    cleanup();
    render(<ClaudeAdvice data={REVIEWS} symbol="SOLUSDT" budget={{ ...BUDGET, reached: true }} />);
    expect(screen.getByRole("alert").textContent).toMatch(/Reached: not asked again until 00:00 UTC/);
  });

  it("saves a new limit from the Settings tab", async () => {
    const sent: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_path: string, init?: RequestInit) => {
        if (init?.method === "PUT") {
          sent.push(JSON.parse(String(init.body)));
          return new Response(JSON.stringify({ ...BUDGET, daily_limit_usd: "0.25" }), { status: 200 });
        }
        return new Response(JSON.stringify(BUDGET), { status: 200 });
      }),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ClaudeBudgetPanel />
      </QueryClientProvider>,
    );
    const input = await screen.findByLabelText("Claude's daily limit (USD)");
    fireEvent.change(input, { target: { value: "5" } });
    expect(screen.getByRole("alert").textContent).toMatch(/from \$0 to \$3/);
    expect((screen.getByRole("button", { name: "Save Claude's limit" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(input, { target: { value: "0.25" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Claude's limit" }));
    await waitFor(() => expect(screen.getByText("Saved: $0.25 a day.")).toBeTruthy());
    expect(sent).toEqual([{ daily_limit_usd: "0.25" }]);
  });
});
