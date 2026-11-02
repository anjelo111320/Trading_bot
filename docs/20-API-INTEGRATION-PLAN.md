# API Integration Plan

Date: 2026-11-02
Status: Updated for decisions D006 to D008. Research and licensing evidence are in [18-ARCHITECTURE-REVIEW.md](18-ARCHITECTURE-REVIEW.md).

This plan covers every external API the platform may use: what it provides, how it is accessed, its limits, and when it is integrated. "Verified" means confirmed by a live read-only call on 2026-11-02. Licensing notes quote published terms and are not legal advice.

## 1. Principles

- Providers are adapters behind one interface. Analysis code never imports a provider.
- No provider is assumed to support everything. Capabilities are declared per provider and per instrument in `provider_instruments`.
- Public market data uses no API keys. The platform holds no exchange credentials.
- Provider HTTP clients allow GET only, on an allow-list of paths.
- Every response is validated before use. Rejected data is recorded, never repaired silently.
- Geographic blocks are never bypassed. HTTP 451 is a hard stop with an alert.
- A provider is not used until its terms are recorded in `providers` with a version and review date.

## 2. Integration Schedule

| Provider | Purpose | Status | Phase | Depends on |
|---|---|---|---|---|
| Binance Spot | Long-history candles, bid and ask | Selected | 1A | Owner to confirm eligibility |
| Binance USD-M Futures | Venue for all simulated trades. Mark price, funding, open interest, liquidations | Selected, primary dataset | 1B | Owner to confirm eligibility |
| Official sources | Fed, SEC, BLS | Primary for macro and regulatory events | News phase, collection may start sooner | None |
| Claude API | Reasoning and classification | Required | News and analyst phases | API key |
| FMP or Finnhub | Crypto and market news | Candidates | News phase | Licence check |
| Telegram Bot API | Notifications | Proposed | Risk phase | Owner choice |
| Bybit | Fallback market data | Reserve | Only if needed | Terms unread |
| OANDA | Forex, if added | Deferred | Not scheduled | Account, licence |
| Interactive Brokers | Stocks and more, if added | Deferred | Not scheduled | Funded account, subscriptions |
| OKX | Market data | Not recommended | None | Terms restrict AI evaluation aimed at commercial or third-party use |
| Kraken, Coinbase | Market data | Rejected on technical grounds | None | Kraken REST gives 720 candles only; Coinbase WebSocket candles are 5-minute only |
| NewsAPI | News | Rejected | None | Free plan is development only with a 24-hour delay; Business is $449/month |

## 3. Provider Capability Matrix

| Data | Binance Spot | Binance USD-M | Bybit | OANDA | IBKR |
|---|---|---|---|---|---|
| Live price | Yes | Yes | Yes | Yes | Paid subscription |
| Bid and ask | `bookTicker` | `bookTicker` | Not checked | Yes, pricing stream | Paid subscription |
| Candles, all seven timeframes | Yes | Yes | Yes | Not confirmed | Not confirmed |
| Closed flag on stream | `x` | `x` | `confirm` | REST field `complete`, not confirmed | Not applicable |
| History depth | From 2017-08-17, verified | From 2019-09-08 BTC, 2019-11-27 ETH, verified | Not confirmed | From 2005, per OANDA | Limited, not confirmed |
| Order-book depth | Yes | Yes | Not checked | Not checked | Paid subscription |
| Funding | No | Yes, full history verified | Not checked | Not applicable | Not applicable |
| Open interest | No | Yes, last month only, verified | Not checked | Not applicable | Not applicable |
| Liquidations | No | Stream only, sampled | Not checked | Not applicable | Not applicable |
| Account needed | No | No | No | Yes | Yes, funded |

## 4. Provider Interface

```python
class MarketDataProvider(Protocol):
    capabilities: ProviderCapabilities

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def get_server_time(self) -> datetime: ...
    async def get_instrument_rules(self, instrument: Instrument) -> InstrumentRules: ...
    async def get_historical_candles(
        self, instrument: Instrument, timeframe: Timeframe, start: datetime, end: datetime,
    ) -> AsyncIterator[ClosedCandle]: ...
    def stream_market(
        self, subscriptions: Sequence[CandleSubscription], book_instruments: Sequence[Instrument], *,
        mark_instruments: Sequence[Instrument] = (), liquidation_instruments: Sequence[Instrument] = (),
    ) -> AsyncIterator[MarketEvent]: ...


class DerivativesCapable(Protocol):
    def get_funding_history(self, instrument: Instrument, start: datetime) -> AsyncIterator[FundingRate]: ...
    async def get_open_interest(self, instrument: Instrument) -> OpenInterest: ...
    def get_open_interest_history(self, instrument: Instrument, start: datetime) -> AsyncIterator[OpenInterest]: ...
```

`MarketEvent` covers candles, top of book, mark price, liquidation samples and link status. One method streams everything, because Binance carries several kinds of data on one connection and each extra connection counts against its limits. Parameters a provider cannot serve are checked against its capabilities. Depth stays out until a strategy needs it (T1.23).

Candle events are either `FormingCandle` or `ClosedCandle`. These are distinct types, so analysis code cannot accept forming data by accident.

This replaces the flat interface in [04-MARKET-DATA.md](04-MARKET-DATA.md), because forcing every provider to implement depth and derivatives would contradict the brief's rule that not every provider supports everything.

## 5. Binance Spot

Base URLs: `https://api.binance.com` and `wss://stream.binance.com:9443`.

The market-data-only hosts on `binance.vision` are avoided for now. They share a domain with the archive, and whether they are "associated endpoints" under the Vision terms is unclear. Vision archive files are not used.

### REST

| Endpoint | Use | Weight | Notes |
|---|---|---|---|
| `GET /api/v3/time` | Clock skew | Low | 22 ms measured |
| `GET /api/v3/exchangeInfo?symbol=` | Instrument rules | 20 | Every 6 hours, stored on change |
| `GET /api/v3/klines` | Backfill, repair, reconcile | 2 | 1000 rows maximum. Last row can be forming, verified |
| `GET /api/v3/depth` | Depth snapshot | Varies | Only if the local order book is built |

Limits: 6,000 weight per minute per IP, verified. Self-imposed cap: 1,500.

Backfill under the local storage profile (D024): 15M and above only, 1.18 million rows and 2,355 weight, about 2 minutes at the cap. The full history would be 12.8 million rows and 25,606 weight, about 17 minutes.

### Streams

| Stream | Use | Observed rate |
|---|---|---|
| `<symbol>@kline_<interval>` | Candles | About one frame per 2 s per stream |
| `<symbol>@bookTicker` | Bid and ask | About 101/s BTC, 35/s ETH in a 30-second sample |
| `<symbol>@depth10@100ms` | Depth summary, if needed | Not measured |

Phase 1A uses one combined connection with 14 kline streams and 2 bookTicker streams.

Connection rules from the documentation:

- A connection lasts about 24 hours. Replace it at about 23 hours 50 minutes by opening the new one first.
- The server pings every 20 seconds and drops the connection if no pong arrives within 1 minute.
- `serverShutdown` means reconnect now.
- At most 1,024 streams per connection, 5 incoming messages per second, and 300 connection attempts per 5 minutes per IP.

### Pitfalls

| Pitfall | Handling |
|---|---|
| REST returns the forming candle last | Keep only rows with `close_time` before server time |
| Klines have no sequence number | Detect gaps from open-time continuity |
| The final `x=true` frame can be lost | Reconcile by REST every 5 minutes |
| `close_time` ends in 999 ms | Next open equals close plus 1 ms |
| Spot archive files use microseconds from 2025-01-01 | Not used; the validator's range check still rejects them |
| Rules change over time | Snapshot from day one |

## 6. Binance USD-M Futures

Selected under D008 as the primary dataset. Only public data is read, and no Binance account is used. Base URLs: `https://fapi.binance.com` and `wss://fstream.binance.com`.

### REST

| Endpoint | Use | Limit, measured or documented | Notes |
|---|---|---|---|
| `GET /fapi/v1/exchangeInfo` | Rules | 2,400 weight per minute overall | BTCUSDT tick 0.10, step 0.001, minimum notional 50, verified. Differs from spot |
| `GET /fapi/v1/klines` | Candles | Weight 5 at 1000 rows, 2 at 499, 1 at 99, measured | BTCUSDT from 2019-09-08, ETHUSDT from 2019-11-27 |
| `GET /fapi/v1/fundingRate` | Funding history | 1000 rows per call | Full history available, verified from 2019-09-10 and 2019-11-27, every 8 hours |
| `GET /fapi/v1/premiumIndex` | Mark, index, latest funding | Not measured | Verified |
| `GET /fapi/v1/openInterest` | Current open interest | Not measured | Verified |
| `GET /futures/data/openInterestHist` | Recent open interest | 1,000 requests per 5 minutes, weight 0 | **Last month only.** An older request returned HTTP 400, verified |
| `GET /fapi/v1/leverageBracket` | Margin brackets | Requires an API key, verified | Not used. Conservative margin assumptions apply instead |
| `GET /fapi/v1/allForceOrders` | Liquidations | Retired, HTTP 404 verified | Not available |

Backfill: 9.8 million rows at weight 5 per 1,000 rows is about 49,000 weight, around 82 minutes at a cap of 600 per minute (25% of the limit).

### Streams

Binance split futures streams into routes. The legacy paths were scheduled for shutdown after 2026-04-23. A live test on 2026-11-02 confirmed the split.

| Route | Streams | Verified result |
|---|---|---|
| `wss://fstream.binance.com/market/stream` | `@kline_*`, `@markPrice@1s` | Delivered klines and mark price, and no bookTicker |
| `wss://fstream.binance.com/public/stream` | `@bookTicker`, `@depth*` | Delivered bookTicker and depth, and no klines |
| `wss://fstream.binance.com/stream` | Legacy | Delivered public data only, and silently dropped klines and mark price |

So the adapter needs **two connections**, and a subscription that silently delivers nothing must be treated as a failure. Heartbeat monitoring works per stream, not per connection.

`@forceOrder` needs route confirmation at implementation time, because no liquidation occurred during the 15-second test.

Liquidation data has limits: since 2021 the stream sends at most one order per symbol per second, and no history is available. Reports must describe it as a sample.

Observed bookTicker volume for BTCUSDT was about 283 to 635 messages per second, so the consumer must aggregate in memory and be load-tested.

### Data That Cannot Be Recovered

| Data | Limit | Consequence |
|---|---|---|
| Spot and futures spread | No history source found | Record per minute from day one |
| Instrument rules | No past values found | Record from day one |
| Open interest | One month back | Record continuously. Gaps under a month refill at 5-minute resolution |
| Liquidations | No history | Record continuously |
| Order-book depth | No history in the free API | Record only what the strategy needs |

Candles and funding can be backfilled at any time. The rest is lost while the collector is not running, so collection should start early and periods of sleep should be kept short.

## 7. Reserve and Deferred Providers

### Bybit

The strongest technical alternative. Public spot and linear feeds, `confirm` flag on streams, 600 requests per 5 seconds per IP, and at least a 10-minute ban on 403. REST has no closed flag and returns newest first. Limit of 100 arguments per connection from 2026-11-26.

Its terms could not be read. Thailand's SEC announced a block on Bybit and OKX effective 2025-06-28, according to secondary reports. Read the terms and check local rules before relying on it as a fallback.

### OANDA

For forex, if added. Requires a v20 trading account and a personal access token. A free demo account exists for testing.

Hosts: `api-fxpractice.oanda.com` and `stream-fxpractice.oanda.com` for practice, `api-fxtrade.oanda.com` and `stream-fxtrade.oanda.com` for live. Limits: 120 requests per second per IP, 20 active streams per IP, 2 new connections per second. History from 2005. The API licence is shown only inside the account portal, so it could not be reviewed.

Any integration must use practice hosts and read-only pricing endpoints. The same token can place orders, which conflicts with the rule against order-capable credentials, so it needs its own decision first.

### Interactive Brokers

For stocks and multi-asset coverage, if added. IBKR's documentation requires about $500 in a funded account, plus paid market-data subscriptions for real-time API data, with delayed data otherwise. Access runs through TWS or IB Gateway, or the Web API. Clients start with 100 market-data lines. Historical bars are restricted. Pacing limits were not found.

This requires a running gateway, a funded account and order-capable credentials, so it stays deferred.

### Paid Aggregators

Not needed, because D006 selected personal use. If that changes, a licensed source is required. CoinAPI starts at $79/month, but its pricing page says nothing about licensing. CoinGecko includes a commercial licence with attribution from $29/month, but it is not an exchange candle feed. CoinDesk Data has no public price, and its agreement limits use to internal purposes. Written terms are required from any of them.

## 8. News and Events

No paid vendor is selected yet. Sequence: official sources first, then one vendor evaluated against section 8.3.

### 8.1 Official Sources

| Source | Access | Use |
|---|---|---|
| Federal Reserve | RSS: `press_monetary.xml`, `press_all.xml`, `speeches.xml`, `prates.xml` under `federalreserve.gov/feeds/` | Monetary policy |
| SEC EDGAR | Free. 10 requests per second. Declared User-Agent required | Regulatory filings |
| BLS | Published schedule pages for CPI and Employment Situation | `economic_events` |
| Exchange announcements | No official API found | Do not scrape. Decide in the news phase |

### 8.2 Candidates

| Provider | Facts | Concern |
|---|---|---|
| FMP | `stable/news/crypto-latest` exists. Starter $22, Premium $59, Ultimate $149 per month, billed annually | Plan coverage unverified. Display needs a separate agreement |
| Finnhub | Free tier 60 calls per minute, personal use, which fits D006 | "All data must be deleted should your subscription to that data ends", which damages an archive. Crypto news coverage unverified |
| CryptoPanic | Free and paid plans; 5 to 10 requests per second | Terms unverified |
| CoinDesk Data | Free tier ended 2026-05-21 | No public price. Delete on termination |

### 8.3 Selection Criteria

A vendor is accepted only with written answers on: crypto coverage, original publication timestamps, storage rights after cancellation, permission to send content to an AI model, and cost. Keep full article text out of scope unless the licence allows it. Headlines and provider snippets are enough for classification.

Polling runs on a schedule within each provider's limits. The worker must not fetch article URLs itself, which avoids scraping and server-side request forgery.

### 8.4 Historical News

No affordable, cleanly licensed history was found. First backtests run without news. Forward collection should start early, because a timestamped archive cannot be created later.

## 9. Claude API

Full design: [07-CLAUDE-AI-ANALYST.md](07-CLAUDE-AI-ANALYST.md).

| Item | Detail |
|---|---|
| Access | Official `anthropic` Python SDK, backend only |
| Models | `claude-opus-5-5` for reasoning, `claude-haiku-5-5` for classification |
| Output | Structured outputs validated by Pydantic |
| Prices | Opus 5.5 $4/$20, Haiku 5.5 $0.10/$0.50 per million tokens. Batches 50% less |
| Errors | SDK retries 408, 409, 429 and 5xx. Handle `refusal`, `max_tokens` and schema failures |
| Tracking | Every call writes `api_usage` with tokens and cost |

## 10. Notifications

In-app events come first. Telegram is proposed for phone alerts: bots can message their users at no cost, at about one message per second per chat. The bot token is a secret, and messages contain no credentials. The channel is decided in the risk phase.

## 11. Common Adapter Behaviour

| Concern | Behaviour |
|---|---|
| Rate limits | Token bucket per provider at 25% of the published limit, updated from response headers |
| HTTP 429 | Honour `Retry-After`, then reduce rate |
| HTTP 418 | Stop that provider and alert. Binance bans can last from 2 minutes to 3 days |
| HTTP 403 | Stop and alert, as a WAF or security block |
| HTTP 451 | Hard stop and alert. No retry on another host |
| HTTP 5xx, timeouts | Jittered exponential backoff with a limit |
| WebSocket drop | Reconnect with jitter. Repair gaps by REST before reporting healthy |
| Heartbeat | Per-stream staleness, because a live connection can carry a dead stream |
| Duplicates | Idempotent writes keyed on natural keys |
| Timestamps | Convert to UTC, keep the raw provider value |
| Malformed data | Reject, count and record. The connection stays up |
| Secrets | From the environment only. Never logged |

Test approach: recorded or synthetic frames for adapters, a fake WebSocket server for failures, and opt-in live smoke tests excluded from the default run.

## 12. Open Items

- Binance's "separate API terms" and the current prohibited-country list. The owner should check that list for their location, which has not been stated.
- Whether derivatives data use has different eligibility terms in the owner's jurisdiction.
- The route for `@forceOrder`.
- FMP and Finnhub plan coverage, read from their own pricing pages by the owner or from support.
- Bybit's market-data terms.
- OANDA's API licence, visible only with an account.

## Sources

- Binance futures: [WebSocket routing notice](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice), [Market streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams), [Open interest statistics](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics), [Liquidation streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Liquidation-Order-Streams), [Change log](https://developers.binance.com/docs/derivatives/change-log)
- OANDA: [Getting started](https://developer.oanda.com/rest-live-v20/introduction/), [Development guide](https://developer.oanda.com/rest-live-v20/development-guide/)
- Interactive Brokers: [Market data requirements](https://www.interactivebrokers.com/docs/general/market-data-subscriptions/market-data-requirements), [Market data pricing](https://www.interactivebrokers.com/en/pricing/market-data-pricing.php)
- Telegram: [Bot FAQ](https://core.telegram.org/bots/faq)
- All other sources: [18-ARCHITECTURE-REVIEW.md](18-ARCHITECTURE-REVIEW.md), section 11.
