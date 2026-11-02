/** Display helpers. Prices stay strings, so no value passes through float rounding. */

function decimalsOf(tickSize: string): number {
  const fraction = tickSize.split(".")[1] ?? "";
  return fraction.replace(/0+$/, "").length;
}

/** Show a price at tick precision by cutting the string, never by parsing it. */
export function formatPrice(value: string, tickSize: string | null | undefined): string {
  if (!tickSize) {
    return value;
  }
  const decimals = decimalsOf(tickSize);
  const [whole = "0", fraction = ""] = value.split(".");
  if (decimals === 0) {
    return whole;
  }
  return `${whole}.${fraction.padEnd(decimals, "0").slice(0, decimals)}`;
}

/** Times are always UTC, and always say so. */
export function formatUtc(iso: string): string {
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)} UTC`;
}

export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) {
    return "unknown";
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}
