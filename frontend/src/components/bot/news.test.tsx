// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { NewsSignal } from "@/lib/api/client";

import { NewsSignalCard } from "./BotPanels";
import { newsText } from "./trades";

/** A news reading as the API gives it (D055). Test data, not market data. */
const BEARISH: NewsSignal = {
  untested: true,
  instrument_id: 3,
  at: "2026-11-11T12:15:00Z",
  rule_version: 1,
  direction: "bearish",
  score: "-1.8",
  threshold: "1.5",
  window_hours: 12,
  stories: [
    {
      headline: "Bitcoin ETFs shed $1.3B in biggest weekly outflow since late June",
      published_at: "2026-11-11T09:00:00Z",
      sentiment: "bearish",
      impact: "medium",
      relevance: "0.9",
      weight: "-1.8",
    },
  ],
};

afterEach(cleanup);

describe("news signal", () => {
  it("shows the reading, its stories and that it is untested", () => {
    render(<NewsSignalCard reading={BEARISH} symbol="BTCUSDT" />);
    expect(screen.getByText(/Bearish, score -1.8/)).toBeTruthy();
    expect(screen.getByText(/needs 1.5 either way/)).toBeTruthy();
    expect(screen.getByText(/1 labelled story in the last 12 hours/)).toBeTruthy();
    expect(screen.getByText(/Bitcoin ETFs shed/)).toBeTruthy();
    expect(screen.getByText(/Untested\..*never changes a trade/)).toBeTruthy();
  });

  it("says so when there is no news about the coin", () => {
    render(<NewsSignalCard reading={{ ...BEARISH, direction: "neutral", score: "0", stories: [] }} symbol="ZECUSDT" />);
    expect(screen.getByText(/Neutral, score 0.0/)).toBeTruthy();
    expect(screen.getByText(/No labelled stories about ZECUSDT in the last 12 hours/)).toBeTruthy();
  });

  it("names what the news said beside a signal, and nothing for signals never checked", () => {
    expect(newsText("aligned")).toBe("News agreed with this trade");
    expect(newsText("conflicting")).toBe("News was against this trade");
    expect(newsText("neutral")).toBe("News was neutral");
    expect(newsText("unavailable")).toBeNull();
    expect(newsText(null)).toBeNull();
  });
});
