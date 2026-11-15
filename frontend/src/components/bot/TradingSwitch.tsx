"use client";

import { useState } from "react";

import { type ExchangeVenue, useSetArming } from "@/features/trading/queries";
import { ApiError, type ExchangeStatus } from "@/lib/api/client";

/**
 * A Binance account's on/off switch (D063, D064). Off stops new trades at once, and open trades
 * keep their stops and targets on Binance. On the real account, turning on asks for the
 * dashboard password, and the API turns it on only while the bot runs and its check of the
 * key and the account is clean. Demo trading's test funds need only a confirm.
 */
export function TradingSwitch({ venue, status }: { venue: ExchangeVenue; status: ExchangeStatus }) {
  const arming = useSetArming(venue);
  const [asking, setAsking] = useState(false);
  const [password, setPassword] = useState("");
  const live = venue === "live";
  const label = live ? "Real trading" : "Demo trading";
  const armed = status.armed;
  const problems = live ? (status.live?.problems ?? []) : [];
  const blocked = !armed && problems.length > 0;
  const refused = arming.error instanceof ApiError ? arming.error.message : arming.error ? "The switch could not be changed." : null;

  const done = () => {
    setAsking(false);
    setPassword("");
  };

  return (
    <div className="mt-3 space-y-2 rounded border border-line p-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">{label}</span>
        <button
          type="button"
          role="switch"
          aria-checked={armed}
          aria-label={label}
          disabled={blocked || arming.isPending}
          onClick={() => {
            arming.reset();
            setAsking(true);
          }}
          className={`min-h-9 min-w-24 cursor-pointer rounded border px-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
            armed ? "border-warn text-warn" : "border-line text-muted"
          }`}
        >
          {armed ? "On" : "Off"}
        </button>
      </div>
      {!armed && !live ? <p className="text-xs text-muted">Switched off: the demo bot opens no new trades.</p> : null}
      {blocked ? (
        <p className="text-xs text-muted">Fix the problems above on Binance first. The bot checks again every few minutes.</p>
      ) : null}
      {asking && armed ? (
        <div className="space-y-2">
          <p className="text-sm">
            Turn {live ? "real" : "demo"} trading off? The bot opens no new trades. Open trades keep their stops and
            targets on Binance, and you can still close them here.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => arming.mutate({ armed: false }, { onSuccess: done })}
              className="min-h-9 cursor-pointer rounded border border-ink bg-raised px-3 text-sm font-semibold text-ink"
            >
              Turn off
            </button>
            <button type="button" onClick={done} className="min-h-9 cursor-pointer rounded border border-line px-3 text-sm text-muted hover:text-ink">
              Keep it on
            </button>
          </div>
        </div>
      ) : null}
      {asking && !armed && !live ? (
        <div className="space-y-2">
          <p className="text-sm">Turn demo trading back on? The bot trades its test funds from its next signal.</p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => arming.mutate({ armed: true }, { onSuccess: done })}
              className="min-h-9 cursor-pointer rounded border border-ink bg-raised px-3 text-sm font-semibold text-ink"
            >
              Turn on
            </button>
            <button type="button" onClick={done} className="min-h-9 cursor-pointer rounded border border-line px-3 text-sm text-muted hover:text-ink">
              Cancel
            </button>
          </div>
        </div>
      ) : null}
      {asking && !armed && live ? (
        <form
          className="space-y-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (password) arming.mutate({ armed: true, password }, { onSuccess: done });
          }}
        >
          <p className="text-sm">
            Turn real trading on? From its next signal the bot opens real trades in your futures wallet, within the
            limits on the Settings tab. Every trade goes through the risk engine; real losses are possible.
          </p>
          <label className="block text-xs text-muted">
            Your dashboard password
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-1 block min-h-9 w-full rounded border border-line bg-raised px-2 text-sm text-ink"
            />
          </label>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={!password || arming.isPending}
              className="min-h-9 cursor-pointer rounded border border-warn bg-raised px-3 text-sm font-semibold text-warn disabled:cursor-not-allowed disabled:opacity-50"
            >
              {arming.isPending ? "Turning on…" : "Turn on"}
            </button>
            <button type="button" onClick={done} className="min-h-9 cursor-pointer rounded border border-line px-3 text-sm text-muted hover:text-ink">
              Cancel
            </button>
          </div>
        </form>
      ) : null}
      {refused ? (
        <p role="alert" className="text-xs text-bad">
          {refused}
        </p>
      ) : null}
    </div>
  );
}
