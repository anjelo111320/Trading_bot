// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ExitReview, ExitReviews } from "@/lib/api/client";

import { adviceLabel, ClaudeAdvice, scoreOf } from "./ClaudeAdvice";

/** Stored exit advice, as the API returns it. Test data, not market data. */
function review(overrides: Partial<ExitReview>): ExitReview {
  return {
    close_time: "2026-11-11T02:44:59.999Z",
    symbol: "SOLUSDT",
    strategy: "pattern_breakout",
    account: "Portfolio",
    checks: ["stall past +1R"],
    status: "advised",
    action: "take_profit_now",
    reason: "Stalled two hours below its best after a rejection.",
    progress_r: "1.235",
    model: "claude-haiku-5-5",
    tokens: 1320,
    cost_usd: "0.0001056",
    own_r: null,
    advised_r: null,
    ...overrides,
  };
}

function data(overrides: Partial<ExitReviews>): ExitReviews {
  return {
    shadow: true,
    model: "claude-haiku-5-5",
    asking: true,
    statuses: { advised: 2, not_asked: 1 },
    cost_usd: "0.0002",
    scored: 1,
    scored_not_hold: 1,
    mean_change_r: "2.240",
    reviews: [],
    ...overrides,
  };
}

afterEach(cleanup);

describe("Claude's exit advice on the Bot page", () => {
  it("names each answer, and why a check was not asked", () => {
    expect(adviceLabel(review({}))).toBe("Take the profit now");
    expect(adviceLabel(review({ status: "not_asked", action: null }))).toBe("Not asked: no API key yet");
    expect(adviceLabel(review({ status: "skipped_budget", action: null }))).toMatch(/daily budget/);
  });

  it("scores the advice only once the trade has finished", () => {
    expect(scoreOf(review({}))).toBeNull();
    expect(scoreOf(review({ own_r: "-1.140", advised_r: "1.100" }))).toBeCloseTo(2.24, 6);
  });

  it("is labelled shadow mode and shows the counts and the score", () => {
    const scored = review({ own_r: "-1.140", advised_r: "1.100" });
    render(<ClaudeAdvice data={data({ reviews: [review({ symbol: "XRPUSDT" }), scored] })} symbol="SOLUSDT" />);
    expect(screen.getByRole("note").textContent).toMatch(/never changes a trade/);
    expect(screen.getByText("Checks recorded").nextSibling?.textContent).toBe("3");
    expect(screen.getByText("Asked Claude").nextSibling?.textContent).toBe("2");
    expect(screen.getByText("+2.24R")).toBeTruthy();
    expect(screen.getByText(/Scored: the trade made -1.14R, with this advice \+1.10R/)).toBeTruthy();
    expect(screen.getByText(/Scored when the trade closes/)).toBeTruthy();
    // The coin on the chart comes first.
    expect(screen.getAllByText(/· Portfolio/)[0]!.textContent).toMatch(/SOLUSDT/);
  });

  it("says when no key is set, and when nothing has fired yet", () => {
    render(<ClaudeAdvice data={data({ asking: false, statuses: {}, reviews: [] })} symbol="SOLUSDT" />);
    expect(screen.getByText(/No Anthropic API key yet/)).toBeTruthy();
    expect(screen.getByText(/No check has fired yet/)).toBeTruthy();
  });
});
