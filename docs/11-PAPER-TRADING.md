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
