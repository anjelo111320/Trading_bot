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
export type Position = Schemas["PositionView"];
export type PaperSummary = Schemas["PaperSummary"];
export type NewsItem = Schemas["NewsView"];

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
