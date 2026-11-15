import { useSyncExternalStore } from "react";

import type { ExchangeVenue } from "./queries";

/**
 * The Binance account last chosen on the Bot page, remembered in this browser only. The Signals
 * page opens on the same account (D065).
 */
const VENUE_KEY = "bot-venue";

function storedVenue(): ExchangeVenue | null {
  try {
    const stored = window.localStorage.getItem(VENUE_KEY);
    return stored === "live" || stored === "demo" ? stored : null;
  } catch {
    return null;
  }
}

function onStorage(changed: () => void): () => void {
  window.addEventListener("storage", changed);
  return () => window.removeEventListener("storage", changed);
}

export function useStoredVenue(): ExchangeVenue | null {
  return useSyncExternalStore(onStorage, storedVenue, () => null);
}

export function storeVenue(venue: ExchangeVenue): void {
  try {
    window.localStorage.setItem(VENUE_KEY, venue);
  } catch {
    // A private window may refuse storage; the choice then lasts for this visit only.
  }
}
