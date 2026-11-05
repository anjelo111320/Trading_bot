import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  apiGet,
  apiPost,
  type AnalysisJob,
  type CandlePage,
  type ForecastView,
  type Timeframe,
} from "@/lib/api/client";

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

const JOB_KEY = ["forecast-analysis"];
const JOB_POLL_MS = 3_000;

/** The latest re-analysis. Polled every few seconds while Kronos is running. */
export function useAnalysisJob() {
  return useQuery({
    queryKey: JOB_KEY,
    queryFn: () => apiGet<AnalysisJob>("/api/v1/forecasts/analyse"),
    refetchInterval: (query) => (query.state.data?.state === "running" ? JOB_POLL_MS : false),
  });
}

export function useStartAnalysis() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { provider: string; instrument_id: number }) =>
      apiPost<AnalysisJob>("/api/v1/forecasts/analyse", body),
    onSuccess: (job) => client.setQueryData(JOB_KEY, job),
  });
}
