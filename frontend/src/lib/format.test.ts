import { describe, expect, it } from "vitest";

import { formatAge, formatPrice, formatUtc } from "./format";

describe("formatPrice", () => {
  it("shows tick precision", () => {
    expect(formatPrice("78125.07000000", "0.01")).toBe("78125.07");
    expect(formatPrice("78094.400000000000000000", "0.1")).toBe("78094.4");
  });

  it("pads short values to tick precision", () => {
    expect(formatPrice("78125", "0.01")).toBe("78125.00");
  });

  it("handles a whole-number tick", () => {
    expect(formatPrice("78125.97", "1")).toBe("78125");
  });

  it("keeps digits a float would lose", () => {
    expect(formatPrice("90071992547409.93", "0.01")).toBe("90071992547409.93");
  });

  it("leaves the value alone when the tick is unknown", () => {
    expect(formatPrice("1.23456", null)).toBe("1.23456");
  });
});

describe("formatUtc", () => {
  it("states the zone", () => {
    expect(formatUtc("2026-11-02T09:18:05Z")).toBe("2026-11-02 09:18:05 UTC");
  });
});

describe("formatAge", () => {
  it("is explicit when the age is unknown", () => {
    expect(formatAge(null)).toBe("unknown");
  });

  it("uses seconds, then minutes", () => {
    expect(formatAge(2.34)).toBe("2.3s");
    expect(formatAge(125)).toBe("2m 5s");
  });
});
