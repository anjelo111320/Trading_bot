"use client";

import { AppNav } from "@/components/AppNav";
import { useScorecard } from "@/features/trading/queries";
import { formatUtc } from "@/lib/format";

import { CoinsTable } from "./CoinsTable";

const ACCOUNT_LABEL = { binance_live: "Binance real", binance: "Binance demo" } as const;

/** Each coin's scorecard (D068): Python's numbers only, read-only. */
export function CoinsScreen() {
  const scorecard = useScorecard();
  const body = scorecard.data;
  return (
    <div className="min-h-screen">
      <header className="border-b border-line px-4 py-2">
        <AppNav current="/coins" />
      </header>
      <main className="mx-auto max-w-7xl space-y-3 p-4">
        <h1 className="text-lg font-semibold">Coins</h1>
        <p className="text-sm text-muted">
          Each coin&apos;s scorecard, worked out by Python alone. For every strategy it shows what the backtests found
          on that coin and what live trading has done since. It also shows how good the entries were: how far the
          price went against each trade in the hour after it filled, measured in R, the trade&apos;s planned risk.
          Analysis only, not financial advice.
        </p>
        {scorecard.isError ? (
          <p role="alert" className="text-sm text-bad">
            The scorecard could not be loaded.
          </p>
        ) : body ? (
          <>
            <CoinsTable coins={body.coins} />
            <p className="text-xs text-muted">
              Live trades are every paper account&apos;s and Binance&apos;s, with a setup traded on several accounts
              counted once. They are still few, so one coin&apos;s live result is mostly luck until it has dozens.
              Today&apos;s signals are {ACCOUNT_LABEL[body.account]}&apos;s, from 00:00 UTC. Worked out at{" "}
              {formatUtc(body.as_of)}.
            </p>
          </>
        ) : (
          <p className="text-sm text-muted">Loading…</p>
        )}
      </main>
    </div>
  );
}
