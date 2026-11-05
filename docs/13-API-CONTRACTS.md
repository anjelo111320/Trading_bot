# API Contracts

## REST Groups
- /api/v1/auth
- /api/v1/instruments
- /api/v1/market
- /api/v1/analysis
- /api/v1/news
- /api/v1/signals
- /api/v1/risk
- /api/v1/paper-trading
- /api/v1/backtests
- /api/v1/settings
- /api/v1/health

## WebSocket Events
- market.price
- market.candle
- market.status
- analysis.updated
- signal.created
- signal.updated
- signal.invalidated
- paper.position.updated
- news.received
- system.alert

## Rules
Use Pydantic request and response models.
Version public APIs.
Validate all inputs.
Use consistent error structures.
Implement authentication and authorization.
Document rate limits.
Never expose provider credentials.
Publish OpenAPI documentation.

## Common Rules

Status: Implemented for Phases 0 and 1. The OpenAPI file is `backend/openapi.json`, and the frontend's types are generated from it.

- Money, prices and quantities are strings on the wire, such as `"78125.07"`, so no float rounding happens.
- Timestamps are UTC ISO 8601.
- Every market row states its `data_origin`: `live`, `backfill` or `synthetic`.
- Only closed candles are returned by REST.
- Everything except `/api/v1/health` and `/api/v1/auth/login` needs a login.

Errors use one structure:

```json
{ "error": { "code": "not_found", "message": "No such instrument.", "request_id": "..." } }
```

## Market Endpoints

| Method and path | Purpose | Limits |
|---|---|---|
| `POST /api/v1/auth/login` | Start a session cookie | 5 attempts per minute |
| `POST /api/v1/auth/logout` | End the session | |
| `GET /api/v1/auth/me` | Current owner | |
| `POST /api/v1/auth/ws-ticket` | Single-use WebSocket ticket, valid 30 seconds | |
| `GET /api/v1/instruments` | Instruments and their providers | |
| `GET /api/v1/market/candles` | Closed candles, newest page first | `limit` 1 to 1,000 |
| `GET /api/v1/market/price` | Latest price, with its age | |
| `GET /api/v1/market/status` | Data health per provider and instrument | |
| `GET /api/v1/market/gaps` | Recorded gaps | `limit` 1 to 500 |

`GET /market/candles` takes `provider`, `instrument_id`, `timeframe`, `limit` and `before`. The response holds `items`, oldest first, and `next_before`. To load older candles, pass `next_before` as `before`. It is null when no older candle exists.

`GET /market/price` returns `price` as null when no live value is held. A client must never present an old price as current, so the response always includes `age_seconds` and `stale`.

## Forecast Endpoint

| Method and path | Purpose | Limits |
|---|---|---|
| `GET /api/v1/forecasts/latest` | The latest Kronos forecast for an instrument, with what Python saw at that close | Read-only. 404 when none is stored |

It takes `provider` and `instrument_id`. The response is labelled `unvalidated model forecast` (D040) and holds:

- Per-candle bands of the close for Kronos and the baseline, and Kronos's 30 sampled closes.
- Summaries for 4 and 24 candles.
- The level catalogue with each source's reach shares.
- Chart patterns from the last 72 hours and candle signals from the last 24.
- Trend, regime and strategy decisions.
- The model's track record.
- The newest manual analyst plan from `data/signals`, if any, replayed on the 15M candles that followed through the shared simulator.

Forecast values are floats because they are model samples. Market prices stay strings. Levels, patterns and the baseline are recomputed from stored candles at the forecast's close, and `baseline_rebuilt` says whether the redrawn baseline matched the stored one exactly.

## Event Envelope

Every event has this structure. JSON Schemas are exported from Pydantic by `domain/events.py`.

| Field | Meaning |
|---|---|
| `event_id` | UUID, unique per event |
| `event_type` | Such as `market.candle` |
| `schema_version` | Integer, raised on any breaking change |
| `occurred_at` | When the fact happened, UTC |
| `seq` | Increases by one per topic |
| `data_origin` | `live`, `backfill` or `synthetic` |
| `payload` | Depends on `event_type` |

## WebSocket Protocol

1. The client calls `POST /api/v1/auth/ws-ticket` and receives a ticket.
2. The client connects to `/api/v1/ws?ticket=...`. The server checks the ticket and the `Origin` header, and closes the connection with code 4401 or 4403 on failure.
3. The client sends `{"type": "subscribe", "topics": ["market.price:binance_usdm:3"]}`.
4. The server replies `{"type": "subscribed", "topics": [...]}`, then sends events.
5. The server sends `{"type": "heartbeat", "at": "..."}` every 15 seconds. If 45 seconds pass with nothing, the client reconnects.

Topics:

| Topic | Delivery |
|---|---|
| `market.price:<provider>:<instrument_id>` | Latest value. Old values may be replaced for a slow client |
| `market.candle:<provider>:<instrument_id>:<timeframe>` | Closed candles and forming updates. Closed candles are never dropped silently |
| `market.status` | Health changes |

## Recovering From a Dropped Connection

1. Reconnect with exponential backoff and jitter, starting at 1 second and capped at 30 seconds, using a new ticket.
2. Subscribe again.
3. For each candle topic, call `GET /market/candles` to refill the chart.
4. Track `seq` per topic. A jump means an event was missed, so refill that topic through REST.
5. On `{"type": "resync", "topic": "..."}`, refill that topic through REST. The server sends this when a client is too slow to keep its queue.

A client that follows these steps needs nothing else to recover.
