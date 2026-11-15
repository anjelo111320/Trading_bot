"use client";

import { useState } from "react";

import { type ExchangeVenue, useExchangeLimits, useSaveLimits } from "@/features/trading/queries";
import { ApiError, type Limits } from "@/lib/api/client";
import { formatUtc } from "@/lib/format";

import { formOf, type LimitsForm, problems, twoLosses, updateOf } from "./limits";

type Field = { key: Exclude<keyof LimitsForm, "fromHigh">; label: string; unit: string; help: string };

function fields(limits: Limits): Field[] {
  const ceiling = (value: string) => `${Number(value) * 100}%`;
  return [
    { key: "risk", label: "Risk per trade", unit: "%", help: `What a losing trade costs, of equity. At most ${ceiling(limits.ceilings.risk_per_trade)}.` },
    { key: "openRisk", label: "Risk across open trades", unit: "%", help: `All open trades together at their stops. At most ${ceiling(limits.ceilings.open_risk)}.` },
    { key: "exposure", label: "All positions together", unit: "% of equity", help: `Trades too big are shrunk to fit. Above 100%, trades open at the leverage that lets them all fit the margin. At most ${ceiling(limits.ceilings.exposure)}.` },
    { key: "largestTrade", label: "Largest single trade", unit: "% of equity", help: "One trade bigger than this is shrunk to it, so others still fit. Blank for none." },
    { key: "oneDirection", label: "One direction", unit: "% of equity", help: "All longs together, or all shorts together, at most this. The coins move together, so a jump through the stops hits a whole side at once. Blank for none." },
    { key: "leverage", label: "Highest leverage", unit: "x", help: `The lowest that fits is used. At most ${limits.ceilings.leverage}x. It changes margin, not what a stop loses.` },
    { key: "dailyLoss", label: "Daily loss limit", unit: "%", help: `No new trades for the UTC day after this loss. At most ${ceiling(limits.ceilings.daily_loss)}.` },
    { key: "profitStop", label: "Daily profit stop", unit: "%", help: "No new trades for the UTC day after this gain. Blank for none." },
    { key: "lossStop", label: "Loss stop", unit: "%", help: "No new trades at all after this loss, until you save limits again. Blank for none." },
  ];
}

/**
 * A Binance account's limits, changed by the owner (D058): demo trading's, or the real
 * account's (D060), each with its own versions. Each save is a new, logged version.
 */
export function LimitsPanel({ venue = "demo" }: { venue?: ExchangeVenue }) {
  const limits = useExchangeLimits(venue, true);
  const save = useSaveLimits(venue);
  // Unsaved edits only; without any, the form shows the saved limits.
  const [draft, setDraft] = useState<LimitsForm | null>(null);
  const [saved, setSaved] = useState(false);
  const form = draft ?? (limits.data ? formOf(limits.data) : null);
  const live = venue === "live";
  const title = live ? "Real account limits" : "Binance demo limits";

  if (!limits.data || !form) {
    const missing = limits.error instanceof ApiError && limits.error.status === 404;
    return (
      <p className="rounded border border-line bg-panel p-3 text-sm text-muted">
        {missing
          ? "The real account is not connected yet. Its limits appear once the bot has seen USDT in your futures wallet."
          : limits.isError
            ? "The limits could not be loaded."
            : "Loading limits…"}
      </p>
    );
  }
  const current = limits.data;
  const found = problems(form, current);
  const change = (key: keyof LimitsForm, value: string | boolean) => {
    setSaved(false);
    setDraft({ ...form, [key]: value });
  };
  const error = save.error instanceof ApiError ? save.error.message : save.error ? "The limits could not be saved." : null;

  return (
    <section aria-label={title} className="rounded border border-line bg-panel p-3">
      <h2 className="mb-1 text-sm font-semibold">{title}</h2>
      <p className="mb-3 text-xs text-muted">
        Version {current.version}, saved {formatUtc(current.changed_at)}. Changes apply from the next close. Saving
        also restarts trading after the loss stop. {live ? "Real money: these limits trade your own USDT." : "Test funds."}
      </p>
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (found.length > 0) return;
          save.mutate(updateOf(form), {
            onSuccess: () => {
              setDraft(null);
              setSaved(true);
            },
          });
        }}
      >
        {fields(current).map((field) => (
          <label key={field.key} className="block text-sm">
            <span className="flex items-baseline justify-between gap-2">
              <span>{field.label}</span>
              <span className="flex items-center gap-1">
                <input
                  type="number"
                  inputMode="decimal"
                  step="any"
                  value={form[field.key]}
                  onChange={(event) => change(field.key, event.target.value)}
                  className="min-h-9 w-24 rounded border border-line bg-raised px-2 text-right tabular-nums text-ink"
                  aria-label={`${field.label} (${field.unit})`}
                />
                <span className="w-16 text-xs text-muted">{field.unit}</span>
              </span>
            </span>
            <span className="block text-xs text-muted">
              {field.help}
              {field.key === "risk" && twoLosses(form.risk)
                ? ` Two losing trades in a row cost ${twoLosses(form.risk)} of equity.`
                : ""}
            </span>
          </label>
        ))}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.fromHigh}
            onChange={(event) => change("fromHigh", event.target.checked)}
            className="h-4 w-4"
          />
          Measure the loss stop from the highest equity, so it rises with profits
        </label>
        {found.length > 0 ? (
          <ul role="alert" className="list-disc pl-5 text-xs text-warn">
            {found.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        ) : null}
        {error ? (
          <p role="alert" className="text-xs text-bad">
            {error}
          </p>
        ) : null}
        {saved ? <p className="text-xs text-good">Saved as version {current.version}.</p> : null}
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={found.length > 0 || save.isPending}
            className="min-h-9 cursor-pointer rounded border border-ink bg-raised px-3 text-sm font-semibold text-ink disabled:cursor-not-allowed disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : "Save limits"}
          </button>
          <button
            type="button"
            onClick={() => {
              setDraft(null);
              setSaved(false);
            }}
            className="min-h-9 cursor-pointer rounded border border-line px-3 text-sm text-muted hover:text-ink"
          >
            Undo changes
          </button>
        </div>
      </form>
      <p className="mt-3 text-xs text-muted">
        Higher risk means bigger losses as well as bigger wins. In your 2020 to 2025 backtests, 10% a trade
        nearly emptied the account along the way. The risk engine still decides every trade.
      </p>
    </section>
  );
}
