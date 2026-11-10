import { useQuery } from "@tanstack/react-query";

import {
  apiGet,
  type ExchangeOrder,
  type ExchangeStatus,
  type NewsItem,
  type PaperSummary,
  type Position,
  type Signal,
  type Trade,
} from "@/lib/api/client";

/**
 * The tested strategies' account, the demo bot's 100 USDT account (D044), or the money plan's
 * 1,000 USDT account (D045).
 */
export type AccountName = "paper" | "demo" | "portfolio";
/** Signals also exist for the Binance demo account (D048), whose positions live on Binance. */
export type SignalAccount = AccountName | "binance";

// The bot page's accounts poll faster, so a new fill shows on the chart within seconds.
const BOT_REFRESH_MS = 5_000;
const PAPER_REFRESH_MS = 15_000;

function refreshOf(account: SignalAccount): number {
  return account === "paper" ? PAPER_REFRESH_MS : BOT_REFRESH_MS;
}

export function useSignals(account: SignalAccount = "paper", limit = 50) {
  return useQuery({
    queryKey: ["signals", account, limit],
    queryFn: () => apiGet<Signal[]>(`/api/v1/signals?limit=${limit}&account=${account}`),
    refetchInterval: refreshOf(account),
  });
}

export function usePaperSummary(account: AccountName = "paper", enabled = true) {
  return useQuery({
    queryKey: ["paper-summary", account],
    queryFn: () => apiGet<PaperSummary>(`/api/v1/paper-trading/summary?account=${account}`),
    refetchInterval: refreshOf(account),
    enabled,
  });
}

export function usePositions(account: AccountName = "paper") {
  return useQuery({
    queryKey: ["paper-positions", account],
    queryFn: () => apiGet<Position[]>(`/api/v1/paper-trading/positions?limit=50&account=${account}`),
    refetchInterval: refreshOf(account),
  });
}

export function useTrades(account: AccountName, enabled = true) {
  return useQuery({
    queryKey: ["paper-trades", account],
    queryFn: () => apiGet<Trade[]>(`/api/v1/paper-trading/trades?limit=200&account=${account}`),
    refetchInterval: refreshOf(account),
    enabled,
  });
}

/** What the quant worker last saved from Binance demo trading, about once a minute (D048). */
export function useExchangeStatus(enabled: boolean) {
  return useQuery({
    queryKey: ["exchange-status"],
    queryFn: () => apiGet<ExchangeStatus>("/api/v1/exchange-demo/status"),
    refetchInterval: BOT_REFRESH_MS,
    enabled,
  });
}

export function useExchangeOrders(enabled: boolean) {
  return useQuery({
    queryKey: ["exchange-orders"],
    queryFn: () => apiGet<ExchangeOrder[]>("/api/v1/exchange-demo/orders?limit=100"),
    refetchInterval: BOT_REFRESH_MS,
    enabled,
  });
}

export function useNews() {
  return useQuery({
    queryKey: ["news"],
    queryFn: () => apiGet<NewsItem[]>("/api/v1/news?limit=50"),
    refetchInterval: 60_000,
  });
}
