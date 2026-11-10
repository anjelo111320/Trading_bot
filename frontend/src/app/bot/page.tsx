"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { BotScreen } from "@/components/bot/BotScreen";
import { useInstruments, useOwner } from "@/features/market/queries";

export default function BotPage() {
  const router = useRouter();
  const owner = useOwner();
  const instruments = useInstruments();

  useEffect(() => {
    if (owner.isError) {
      router.replace("/login");
    }
  }, [owner.isError, router]);

  if (!owner.data || !instruments.data) {
    return <p className="p-6 text-sm text-muted">Loading…</p>;
  }
  return <BotScreen instruments={instruments.data} />;
}
