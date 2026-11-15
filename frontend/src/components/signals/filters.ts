/**
 * The Signals page's filters (D065). They live in the page's address, so a reload, a saved link
 * and the Back button from the chart all keep them. The API applies every filter; the page only
 * reads and writes the address.
 */

import { ACCOUNT_LABEL, tradeText } from "@/components/bot/focus";
import { STRATEGY_NAMES } from "@/components/bot/trades";
import type { ExchangeVenue, SignalAccount, SignalFilters } from "@/features/trading/queries";
import type { Signal } from "@/lib/api/client";

type Side = NonNullable<SignalFilters["action"]>;
type Decision = NonNullable<SignalFilters["decision"]>;
type Result = NonNullable<SignalFilters["result"]>;
type Period = NonNullable<SignalFilters["period"]>;

export type PageFilters = {
  account: SignalAccount;
  coin: string | null;
  strategy: string | null;
  side: Side | null;
  decision: Decision | null;
  result: Result | null;
  period: Period;
};

export const SIDES: Record<Side, string> = { BUY: "Buy", SELL: "Sell" };
export const DECISIONS: Record<Decision, string> = { APPROVED: "Approved", REJECTED: "Rejected" };
export const RESULTS: Record<Result, string> = {
  entered: "Entered a trade",
  open: "Open now",
  won: "Won",
  lost: "Lost",
  waiting: "Waiting to fill",
  not_entered: "Not entered",
};
export const PERIODS: Record<Period, string> = {
  all: "All time",
  today: "Today",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
};

/** Whose money a signal's result is, said beside every total. */
export const MONEY_NOTE: Record<SignalAccount, string> = {
  binance_live: "Real money in your Binance futures wallet.",
  binance: "Test funds on Binance demo trading.",
  portfolio: "Simulated, in a paper account.",
  demo: "Simulated, in a paper account.",
  paper: "Simulated, in a paper account.",
};

/** The account the page opens on: the one last chosen on the Bot page, else the real one. */
export function defaultAccount(venue: ExchangeVenue | null): SignalAccount {
  return venue === "demo" ? "binance" : "binance_live";
}

function oneOf<T extends string>(value: string | null, options: Record<T, string>): T | null {
  return value !== null && Object.hasOwn(options, value) ? (value as T) : null;
}

/** The filters in the page's address. Anything unknown there is ignored. */
export function readFilters(
  params: Pick<URLSearchParams, "get">,
  fallback: SignalAccount,
  coins: readonly string[],
): PageFilters {
  const coin = params.get("coin");
  const strategy = params.get("strategy");
  return {
    account: oneOf(params.get("account"), ACCOUNT_LABEL) ?? fallback,
    coin: coin && coins.includes(coin) ? coin : null,
    strategy: strategy && STRATEGY_NAMES.includes(strategy) ? strategy : null,
    side: oneOf(params.get("side"), SIDES),
    decision: oneOf(params.get("decision"), DECISIONS),
    result: oneOf(params.get("result"), RESULTS),
    period: oneOf(params.get("period"), PERIODS) ?? "all",
  };
}

/** The page's address for these filters, without the ones left unset. */
export function filtersQuery(filters: PageFilters): string {
  const query = new URLSearchParams({ account: filters.account });
  const optional: [string, string | null][] = [
    ["coin", filters.coin],
    ["strategy", filters.strategy],
    ["side", filters.side],
    ["decision", filters.decision],
    ["result", filters.result],
    ["period", filters.period === "all" ? null : filters.period],
  ];
  for (const [name, value] of optional) {
    if (value) query.set(name, value);
  }
  return query.toString();
}

/** True when anything but the account narrows the list. */
export function narrowed(filters: PageFilters): boolean {
  return Boolean(
    filters.coin || filters.strategy || filters.side || filters.decision || filters.result || filters.period !== "all",
  );
}

export function cleared(filters: PageFilters): PageFilters {
  return { account: filters.account, coin: null, strategy: null, side: null, decision: null, result: null, period: "all" };
}

/** What the API is asked for. A coin goes by its instrument ID. */
export function apiFilters(filters: PageFilters, ids: ReadonlyMap<string, number>): SignalFilters {
  const id = filters.coin ? ids.get(filters.coin) : undefined;
  return {
    ...(id !== undefined ? { instrument_id: id } : {}),
    ...(filters.strategy ? { strategy: filters.strategy } : {}),
    ...(filters.side ? { action: filters.side } : {}),
    ...(filters.decision ? { decision: filters.decision } : {}),
    ...(filters.result ? { result: filters.result } : {}),
    period: filters.period,
  };
}

const ENTERED = new Set(["open", "won", "lost", "even"]);
const CLOSED = new Set(["won", "lost", "even"]);

/** What became of a signal, in words. */
export function signalResult(signal: Signal): string {
  if (signal.trade) return tradeText(signal.trade.state, signal.trade.net ?? null);
  return signal.decision === "REJECTED" ? "Not traded" : "No entry sent";
}

export type Tally = {
  signals: number;
  entered: number;
  won: number;
  lost: number;
  even: number;
  open: number;
  net: number;
};

/** Totals over the signals shown: the closed trades' net after fees and funding. */
export function tally(signals: Signal[]): Tally {
  const totals: Tally = { signals: signals.length, entered: 0, won: 0, lost: 0, even: 0, open: 0, net: 0 };
  for (const signal of signals) {
    const state = signal.trade?.state;
    if (!state || !ENTERED.has(state)) continue;
    totals.entered += 1;
    if (state === "won") totals.won += 1;
    if (state === "lost") totals.lost += 1;
    if (state === "even") totals.even += 1;
    if (state === "open") totals.open += 1;
    if (CLOSED.has(state)) totals.net += Number(signal.trade?.net ?? 0);
  }
  return totals;
}

/** The totals in a sentence. */
export function tallyText(totals: Tally, limit: number): string {
  const shown =
    totals.signals >= limit
      ? `The newest ${limit} signals.`
      : `${totals.signals} signal${totals.signals === 1 ? "" : "s"}.`;
  if (totals.entered === 0) return `${shown} None entered a trade.`;
  const parts = [`${totals.won} won`, `${totals.lost} lost`];
  if (totals.even) parts.push(`${totals.even} even`);
  parts.push(`${totals.open} open`);
  const closed = totals.won + totals.lost + totals.even;
  const net = closed
    ? ` Closed trades made ${totals.net > 0 ? "+" : ""}${totals.net.toFixed(2)} USDT after fees and funding.`
    : "";
  return `${shown} ${totals.entered} entered a trade: ${parts.join(", ")}.${net}`;
}
