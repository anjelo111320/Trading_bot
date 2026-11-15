"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useId, useMemo } from "react";

import { AppNav } from "@/components/AppNav";
import { ACCOUNT_LABEL } from "@/components/bot/focus";
import { STRATEGY_NAMES, strategyLabel } from "@/components/bot/trades";
import { useInstruments } from "@/features/market/queries";
import { useSignals } from "@/features/trading/queries";
import { useStoredVenue } from "@/features/trading/venue";
import type { Instrument } from "@/lib/api/client";

import {
  apiFilters,
  cleared,
  DECISIONS,
  defaultAccount,
  filtersQuery,
  MONEY_NOTE,
  narrowed,
  type PageFilters,
  PERIODS,
  readFilters,
  RESULTS,
  SIDES,
  tally,
  tallyText,
} from "./filters";
import { type Coin, SignalsTable } from "./SignalsTable";

const PROVIDER = "binance_usdm";
// The most signals one view shows. The filters narrow which.
const LIMIT = 500;
const STRATEGIES: Record<string, string> = Object.fromEntries(STRATEGY_NAMES.map((name) => [name, strategyLabel(name)]));

function Choice<T extends string>({
  label,
  value,
  options,
  all,
  onChange,
}: {
  label: string;
  value: T | null;
  options: Record<T, string>;
  all?: string; // The choice that filters nothing, when there is one.
  onChange: (value: T | null) => void;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-xs text-muted">
        {label}
      </label>
      <select
        id={id}
        value={value ?? ""}
        onChange={(event) => onChange((event.target.value || null) as T | null)}
        className="min-h-9 rounded border border-line bg-panel px-2 text-sm text-ink"
      >
        {all ? <option value="">{all}</option> : null}
        {(Object.keys(options) as T[]).map((key) => (
          <option key={key} value={key}>
            {options[key]}
          </option>
        ))}
      </select>
    </div>
  );
}

function SignalsBrowser({ instruments }: { instruments: Instrument[] }) {
  const router = useRouter();
  const params = useSearchParams();
  const venue = useStoredVenue();
  const perpetuals = useMemo(
    () => instruments.filter((item) => item.provider === PROVIDER && item.instrument_type === "linear_perpetual"),
    [instruments],
  );
  const symbols = useMemo(() => perpetuals.map((item) => item.symbol), [perpetuals]);
  const ids = useMemo(() => new Map(perpetuals.map((item) => [item.symbol, item.id] as const)), [perpetuals]);
  const coins = useMemo(
    () => new Map(perpetuals.map((item) => [item.id, { symbol: item.symbol, tickSize: item.tick_size } as Coin] as const)),
    [perpetuals],
  );
  const coinOptions = useMemo(() => Object.fromEntries(symbols.map((symbol) => [symbol, symbol])), [symbols]);
  const filters = useMemo(() => readFilters(params, defaultAccount(venue), symbols), [params, venue, symbols]);
  const signals = useSignals(filters.account, LIMIT, apiFilters(filters, ids));
  // Each change replaces the address, so Back from the chart returns to these filters.
  const change = (next: PageFilters) => router.replace(`/signals?${filtersQuery(next)}`, { scroll: false });
  const rows = signals.data ?? [];
  const label = ACCOUNT_LABEL[filters.account];

  return (
    <>
      <section aria-label="Filters" className="flex flex-wrap items-end gap-3 rounded border border-line bg-panel p-3">
        <Choice
          label="Account"
          value={filters.account}
          options={ACCOUNT_LABEL}
          onChange={(account) => account && change({ ...filters, account })}
        />
        <Choice label="Coin" value={filters.coin} options={coinOptions} all="All coins" onChange={(coin) => change({ ...filters, coin })} />
        <Choice
          label="Strategy"
          value={filters.strategy}
          options={STRATEGIES}
          all="All strategies"
          onChange={(strategy) => change({ ...filters, strategy })}
        />
        <Choice label="Side" value={filters.side} options={SIDES} all="Buy and sell" onChange={(side) => change({ ...filters, side })} />
        <Choice
          label="Risk engine"
          value={filters.decision}
          options={DECISIONS}
          all="Approved and rejected"
          onChange={(decision) => change({ ...filters, decision })}
        />
        <Choice
          label="Result"
          value={filters.result}
          options={RESULTS}
          all="Any result"
          onChange={(result) => change({ ...filters, result })}
        />
        <Choice
          label="Period"
          value={filters.period}
          options={PERIODS}
          onChange={(period) => change({ ...filters, period: period ?? "all" })}
        />
        {narrowed(filters) ? (
          <button
            type="button"
            onClick={() => change(cleared(filters))}
            className="min-h-9 cursor-pointer rounded border border-line px-3 text-sm text-muted hover:text-ink"
          >
            Clear filters
          </button>
        ) : null}
        {signals.isPlaceholderData ? (
          <span role="status" className="min-h-9 py-2 text-xs text-muted">
            Updating…
          </span>
        ) : null}
      </section>

      {signals.isError ? (
        <p role="alert" className="text-sm text-bad">
          Signals could not be loaded.
        </p>
      ) : signals.isPending ? (
        <p className="text-sm text-muted">Loading signals…</p>
      ) : rows.length === 0 ? (
        <div className="space-y-2 rounded border border-line bg-panel p-3 text-sm text-muted">
          <p>
            {narrowed(filters)
              ? "No signal on this account matches these filters."
              : `No signals on ${label} yet. No trade is a normal outcome, and most candles produce none.`}
          </p>
          {narrowed(filters) ? (
            <button
              type="button"
              onClick={() => change(cleared(filters))}
              className="min-h-9 cursor-pointer rounded border border-line px-3 text-ink hover:border-ink"
            >
              Clear filters
            </button>
          ) : null}
        </div>
      ) : (
        <>
          <p className="text-sm">
            {tallyText(tally(rows), LIMIT)} <span className="text-muted">{MONEY_NOTE[filters.account]}</span>
          </p>
          <div className={signals.isPlaceholderData ? "opacity-60" : undefined}>
            <SignalsTable signals={rows} account={filters.account} accountLabel={label} coins={coins} />
          </div>
        </>
      )}
    </>
  );
}

/** Every signal of one account, filtered (D065). */
export function SignalsScreen() {
  const instruments = useInstruments();
  return (
    <div className="min-h-screen">
      <header className="border-b border-line px-4 py-2">
        <AppNav current="/signals" />
      </header>
      <main className="mx-auto max-w-7xl space-y-3 p-4">
        <h1 className="text-lg font-semibold">Signals</h1>
        <p className="text-sm text-muted">
          Every setup Python found on one account, what the risk engine decided, and what became of each trade,
          from Binance&apos;s own fills or the paper simulator&apos;s. Rejections are listed too, and no trade is a
          normal outcome. Chart opens an entered trade on the Bot page&apos;s chart. Analysis only, not financial
          advice.
        </p>
        {instruments.isError ? (
          <p role="alert" className="text-sm text-bad">
            The coins could not be loaded.
          </p>
        ) : instruments.data ? (
          <SignalsBrowser instruments={instruments.data} />
        ) : (
          <p className="text-sm text-muted">Loading…</p>
        )}
      </main>
    </div>
  );
}
