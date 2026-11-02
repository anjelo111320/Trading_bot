"use client";

import { HealthPanel } from "@/components/status/HealthPanel";
import { useHealth } from "@/features/health/useHealth";

export default function HomePage() {
  const health = useHealth();
  return (
    <main className="mx-auto max-w-2xl p-6">
      <h1 className="mb-4 text-xl font-semibold">System status</h1>
      <HealthPanel health={health.data} failed={health.isError} />
    </main>
  );
}
