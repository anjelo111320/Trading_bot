import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import {
  apiGet,
  type CandlePage,
  type Instrument,
  type MarketStatus,
  type Owner,
  type Timeframe,
} from "@/lib/api/client";

const PAGE_SIZE = 500;

export function useOwner() {
  return useQuery({
    queryKey: ["owner"],
    queryFn: () => apiGet<Owner>("/api/v1/auth/me"),
    retry: false,
  });
}

export function useInstruments() {
  return useQuery({
    queryKey: ["instruments"],
    queryFn: () => apiGet<Instrument[]>("/api/v1/instruments"),
    staleTime: 60_000,
  });
}

export function useMarketStatus() {
  return useQuery({
    queryKey: ["market-status"],
    queryFn: () => apiGet<MarketStatus>("/api/v1/market/status"),
    refetchInterval: 5_000,
    retry: false,
  });
}

export function candleKey(provider: string, instrumentId: number, timeframe: Timeframe) {
  return ["candles", provider, instrumentId, timeframe];
}

export function useCandles(provider: string, instrumentId: number, timeframe: Timeframe) {
  return useInfiniteQuery({
    queryKey: candleKey(provider, instrumentId, timeframe),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const query = new URLSearchParams({
        provider,
        instrument_id: String(instrumentId),
        timeframe,
        limit: String(PAGE_SIZE),
      });
      if (pageParam) {
        query.set("before", pageParam);
      }
      return apiGet<CandlePage>(`/api/v1/market/candles?${query}`);
    },
    getNextPageParam: (page) => page.next_before,
  });
}
