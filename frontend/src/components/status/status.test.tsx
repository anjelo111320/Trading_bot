// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { FeedStatus } from "@/lib/api/client";

import { DataWarning, SyntheticBanner } from "./Banners";
import { DataQualityPanel } from "./DataQualityPanel";
import { PricePanel, isPriceCurrent } from "./PricePanel";

const NOW = Date.parse("2026-11-02T10:00:10Z");
const FRESH = { bid: "100.10000000", ask: "100.20000000", receivedAt: "2026-11-02T10:00:09Z" };
const OLD = { ...FRESH, receivedAt: "2026-11-02T10:00:00Z" };

const HEALTHY: FeedStatus = {
  provider: "binance_usdm",
  state: "HEALTHY",
  reasons: [],
  last_event_at: "2026-11-02T10:00:09Z",
  lag_seconds: 0.4,
  open_gaps: 0,
  clock_skew_ms: 12,
};

afterEach(cleanup);

describe("PricePanel", () => {
  it("shows a fresh price at tick precision", () => {
    render(<PricePanel price={FRESH} tickSize="0.1" now={NOW} isCurrentFeed />);
    expect(screen.getByText("100.1")).toBeTruthy();
    expect(screen.getByText(/^Live/)).toBeTruthy();
  });

  it("never presents an old price as current", () => {
    render(<PricePanel price={OLD} tickSize="0.1" now={NOW} isCurrentFeed />);
    expect(screen.getByText(/NOT CURRENT/)).toBeTruthy();
    expect(screen.queryByText(/^Live/)).toBeNull();
    expect(screen.getByText("100.1").className).toContain("line-through");
  });

  it("treats a fresh price on an unhealthy feed as not current", () => {
    expect(isPriceCurrent(FRESH, NOW, false)).toBe(false);
    expect(isPriceCurrent(FRESH, NOW, true)).toBe(true);
  });

  it("says so when there is no price", () => {
    render(<PricePanel price={null} tickSize="0.1" now={NOW} isCurrentFeed />);
    expect(screen.getByText("No live price.")).toBeTruthy();
  });
});

describe("banners", () => {
  it("warns when data is not current", () => {
    render(<DataWarning problem="Binance USD-M is STALE" />);
    expect(screen.getByRole("alert").textContent).toContain("Do not rely on the prices shown");
  });

  it("shows nothing when data is fine", () => {
    const { container } = render(<DataWarning problem={null} />);
    expect(container.textContent).toBe("");
  });

  it("labels synthetic data unmissably", () => {
    render(<SyntheticBanner visible />);
    expect(screen.getByRole("alert").textContent).toContain("SYNTHETIC DATA");
    expect(screen.getByRole("alert").textContent).toContain("not real market data");
  });
});

describe("DataQualityPanel", () => {
  it("shows state as text, with lag, gaps and skew", () => {
    render(<DataQualityPanel feeds={[HEALTHY]} />);
    expect(screen.getByText("HEALTHY")).toBeTruthy();
    expect(screen.getByText("0.4s")).toBeTruthy();
    expect(screen.getByText("12 ms")).toBeTruthy();
  });

  it("lists reasons for an unhealthy feed", () => {
    const stale: FeedStatus = { ...HEALTHY, state: "STALE", reasons: ["kline:3:1m: no data for 40s"] };
    render(<DataQualityPanel feeds={[stale]} />);
    expect(screen.getByText("STALE")).toBeTruthy();
    expect(screen.getByText("kline:3:1m: no data for 40s")).toBeTruthy();
  });

  it("warns when status cannot be read", () => {
    render(<DataQualityPanel feeds={undefined} />);
    expect(screen.getByRole("alert").textContent).toContain("unavailable");
  });
});
