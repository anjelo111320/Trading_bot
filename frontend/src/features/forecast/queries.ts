import { useQuery } from "@tanstack/react-query";

import { apiGet, type CandlePage, type ForecastView, type Timeframe } from "@/lib/api/client";

const REFRESH_MS = 60_000; // New closed candles and the plan's status arrive about once a minute.

export function useForecastView(provider: string, instrumentId: number) {
  return useQuery({
    queryKey: ["forecast-view", provider, instrumentId],
    queryFn: () => {
      const query = new URLSearchParams({ provider, instrument_id: String(instrumentId) });
      return apiGet<ForecastView>(`/api/v1/forecasts/latest?${query}`);
    },
    refetchInterval: REFRESH_MS,
    retry: false,
  });
}

/** The newest closed candles, refreshed so candles after the forecast appear as they close. */
export function useRecentCandles(provider: string, instrumentId: number, timeframe: Timeframe) {
  return useQuery({
    queryKey: ["recent-candles", provider, instrumentId, timeframe],
    queryFn: () => {
      const query = new URLSearchParams({
        provider,
        instrument_id: String(instrumentId),
        timeframe,
        limit: "500",
      });
      return apiGet<CandlePage>(`/api/v1/market/candles?${query}`);
    },
    refetchInterval: REFRESH_MS,
  });
}
