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
| `GET /api/v1/forecasts/latest` | What Python sees at the latest 1H close, with the baseline projection, and a Kronos run only while Kronos is on | Read-only. 404 when no candles or rules are stored |
| `POST /api/v1/forecasts/analyse` | Start a re-analysis: a Kronos forecast from the latest stored 1H close, in the background | 202. 409 while one is running, or while Kronos is off |
| `GET /api/v1/forecasts/analyse` | The latest re-analysis: `idle`, `running`, `succeeded` or `failed`, with a message | |

It takes `provider` and `instrument_id`. Kronos was retired on 2026-11-06 (D040): `kronos_enabled` is false and `kronos` is null, so everything Kronos below is absent unless the setting is turned on. A Kronos run, when present, is labelled `unvalidated model forecast`. The response holds:

- Per-candle bands of the close for Kronos and the baseline, and Kronos's 30 sampled closes.
- Summaries for 4 and 24 candles.
- The level catalogue with each source's reach shares.
- Chart patterns from the last 72 hours and candle signals from the last 24.
- Trend, regime and strategy decisions.
- The model's track record.
- The newest manual analyst plan from `data/signals`, if any, replayed on the 15M candles that followed through the shared simulator.

Forecast values are floats because they are model samples. Market prices stay strings.

- **At the forecast's close (`as_of`):** Kronos and the baseline drawn beside it. `baseline_rebuilt` says whether the redrawn baseline matched the stored one exactly.
- **At the latest stored 1H close (`analysis_as_of`), recomputed every hour:**
  - Levels, patterns and decisions.
  - `projection`: the baseline drawn again from this close with the forecast's settings. It is null when too few 1H candles are stored.
  - Each strategy's decision, with Python's `proposal` prices when it says BUY or SELL.
- **`forecast_current`** says whether the Kronos run is from the latest close.
- **Reach shares** are measured from the latest close: `baseline` from the projection, and `model` only while `forecast_current` is true, otherwise null.
- **A manual plan's `python_at_close`** lists Python's decisions at the plan's close, read from the context saved beside it. It is null when none was saved.

`POST /forecasts/analyse` takes `provider` and `instrument_id`. It runs a forecast and stores it. Forecasts cannot reach orders (D040). The other write routes are the Binance accounts' limits (D058) and closes (D060), and Claude's daily cost limit (D062), below. A regression test keeps the list of write routes fixed.

## Signals and Paper Trading Endpoints

All are read-only. Nothing here can place or change a trade.

| Method and path | Purpose | Limits |
|---|---|---|
| `GET /api/v1/signals` | Recent recommendations with their risk decision, strategy and trade, newest first, filtered (D065) | `limit` 1 to 500 |
| `GET /api/v1/signals/{signal_id}` | One of the account's signals with its trade, for the Bot page's chart link (D065) | 404 when the account has no such signal |
| `GET /api/v1/coins/scorecard` | Each coin's scorecard (D068): every strategy's published backtest or why it is untested, live trades of every account counted once per setup, entry quality in R, and the coin now | Read-only, owner only |
| `GET /api/v1/paper-trading/summary` | Starting balance, equity with open trades at the latest price, and resolved results | |
| `GET /api/v1/paper-trading/positions` | Recent simulated positions | `limit` 1 to 200 |
| `GET /api/v1/paper-trading/trades` | Each simulated trade with its plan, current stop, targets and every fill, newest first | `limit` 1 to 500 |

Each takes `account`: `paper`, the tested strategies' account and the default; `demo`, the demo bot's 100 USDT account (D044); or `portfolio`, the money plan's 1,000 USDT account (D045). Any other value is refused with 422. `GET /paper-trading/trades` also takes an optional `instrument_id`.

The summary also gives `day_start_equity`, `open_risk` (what open trades would lose at their stops), and the account's `max_open_risk` and `daily_profit_stop` fractions, which are null outside the money plan. Signals carry `risk_share`, and trades carry `max_account_risk`, `risk_share` and `evidence_share`: the share of the 1% risk the trade was given and the share its strategy's evidence asked for. Both are null outside the money plan.

Signals also carry `signal_score`, the conditions of the signal score at the signal's close (docs/34): `long_term_trend`, `bitcoin_trend`, `volume` and `funding`, each true for the trade, false against it or null when unknown, with `against`, `weak` (null while any condition is unknown) and `bitcoin_applies` (false on Bitcoin's own signals). The score failed its test (D046), so it is information only and sets no size. It is null on signals from before 2026-11-10.

`GET /api/v1/signals` filters for the Signals page (D065). Every filter is optional:
- `instrument_id`, `strategy`, `action` (`BUY` or `SELL`) and `decision` (`APPROVED` or `REJECTED`).
- `result`, by the signal's trade: `entered` (open or closed), `open`, `won`, `lost`, `waiting`, or `not_entered` (rejected, never sent, not filled or refused).
- `period`: `today` from 00:00 UTC, `7d`, `30d`, or `all`, the default.

Each signal carries `trade`, null when it was rejected or no entry was sent for it:
- `state`: `waiting`, `open`, `won`, `lost`, `even`, `not filled` or `refused` (by Binance).
- `opened_at` and `closed_at`, and `entry_price` and `exit_price` averaged over the fills.
- `net` in USDT: after fees and funding once closed; Binance's open profit while a Binance trade is open; null while a paper trade is open.

On a Binance account the trade is the one the signal's entry order opened, rebuilt from Binance's fills (D057). A limit entry is `waiting` only while it is its coin's newest entry and its good-till time has not passed. On a paper account the trade is the simulator's position. Prices keep 8 places and `net` keeps 4.

A trade's fills have a `kind` (`entry`, `tp1` to `tp3`, `stop`, `expiry`, `invalidation` or `funding`), a UTC time, a price, quantity, fee, funding and whether the fill was `reconstructed` from repaired candles. Every trade and summary carries `simulated: true`.

## Binance Account Endpoints

The same routes exist for demo trading's test funds under `/api/v1/exchange-demo` (D048), and for the owner's real futures wallet under `/api/v1/exchange-live` (D060). They read what the quant worker saved. The API holds no exchange key and cannot import the exchange code, so no route can send an order.

| Method and path | Purpose | Limits |
|---|---|---|
| `GET …/status` | The account as last saved: `capital` (demo's budget, or what the owner put in), equity, free margin, positions and orders, each marked `bot` (false for the owner's own on the real account), the loss stop, and `closing`, the coins with a close still being carried out. On the real account, `live` gives `armed`, `armed_at`, `checked_at`, `problems` and `ip_restricted`. `test_funds` is false on the real account | `connected: false` until the worker has saved one. The real account is never made by reading |
| `GET …/results` | Completed trades rebuilt from Binance's fills (D057) | `period` `7d`, `30d` or `all` |
| `GET …/limits`, `PUT …/limits` | The account's limits and their ceilings; saving makes a new logged version (D058) | `PUT` only from the dashboard's origin. 404 on the real account until it is connected |
| `GET …/orders` | Every request sent to Binance, with what each means in USDT | `limit` 1 to 200 |
| `POST …/positions/{symbol}/close` | Ask for the bot's trade on a coin to be closed now (D060). Stores a request and writes it to the audit log; the quant worker cancels a waiting entry, closes the position at market with a reduce-only order, then cancels its stop and targets | 202. 403 from another origin. 404 when the bot has no open trade on the coin, including the owner's own positions. One waiting close per coin |
| `GET …/closes` | The latest closes asked, with `outcome`: `closed`, `nothing_open`, `not_the_bots` or `failed`, and its `detail` | `limit` 1 to 50 |
| `PUT …/arming` | The account's trading on or off (D063, D064). `armed: false` needs nothing more. On the real account, `armed: true` needs `password`, the owner's dashboard password; on demo it needs nothing more | On the real account: 403 from another origin or for a wrong password (rate-limited as login). 409 while the bot's last save is over 5 minutes old or its check found a problem. Every attempt is logged |

`GET /api/v1/signals` also takes `account=binance` for demo trading and `account=binance_live` for the real account, which gives an empty list until the account exists. `GET /api/v1/signals/{signal_id}` takes the same `account`, and gives 404 for a signal of any other account.

`GET /api/v1/ai/budget` gives Claude's daily cost limit for every call together (D062), its `ceiling_usd`, when it was `changed_at`, and today's spend since 00:00 UTC: `spent_today_usd`, `calls_today`, input and output tokens, `reached`, and the same `by_purpose`. `PUT /api/v1/ai/budget` takes `daily_limit_usd`, from $0 to the $3 ceiling, only from the dashboard's own origin, and writes the change to the audit log. Zero stops every Claude call.

`GET /api/v1/ai/exit-reviews` gives Claude's exit advice on open paper trades (D051), newest first, with `limit` 1 to 200. It reads only what the quant worker stored, and never calls Claude, so viewing it costs nothing.
- It carries `shadow: true`, the `model`, and `asking`: false until an Anthropic key is set.
- It also gives counts by `status`, the total `cost_usd`, how many answers are `scored`, and `mean_change_r`, the R the advice added on finished trades, over answers that were not "hold".
- Each review gives its close, coin, strategy, account, the `checks` that fired, its `status` (`advised`, `invalid`, `refused`, `error`, `not_asked` or `skipped_budget`), the `action` (`hold`, `take_profit_now` or `stop_to_breakeven`) and one-sentence `reason`, the trade's R when asked, tokens and cost.
- Once the trade has finished, a review also gives `own_r` and `advised_r`.

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
