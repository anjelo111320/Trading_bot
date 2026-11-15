import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiError,
  apiGet,
  apiPost,
  apiPut,
  type AiBudget,
  type Arming,
  type CloseRequest,
  type Limits,
  type LimitsUpdate,
  type ExchangeOrder,
  type ExchangeStatus,
  type ExitReviews,
  type NewsItem,
  type NewsSignal,
  type PaperSummary,
  type Results,
  type Position,
  type Scorecard,
  type Signal,
  type Trade,
} from "@/lib/api/client";

/**
 * The tested strategies' account, the demo bot's 100 USDT account (D044), or the money plan's
 * 1,000 USDT account (D045).
 */
export type AccountName = "paper" | "demo" | "portfolio";
/**
 * Signals also exist for the Binance demo account (D048) and the owner's real futures wallet
 * (D060), whose positions live on Binance.
 */
export type SignalAccount = AccountName | "binance" | "binance_live";

/** The Bot page's Binance accounts: the owner's real futures wallet (D060), or demo trading's test funds (D048). */
export type ExchangeVenue = "live" | "demo";

function exchangeApi(venue: ExchangeVenue): string {
  return `/api/v1/exchange-${venue}`;
}

/** A 404 means the account does not exist yet, as the real one before it is connected: asking again changes nothing. */
function retryUnlessMissing(count: number, error: Error): boolean {
  return !(error instanceof ApiError && error.status === 404) && count < 3;
}

// The bot page's accounts poll faster, so a new fill shows on the chart within seconds.
const BOT_REFRESH_MS = 5_000;
const PAPER_REFRESH_MS = 15_000;

function refreshOf(account: SignalAccount): number {
  return account === "paper" ? PAPER_REFRESH_MS : BOT_REFRESH_MS;
}

/** The Signals page's filters (D065), each optional; the API applies them. */
export type SignalFilters = {
  instrument_id?: number;
  strategy?: string;
  action?: "BUY" | "SELL";
  decision?: "APPROVED" | "REJECTED";
  result?: "entered" | "open" | "won" | "lost" | "waiting" | "not_entered";
  period?: "today" | "7d" | "30d" | "all";
};

// The Signals page reads up to 500 signals, so it refreshes less often than the Bot page.
const SIGNALS_PAGE_REFRESH_MS = 15_000;

export function useSignals(account: SignalAccount = "paper", limit = 50, filters?: SignalFilters) {
  const query = new URLSearchParams({ limit: String(limit), account });
  for (const [name, value] of Object.entries(filters ?? {})) {
    if (value !== undefined) query.set(name, String(value));
  }
  return useQuery({
    queryKey: ["signals", account, limit, filters ?? null],
    queryFn: () => apiGet<Signal[]>(`/api/v1/signals?${query}`),
    refetchInterval: filters ? SIGNALS_PAGE_REFRESH_MS : refreshOf(account),
    // On the Signals page a changed filter keeps the last rows, marked as updating, until the
    // new ones arrive. The Bot page never shows one account's signals under another.
    placeholderData: filters ? keepPreviousData : undefined,
  });
}

const SCORECARD_REFRESH_MS = 300_000;

/** Each coin's scorecard (D068), Python's numbers only. It changes slowly, so every 5 minutes. */
export function useScorecard() {
  return useQuery({
    queryKey: ["scorecard"],
    queryFn: () => apiGet<Scorecard>("/api/v1/coins/scorecard"),
    refetchInterval: SCORECARD_REFRESH_MS,
  });
}

/** One signal with its trade, for the Bot page's chart link (D065). */
export function useSignal(account: SignalAccount | null, id: string | null) {
  return useQuery({
    queryKey: ["signal", account, id],
    queryFn: () => apiGet<Signal>(`/api/v1/signals/${encodeURIComponent(id!)}?account=${account}`),
    enabled: Boolean(account && id),
    retry: retryUnlessMissing,
  });
}

export function usePaperSummary(account: AccountName = "paper", enabled = true) {
  return useQuery({
    queryKey: ["paper-summary", account],
    queryFn: () => apiGet<PaperSummary>(`/api/v1/paper-trading/summary?account=${account}`),
    refetchInterval: refreshOf(account),
    enabled,
  });
}

export function usePositions(account: AccountName = "paper") {
  return useQuery({
    queryKey: ["paper-positions", account],
    queryFn: () => apiGet<Position[]>(`/api/v1/paper-trading/positions?limit=50&account=${account}`),
    refetchInterval: refreshOf(account),
  });
}

export function useTrades(account: AccountName, enabled = true) {
  return useQuery({
    queryKey: ["paper-trades", account],
    queryFn: () => apiGet<Trade[]>(`/api/v1/paper-trading/trades?limit=200&account=${account}`),
    refetchInterval: refreshOf(account),
    enabled,
  });
}

/** What the quant worker last saved from a Binance account, about once a minute (D048). */
export function useExchangeStatus(venue: ExchangeVenue, enabled: boolean) {
  return useQuery({
    queryKey: ["exchange-status", venue],
    queryFn: () => apiGet<ExchangeStatus>(`${exchangeApi(venue)}/status`),
    refetchInterval: BOT_REFRESH_MS,
    enabled,
  });
}

export function useExchangeOrders(venue: ExchangeVenue, enabled: boolean) {
  return useQuery({
    queryKey: ["exchange-orders", venue],
    queryFn: () => apiGet<ExchangeOrder[]>(`${exchangeApi(venue)}/orders?limit=100`),
    refetchInterval: BOT_REFRESH_MS,
    retry: retryUnlessMissing,
    enabled,
  });
}

export type ResultsPeriod = "7d" | "30d" | "all";

/** A Binance account's completed trades and results (D057), rebuilt from Binance's own fills. */
export function useExchangeResults(venue: ExchangeVenue, period: ResultsPeriod, enabled: boolean) {
  return useQuery({
    queryKey: ["exchange-results", venue, period],
    queryFn: () => apiGet<Results>(`${exchangeApi(venue)}/results?period=${period}`),
    refetchInterval: 60_000,
    retry: retryUnlessMissing,
    enabled,
  });
}

function limitsKey(venue: ExchangeVenue) {
  return ["exchange-limits", venue];
}

/** A Binance account's limits now, with the ceilings no setting can pass (D058). */
export function useExchangeLimits(venue: ExchangeVenue, enabled: boolean) {
  return useQuery({
    queryKey: limitsKey(venue),
    queryFn: () => apiGet<Limits>(`${exchangeApi(venue)}/limits`),
    retry: retryUnlessMissing,
    enabled,
  });
}

/** Save new limits as a new version, used by the bot from its next close. */
export function useSaveLimits(venue: ExchangeVenue) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: LimitsUpdate) => apiPut<Limits>(`${exchangeApi(venue)}/limits`, body),
    onSuccess: (saved) => {
      client.setQueryData(limitsKey(venue), saved);
      void client.invalidateQueries({ queryKey: ["exchange-status", venue] });
    },
  });
}

/** True once the owner has armed the real account, so real money can trade (D060). */
export function useLiveArmed(): boolean {
  const live = useQuery({
    queryKey: ["live-armed"],
    queryFn: () => apiGet<ExchangeStatus>(`${exchangeApi("live")}/status`),
    refetchInterval: 60_000,
  });
  return live.data?.live?.armed === true;
}

/**
 * A Binance account's trading on or off (D063, D064). Off stops new trades at once. On the real
 * account, on needs the owner's password and a clean check of the key and the account; the API
 * refuses otherwise and says why.
 */
export function useSetArming(venue: ExchangeVenue) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { armed: boolean; password?: string }) =>
      apiPut<Arming>(`${exchangeApi(venue)}/arming`, body),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["exchange-status", venue] });
      void client.invalidateQueries({ queryKey: ["live-armed"] });
    },
  });
}

/** Closes asked from the dashboard, newest first, with what each did (D060). */
export function useCloseRequests(venue: ExchangeVenue, enabled: boolean) {
  return useQuery({
    queryKey: ["exchange-closes", venue],
    queryFn: () => apiGet<CloseRequest[]>(`${exchangeApi(venue)}/closes?limit=10`),
    refetchInterval: BOT_REFRESH_MS,
    retry: retryUnlessMissing,
    enabled,
  });
}

/**
 * Ask for the bot's trade on a coin to be closed now (D060). The page only asks: the quant
 * worker, which holds the key, closes it within seconds.
 */
export function useCloseTrade(venue: ExchangeVenue) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (symbol: string) =>
      apiPost<CloseRequest>(`${exchangeApi(venue)}/positions/${encodeURIComponent(symbol)}/close`),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["exchange-status", venue] });
      void client.invalidateQueries({ queryKey: ["exchange-closes", venue] });
    },
  });
}

/** Claude's daily cost limit for every call together, and today's spend against it (D062). */
export function useAiBudget(enabled: boolean) {
  return useQuery({
    queryKey: ["ai-budget"],
    queryFn: () => apiGet<AiBudget>("/api/v1/ai/budget"),
    refetchInterval: 60_000,
    enabled,
  });
}

/** A new daily limit for Claude, used from its next call. Logged by the API. */
export function useSaveAiBudget() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (dailyLimit: string) => apiPut<AiBudget>("/api/v1/ai/budget", { daily_limit_usd: dailyLimit }),
    onSuccess: (saved) => client.setQueryData(["ai-budget"], saved),
  });
}

/** Claude's exit advice, in shadow mode (D051). Reading it never calls Claude. */
export function useExitReviews(enabled: boolean) {
  return useQuery({
    queryKey: ["exit-reviews"],
    queryFn: () => apiGet<ExitReviews>("/api/v1/ai/exit-reviews?limit=50"),
    refetchInterval: BOT_REFRESH_MS,
    enabled,
  });
}

/** A coin's news reading now (D055): Python's sum of Claude's labels. Untested. */
export function useNewsSignal(instrumentId: number) {
  return useQuery({
    queryKey: ["news-signal", instrumentId],
    queryFn: () => apiGet<NewsSignal>(`/api/v1/news/signal?instrument_id=${instrumentId}`),
    refetchInterval: 60_000,
    enabled: instrumentId > 0,
  });
}

export function useNews() {
  return useQuery({
    queryKey: ["news"],
    queryFn: () => apiGet<NewsItem[]>("/api/v1/news?limit=50"),
    refetchInterval: 60_000,
  });
}
