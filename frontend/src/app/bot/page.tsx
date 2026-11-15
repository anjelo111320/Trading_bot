"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo } from "react";

import { BotScreen } from "@/components/bot/BotScreen";
import { readChartLink } from "@/components/bot/focus";
import { useInstruments, useOwner } from "@/features/market/queries";

function Loading() {
  return <p className="p-6 text-sm text-muted">Loading…</p>;
}

function Bot() {
  const router = useRouter();
  const params = useSearchParams();
  const owner = useOwner();
  const instruments = useInstruments();
  // A Signals page link names a trade to show on the chart (D065).
  const link = useMemo(() => readChartLink(params), [params]);

  useEffect(() => {
    if (owner.isError) {
      router.replace("/login");
    }
  }, [owner.isError, router]);

  if (!owner.data || !instruments.data) {
    return <Loading />;
  }
  // Each link opens the page afresh on its own coin and trade.
  return <BotScreen key={link?.signalId ?? "bot"} instruments={instruments.data} link={link} />;
}

export default function BotPage() {
  return (
    <Suspense fallback={<Loading />}>
      <Bot />
    </Suspense>
  );
}
