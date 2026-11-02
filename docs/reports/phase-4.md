# Phase 4 Completion Report

Date: 2026-11-02
Status: Engine complete and tested. **The evidence gate is not met**, because full history is not available here.

## Exit Gate

| Gate | Result | Evidence |
|---|---|---|
| Reproducible | Passed | Same inputs give identical trades |
| Leakage tests pass | Passed | Corrupting all future candles changes no past decision |
| Fill rules | Passed | 30 golden tests in `test_simulator.py` |
| Holdout protected | Passed | Frozen at 2025-11-01 (D029). Code refuses it, and a real attempt was refused |
| Honest report | Passed | Below |
| Promotion gate | **Not met** | Needs at least 200 out-of-sample trades. This run has 41 |

## First Real Run

Window: 2025-08-01 to 2025-11-01, on real perpetual candles from before the holdout. Full reports: [BTC](backtest-research-btc.md), [ETH](backtest-research-eth.md).

| | BTCUSDT | ETHUSDT |
|---|---|---|
| Decisions checked | 8,832 | 8,832 |
| Signals | 58 | 75 |
| Trades | 9 | 32 |
| Net P/L on 10,000 | -559.10 | +405.72 |
| Win rate | 11.1% | 34.4% |
| Expectancy | -0.69R | +0.15R |
| 95% interval | -1.10R to +0.10R | -0.42R to +0.73R |
| Profit factor | 0.28 | 1.19 |
| Maximum drawdown | 5.59% | 6.79% |
| At 2× costs | -667.75 | -118.87 |

**This shows no edge.** Both intervals include zero, and the ETH profit does not survive 2× costs. Three months is far too short, and these numbers say the engine runs, nothing more.

## Trials

| Trial | Change | Result |
|---|---|---|
| 1 | Version 1, first target at 1R | 0 BTC trades, because every signal failed the 2:1 rule by design |
| 2 | Version 2, first target at 2R | Above |

Version 1 was a logic error, not a tuning choice. Tuning stopped there on purpose, because adjusting a strategy to one short window is how overfitting begins.

## Limits

- Spread and slippage are conservative assumptions, since recorded spread does not yet cover this period.
- Instrument rules are today's snapshot, used as a proxy.
- Only one position at a time per instrument, and instruments run separately.
- The liquidity cap applies to entries only.
- Deflated Sharpe, parameter stability and random-entry benchmarks are not built yet. They matter once full history is available.
- BTC and ETH were chosen with hindsight.
- No news was used.

## Next

Walk-forward needs full perpetual history: about 2.4 GB and a place to hold it, which the Railway move or more free disk would provide.
