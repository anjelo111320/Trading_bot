# Paper Trading

## Purpose
Validate recommendations against live market data without real orders.

## Requirements
- Simulated balance.
- Open positions.
- Entry execution simulation.
- Stop-loss.
- Multiple take-profits.
- Fees.
- Spread.
- Slippage.
- Funding where applicable.
- Realized and unrealized P/L.
- Trade history.

## Execution
Define deterministic fill rules.
Handle gaps and candle ambiguity conservatively.
Never assume a limit order fills merely because price touched it.
Record every simulated execution.

## Live Loop

Since 2026-11-06 (D042), `make quant` runs the quant worker:

| At each close | It does |
|---|---|
| 1M | Replays every active paper trade through the shared simulator on the stored 1M candles, applying stored stop moves from the next candle |
| 1H | Runs the 1H pattern breakout (docs/27) for each core perpetual, then the risk engine. An approved signal opens a paper position |
| 1D | Tightens open daily trend stops to the 10-day extreme, then runs the daily trend (docs/29) |

Each strategy holds at most one position per coin. Both share the owner's paper account and its limits.

## Safety
Paper trading is the default.
No real broker order placement in initial release.
Clearly label simulated results.

## Downtime

Under D007 the platform runs on the owner's computer, so positions can sit unmonitored while it sleeps.

On waking, closed 1M candles are replayed in time order so stops, targets, invalidation and expiry resolve when they actually happened.
These fills are marked `reconstructed`, because the live spread at that moment is unknown. They use the conservative cost assumptions from backtesting.
Stop-before-target ordering applies when both fall in one candle.
Reports show live and reconstructed fills separately, along with coverage.
