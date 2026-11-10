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
| 15M | The demo bot (D044): runs the 15M rule baseline for each core perpetual into the separate 100 USDT `Demo` account, through the risk engine. An approved signal enters at the live price seconds after the close. Then the money plan (D045) runs once for all coins together, below |
| 1H | Runs the 1H pattern breakout (docs/27) for each core perpetual, then the risk engine. An approved signal opens a paper position |
| 1D | Tightens open daily trend stops to the 10-day extreme, then runs the daily trend (docs/29) |

Each strategy holds at most one position per coin and account. The two tested strategies share the owner's `Paper` account and its limits. The demo bot has its own `Demo` account with the default limits: 1% risk per trade (1 USDT), 2:1 reward to risk, a 3% daily loss limit and at most 3 open positions.

## Money Plan

Since 2026-11-09 (D045), a third paper account, `Portfolio`, starts with 1,000 USDT and runs every Python strategy on every core coin. At each 15M close the worker decides all six coins together: the 15M rule baseline always, the 1H pattern breakout at each 1H close, and the daily trend at each daily close. A coin whose candle for that close is not stored yet is skipped and logged, never decided on the candle before.

| Strategy | Share of the 1% risk per trade | Evidence |
|---|---|---|
| Daily trend | Full: 1% | Replicated on the four coins it was not first tested on (docs/33) |
| 1H pattern breakout | Half: 0.5% | Positive on six coins pooled, but not clearly on the new four |
| 15M rule baseline | Quarter: 0.25% | Not testable on history before the holdout. Enters at the live price, as in D044 |

Signals at the same close share the account's room, the strongest evidence first (docs/08, Money Plan Limits). At most 3% of equity is at risk across open trades, the same as the daily loss limit, and new trades stop for the UTC day once the account is 3% up. Up to 10 positions, one per strategy and coin, and total size within equity, so no leverage. The risk engine decides every trade and stores each refusal with its reason. Shares weigh backtest evidence; they are not win probabilities.

A decision waits 10 seconds after its close so the minute's order book is stored. A close older than its freshness window (5 minutes for 15M, 15 for 1H, an hour for 1D) is never traded.

## Demo Bot Page

The dashboard's Bot page (`/bot`) switches between the money plan account and the demo account, and shows one coin at a time on a live candle chart. An arrow marks each entry, BUY below the bar and SELL above it. A dot marks each exit, green at a target and red at the stop. Lines mark the open trade's entry, current stop and the targets still ahead. Beside the chart are the account (profit in USDT and as a share of its start), the open trade with its strategy, risk and live profit, and Python's latest setups with the risk engine's decision. Each setup also shows its signal score in words, such as "Score weak, 2 of 4 against", labelled as recorded to test on live results and never changing a trade's size (D046). For the money plan the account also shows today's profit against the +3% stop and the risk in open trades against its 3% limit. The trade history table lists every coin with its strategy and the USDT it risked. All of it is labelled simulated, and the demo's strategy is labelled untested.

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
