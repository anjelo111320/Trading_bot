import { useQuery } from "@tanstack/react-query";

import { apiGet, type PaperSummary, type Position, type Signal } from "@/lib/api/client";

export function useSignals() {
  return useQuery({
    queryKey: ["signals"],
    queryFn: () => apiGet<Signal[]>("/api/v1/signals?limit=50"),
    refetchInterval: 15_000,
  });
}

export function usePaperSummary() {
  return useQuery({
    queryKey: ["paper-summary"],
    queryFn: () => apiGet<PaperSummary>("/api/v1/paper-trading/summary"),
    refetchInterval: 15_000,
  });
}

export function usePositions() {
  return useQuery({
    queryKey: ["paper-positions"],
    queryFn: () => apiGet<Position[]>("/api/v1/paper-trading/positions?limit=50"),
    refetchInterval: 15_000,
  });
}
