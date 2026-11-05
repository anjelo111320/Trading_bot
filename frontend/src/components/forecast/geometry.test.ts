import { describe, expect, it } from "vitest";

import {
  atrDistance,
  futureSlots,
  interpolateX,
  levelStyle,
  spreadLabels,
  visibleWindow,
} from "./geometry";

const HOUR = 3600;

describe("interpolateX", () => {
  const slots = [0, 4 * HOUR, 8 * HOUR];
  const xOf = (slot: number) => slot / HOUR; // One pixel per hour.

  it("reads a bar slot directly", () => {
    expect(interpolateX(4 * HOUR, slots, xOf)).toBe(4);
  });

  it("places an hourly point between two 4H bars", () => {
    expect(interpolateX(5 * HOUR, slots, xOf)).toBeCloseTo(5);
  });

  it("continues the last spacing past the last slot", () => {
    expect(interpolateX(10 * HOUR, slots, xOf)).toBeCloseTo(10);
  });

  it("has no position before the first slot or off screen", () => {
    expect(interpolateX(-1, slots, xOf)).toBeNull();
    expect(interpolateX(2 * HOUR, slots, (slot) => (slot === 0 ? null : 1))).toBeNull();
  });
});

describe("futureSlots", () => {
  it("adds one empty slot per bar up to the end", () => {
    expect(futureSlots(0, HOUR, 3 * HOUR)).toEqual([HOUR, 2 * HOUR, 3 * HOUR]);
    expect(futureSlots(5 * HOUR, HOUR, 5 * HOUR)).toEqual([]);
  });
});

describe("spreadLabels", () => {
  it("keeps every label at least a gap apart, in order, inside the pane", () => {
    const placed = spreadLabels([50, 52, 51, 200], 12, 0, 300);
    const sorted = [...placed].sort((a, b) => a - b);
    for (let i = 1; i < sorted.length; i += 1) {
      expect(sorted[i]! - sorted[i - 1]!).toBeGreaterThanOrEqual(12);
    }
    expect(placed[0]).toBeLessThan(placed[2]!);
    expect(placed[2]).toBeLessThan(placed[1]!);
    expect(placed[3]).toBe(200);
  });

  it("pushes labels back inside when they crowd the bottom", () => {
    const placed = spreadLabels([295, 298, 299], 10, 0, 300);
    expect(Math.max(...placed)).toBeLessThanOrEqual(300);
    expect(Math.min(...placed)).toBe(280);
  });
});

describe("levelStyle", () => {
  it("draws reaction levels solid and calculated ones broken", () => {
    expect(levelStyle("resistance")).toEqual({ dash: [], label: "resistance", structural: true });
    expect(levelStyle("atr_projection").dash.length).toBe(2);
    expect(levelStyle("something_new").label).toBe("something new");
  });
});

describe("visibleWindow", () => {
  it("shows history, the forecast span, then empty room for labels", () => {
    const asOf = 100 * HOUR - 0.001;
    const window = visibleWindow(asOf, 4, "1h");
    expect(window.from).toBe(99 * HOUR - 36 * HOUR);
    // The forecast ends at 104h; 36 + 5 bars of chart leave ceil(41 × 0.22) = 10 bars of room.
    expect(window.to).toBe(104 * HOUR + 10 * HOUR);
    expect(visibleWindow(asOf, 24, "1h").to).toBe(124 * HOUR + 27 * HOUR);
  });
});

describe("atrDistance", () => {
  it("signs the distance", () => {
    expect(atrDistance(102, 100, 2)).toBe("+1.00 ATR");
    expect(atrDistance(99, 100, 2)).toBe("−0.50 ATR");
  });
});
