import { useQuery } from "@tanstack/react-query";

import { apiGet, type Health } from "@/lib/api/client";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet<Health>("/api/v1/health"),
    refetchInterval: 5_000,
    retry: false,
  });
}
