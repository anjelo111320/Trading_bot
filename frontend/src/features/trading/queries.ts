import { useQuery } from "@tanstack/react-query";

import {
  apiGet,
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

// The bot page's accounts poll faster, so a new fill shows on the chart within seconds.
const BOT_REFRESH_MS = 5_000;
const PAPER_REFRESH_MS = 15_000;

function refreshOf(account: AccountName): number {
  return account === "paper" ? PAPER_REFRESH_MS : BOT_REFRESH_MS;
}

export function useSignals(account: AccountName = "paper", limit = 50) {
  return useQuery({
    queryKey: ["signals", account, limit],
    queryFn: () => apiGet<Signal[]>(`/api/v1/signals?limit=${limit}&account=${account}`),
    refetchInterval: refreshOf(account),
  });
}

export function usePaperSummary(account: AccountName = "paper") {
  return useQuery({
    queryKey: ["paper-summary", account],
    queryFn: () => apiGet<PaperSummary>(`/api/v1/paper-trading/summary?account=${account}`),
    refetchInterval: refreshOf(account),
  });
}

export function usePositions(account: AccountName = "paper") {
  return useQuery({
    queryKey: ["paper-positions", account],
    queryFn: () => apiGet<Position[]>(`/api/v1/paper-trading/positions?limit=50&account=${account}`),
    refetchInterval: refreshOf(account),
  });
}

export function useTrades(account: AccountName) {
  return useQuery({
    queryKey: ["paper-trades", account],
    queryFn: () => apiGet<Trade[]>(`/api/v1/paper-trading/trades?limit=200&account=${account}`),
    refetchInterval: refreshOf(account),
  });
}

export function useNews() {
  return useQuery({
    queryKey: ["news"],
    queryFn: () => apiGet<NewsItem[]>("/api/v1/news?limit=50"),
    refetchInterval: 60_000,
  });
}
