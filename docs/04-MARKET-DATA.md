# Market Data Specification

## Provider Architecture
Define a common interface for:
- connect()
- disconnect()
- subscribe_trades()
- subscribe_ticker()
- subscribe_orderbook()
- subscribe_candles()
- get_historical_candles()

Implement each provider independently.

Superseded in part: [20-API-INTEGRATION-PLAN.md](20-API-INTEGRATION-PLAN.md) splits this into required methods and optional capabilities, because not every provider supports every data type.

## Initial Scope
Binance public market data is selected: USD-M perpetuals for simulated trades, spot for long history.
Keep the provider replaceable.
Do not require API credentials for public endpoints when unnecessary.

## Candle Model
- instrument
- timeframe
- open_time
- close_time
- open
- high
- low
- close
- volume
- quote_volume
- trade_count
- is_closed
- provider
- received_at

## Validation
- OHLC consistency.
- Positive prices.
- Non-negative volume.
- Duplicate detection.
- Sequence gaps.
- Timestamp validation.
- Staleness checks.
- Provider health monitoring.

## Important Rules
Never silently fill missing market data.
Never treat incomplete candles as closed.
Preserve original provider timestamps.
Store normalized timestamps in UTC.
Record provider and data provenance.

## Licensing
Verify exchange data licensing and redistribution terms.
Do not scrape TradingView or bypass access controls.
Do not use TradingView data for automated processing without explicit permission.
