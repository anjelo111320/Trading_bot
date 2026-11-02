"use client";

import { AppNav } from "@/components/AppNav";
import { SignalCard } from "@/components/trading/SignalCard";
import { useSignals } from "@/features/trading/queries";

export default function SignalsPage() {
  const signals = useSignals();
  return (
    <div className="min-h-screen">
      <header className="border-b border-line px-4 py-2">
        <AppNav current="/signals" />
      </header>
      <main className="mx-auto max-w-4xl space-y-3 p-4">
        <h1 className="text-lg font-semibold">Signals</h1>
        <p className="text-sm text-muted">
          From the rule baseline, which has not shown an edge yet. Rejections are listed too. Analysis
          only, not financial advice.
        </p>
        {signals.isError ? <p role="alert" className="text-bad">Signals could not be loaded.</p> : null}
        {signals.data?.length === 0 ? (
          <p className="text-sm text-muted">
            No signals yet. No trade is a normal outcome, and most candles produce none.
          </p>
        ) : null}
        {signals.data?.map((signal) => <SignalCard key={signal.id} signal={signal} />)}
      </main>
    </div>
  );
}
