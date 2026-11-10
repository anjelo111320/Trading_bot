import type { components } from "./schema";

type Schemas = components["schemas"];

export type Health = Schemas["HealthResponse"];
export type Owner = Schemas["OwnerView"];
export type Instrument = Schemas["InstrumentView"];
export type Candle = Schemas["CandleView"];
export type CandlePage = Schemas["CandlePage"];
export type Price = Schemas["PriceView"];
export type FeedStatus = Schemas["FeedStatusView"];
export type MarketStatus = Schemas["MarketStatusView"];
export type Ticket = Schemas["TicketView"];
export type Timeframe = Schemas["Timeframe"];
export type Signal = Schemas["SignalView"];
export type SignalScore = Schemas["SignalScoreView"];
export type Position = Schemas["PositionView"];
export type PaperSummary = Schemas["PaperSummary"];
export type Trade = Schemas["TradeView"];
export type TradeFill = Schemas["FillView"];
export type NewsItem = Schemas["NewsView"];
export type ForecastView = Schemas["ForecastView"];
export type ForecastHorizon = Schemas["HorizonView"];
export type ForecastLevel = Schemas["LevelView"];
export type ForecastPlan = Schemas["PlanView"];
export type ForecastBand = Schemas["BandView"];
export type ForecastSpread = Schemas["SpreadView"];
export type ForecastProjection = Schemas["ProjectionView"];
export type ForecastStrategy = Schemas["StrategyView"];
export type ForecastKronos = Schemas["KronosView"];
export type ForecastProposal = Schemas["ProposalView"];
export type ChartPattern = Schemas["ChartPatternView"];
export type CandleSignal = Schemas["CandleSignalView"];
export type AnalysisJob = Schemas["AnalysisJobView"];
export type ExchangeStatus = Schemas["ExchangeStatusView"];
export type ExchangePosition = Schemas["ExchangePositionView"];
export type ExchangeOpenOrder = Schemas["ExchangeOpenOrderView"];
export type ExchangeOrder = Schemas["ExchangeOrderView"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      response.status,
      body?.error?.code ?? "http_error",
      body?.error?.message ?? `Request failed with status ${response.status}`,
    );
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export function apiGet<T>(path: string): Promise<T> {
  return send<T>(path);
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
  return send<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
