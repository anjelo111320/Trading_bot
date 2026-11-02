"use client";

import { AppNav } from "@/components/AppNav";
import { PaperAccount, PositionsTable } from "@/components/trading/PaperPanels";
import { usePaperSummary, usePositions } from "@/features/trading/queries";

export default function PaperPage() {
  const summary = usePaperSummary();
  const positions = usePositions();
  return (
    <div className="min-h-screen">
      <header className="border-b border-line px-4 py-2">
        <AppNav current="/paper" />
      </header>
      <main className="mx-auto max-w-5xl space-y-3 p-4">
        <h1 className="text-lg font-semibold">Paper trading</h1>
        {summary.isError ? <p role="alert" className="text-bad">The account could not be loaded.</p> : null}
        {summary.data ? <PaperAccount summary={summary.data} /> : null}
        {positions.data ? <PositionsTable positions={positions.data} /> : null}
      </main>
    </div>
  );
}
