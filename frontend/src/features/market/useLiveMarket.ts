import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiPost, type Ticket, type Timeframe } from "@/lib/api/client";
import { MarketSocket, type ConnectionState, type MarketEvent } from "@/lib/ws/market-socket";

import { candleKey } from "./queries";

export type LivePrice = { bid: string; ask: string; receivedAt: string };

export type LiveCandle = {
  openTime: string;
  open: string;
  high: string;
  low: string;
  close: string;
  isClosed: boolean;
};

type LiveValues = { key: string; price: LivePrice | null; candle: LiveCandle | null };

const WEBSOCKET_PORT = "8000";

function socketUrl(): string {
  const { protocol, hostname } = window.location;
  const scheme = protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${hostname}:${WEBSOCKET_PORT}/api/v1/ws`;
}

/** Live price and candle for one chart. Reconnection and refilling happen inside. */
export function useLiveMarket(provider: string, instrumentId: number, timeframe: Timeframe) {
  const client = useQueryClient();
  const key = `${provider}:${instrumentId}:${timeframe}`;
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [live, setLive] = useState<LiveValues>({ key, price: null, candle: null });

  useEffect(() => {
    const candleTopic = `market.candle:${provider}:${instrumentId}:${timeframe}`;
    const queryKey = candleKey(provider, instrumentId, timeframe);
    const merge = (change: Partial<LiveValues>) =>
      setLive((previous) => ({
        ...(previous.key === key ? previous : { key, price: null, candle: null }),
        ...change,
      }));

    const onEvent = (event: MarketEvent) => {
      const body = event.payload;
      if (event.event_type === "market.price") {
        merge({
          price: {
            bid: String(body.bid),
            ask: String(body.ask),
            receivedAt: String(body.received_at),
          },
        });
      } else if (event.event_type === "market.candle") {
        merge({
          candle: {
            openTime: String(body.open_time),
            open: String(body.open),
            high: String(body.high),
            low: String(body.low),
            close: String(body.close),
            isClosed: Boolean(body.is_closed),
          },
        });
        if (body.is_closed) {
          // The row committed before this event was sent, so history now contains it.
          void client.invalidateQueries({ queryKey });
        }
      }
    };

    const socket = new MarketSocket({
      url: socketUrl(),
      topics: [`market.price:${provider}:${instrumentId}`, candleTopic],
      getTicket: async () => (await apiPost<Ticket>("/api/v1/auth/ws-ticket")).ticket,
      onEvent,
      onResync: (topic) => {
        if (topic === candleTopic) {
          void client.invalidateQueries({ queryKey });
        }
      },
      onState: setConnection,
    });
    socket.start();
    return () => socket.stop();
  }, [client, key, provider, instrumentId, timeframe]);

  const current = live.key === key ? live : { price: null, candle: null };
  return { connection, price: current.price, candle: current.candle };
}
