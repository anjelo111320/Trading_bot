"use client";

import { useState } from "react";

import { type ExchangeVenue, useCloseRequests, useCloseTrade } from "@/features/trading/queries";
import { ApiError } from "@/lib/api/client";

/**
 * Close the bot's trade on a coin now, from the dashboard (D060). Two clicks: ask, then
 * confirm. The page only asks; the quant worker, which holds the key, cancels a waiting entry,
 * closes the position at market and then cancels its stop and targets, within seconds.
 */
export function CloseTrade({
  venue,
  symbol,
  label,
  question,
  closing,
}: {
  venue: ExchangeVenue;
  symbol: string;
  label: string;
  question: string;
  closing: boolean;
}) {
  const close = useCloseTrade(venue);
  const [confirming, setConfirming] = useState(false);
  const [asked, setAsked] = useState(false);
  const closes = useCloseRequests(venue, asked);
  // The close asked here, once the quant worker has carried it out, so a failure says why.
  const failed = (closes.data ?? []).find((item) => item.id === close.data?.id && item.outcome === "failed");
  const refused = close.error instanceof ApiError ? close.error.message : close.error ? "The close could not be asked." : null;

  if (closing || close.isPending) {
    return (
      <p role="status" className="text-sm font-semibold text-warn">
        Closing {symbol} on Binance…
      </p>
    );
  }
  return (
    <div className="space-y-2">
      {confirming ? (
        <div className="space-y-2 rounded border border-warn p-2">
          <p className="text-sm">{question}</p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                setConfirming(false);
                setAsked(true);
                close.mutate(symbol);
              }}
              className="min-h-9 cursor-pointer rounded border border-bad bg-raised px-3 text-sm font-semibold text-bad"
            >
              Confirm: {label.toLowerCase()}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="min-h-9 cursor-pointer rounded border border-line px-3 text-sm text-muted hover:text-ink"
            >
              Keep it
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="min-h-9 cursor-pointer rounded border border-line px-3 text-sm font-semibold text-ink hover:border-bad"
        >
          {label}
        </button>
      )}
      {refused ? (
        <p role="alert" className="text-xs text-bad">
          {refused}
        </p>
      ) : null}
      {failed ? (
        <p role="alert" className="text-xs text-bad">
          The last close failed: {failed.detail ?? "Binance refused it"}. Its stop and targets are still on Binance.
        </p>
      ) : null}
    </div>
  );
}
