# Binance Provider Pack

Date: 2026-11-02
Covers: Binance Spot and USD-M Futures public market data.
Plan: [20-API-INTEGRATION-PLAN.md](../20-API-INTEGRATION-PLAN.md). Evidence: [18-ARCHITECTURE-REVIEW.md](../18-ARCHITECTURE-REVIEW.md).

## Terms Relied On

| Item | Detail |
|---|---|
| Terms | Binance Terms of Use, read 2026-11-02 |
| Clause 27 | Allows "non-commercial personal or internal business use" |
| Clause 14.1.2 | Refers to separate API terms. These were not found, and remain an open question for Binance |
| Use | Personal only (D006), run on the owner's computer first (D007) |
| Eligibility | Confirmed by the owner on 2026-11-02 for their location |
| Account | None. Public endpoints only, with no API key |
| Vision archive | Not used. It is CC BY-NC-SA 4.0 and covers derived data (D017) |
| Hosting | A server location needs its own check, because Binance can refuse by IP (D026) |

## Behaviour Contract

"Probe" means a live read-only call on 2026-11-02. "Fixture" means a frame stored in `backend/tests/fixtures/`.

| Behaviour the adapter relies on | Evidence |
|---|---|
| Kline REST rows are arrays with `close_time` ending in 999 ms | Fixture `klines_btcusdt_1m.json` |
| The last REST row can be the forming candle | Probe |
| Stream klines carry `x=true` only on the closing frame | Fixture `stream_frames.json` |
| Spot `bookTicker` frames have no event time | Fixture `stream_frames.json` |
| Futures `bookTicker` frames carry `T` and `E` | Fixture `public_stream_frames.json` |
| Futures klines and mark price arrive on `/market/stream` | Fixture `market_stream_frames.json` |
| Futures `bookTicker` arrives on `/public/stream` | Fixture `public_stream_frames.json` |
| The legacy `/stream` path silently drops klines | Probe |
| Funding times can sit a few milliseconds past the hour, such as `...600005` | Fixture `funding_rate.json` |
| USD-M REST klines are not final for a few seconds after close, so the live closing frame is more complete at that moment. Never read them within 30 seconds of close | Observed 2026-11-02: 9 candles differed |
| `openInterestHist` without `endTime` returns only the newest rows, so each page must name its end | Probe |
| `openInterestHist` returns about the last month only | Probe |
| Spot limit 6,000 weight per minute; klines weight 2 | Probe and [spot limits](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/limits) |
| Futures limit 2,400 weight per minute; klines weight 5 at 1,000 rows | Probe |
| Connections end at about 24 hours; server pings every 20 s; pong within 1 minute | [Spot streams](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams), [futures streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams) |

## Fixtures

Stored under `backend/tests/fixtures/binance_spot/` and `binance_usdm/`, recorded by `backend/scripts/record_binance_frames.py`. They total under 100 KB, stay in this private repository, and are labelled in `meta.json`.

## Open Questions

- Where Binance publishes its separate API terms.
- Whether any Railway region is accepted (D026).
