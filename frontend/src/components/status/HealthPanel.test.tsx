// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Health } from "@/lib/api/client";

import { HealthPanel } from "./HealthPanel";

const ready: Health = {
  live: true,
  ready: true,
  trading_mode: "paper",
  checked_at: "2026-01-01T00:00:00Z",
  dependencies: [{ name: "database", ok: true, detail: null }],
};

afterEach(cleanup);

describe("HealthPanel", () => {
  it("shows readiness and the paper mode", () => {
    render(<HealthPanel health={ready} failed={false} />);
    expect(screen.getByText("All systems ready")).toBeTruthy();
    expect(screen.getByText("Mode: paper")).toBeTruthy();
  });

  it("names a failed dependency", () => {
    const degraded: Health = {
      ...ready,
      ready: false,
      dependencies: [{ name: "redis", ok: false, detail: "timed out" }],
    };
    render(<HealthPanel health={degraded} failed={false} />);
    expect(screen.getByText("Not ready")).toBeTruthy();
    expect(screen.getByText("timed out")).toBeTruthy();
  });

  it("warns when the backend cannot be reached", () => {
    render(<HealthPanel health={undefined} failed />);
    expect(screen.getByRole("alert").textContent).toContain("out of date");
  });
});
