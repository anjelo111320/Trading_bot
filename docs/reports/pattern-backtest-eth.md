# Pattern Breakout Backtest: ETHUSDT Perpetual

Simulated results. A profitable backtest is not proof of future profitability.

Strategy `pattern_breakout` version 1, pattern rule version 2. Rules were registered before any run in [27-PATTERN-SIGNAL-PLAN.md](../27-PATTERN-SIGNAL-PLAN.md). Period 2020-01-01 to 2025-11-01, before the frozen holdout (D029). Data: 51,977 1H, 12,995 4H, 2,166 1D and 207,905 15M candles, and 2,195 funding events.

## Trial 1 at Normal Costs

| Metric | Value |
|---|---|
| Trades | 176 |
| Net P/L after costs | 2225.04 |
| Total return | 22.25% |
| Win rate | 0.318 |
| Expectancy (R) | 0.139 |
| 95% interval for expectancy | -0.119 to 0.402 |
| Profit factor | 1.164 |
| Maximum drawdown | 15.07% |
| Sharpe (daily, 365 days, no risk-free rate) | 0.406 |
| Sortino | 0.858 |
| Cost share of gross profit | 0.056 |

## How Signals Were Made

Every 1H candle where a chart pattern broke out, and what the strategy decided there.

| Step | Count |
|---|---|
| Chart-pattern breakouts | 1240 |
| Refused: against the 4H or 1D trend | 847 |
| Refused: no reachable target | 95 |
| Proposed as BUY or SELL | 298 |
| Reached the risk engine, with no position open | 190 |
| Approved and filled | 176 |

Risk engine rejections:

- EXPOSURE_EXCEEDED: 2
- RR_BELOW_MIN: 11

## Costs

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Trial 1 at 1x costs | 176 | 0.32 | 0.139 | -0.12 to 0.40 | 1.16 | 2225 |
| Trial 1 at 1.5x costs | 171 | 0.32 | 0.136 | -0.13 to 0.41 | 1.15 | 1991 |
| Trial 1 at 2x costs | 166 | 0.33 | 0.162 | -0.13 to 0.43 | 1.18 | 2312 |

## Walk-Forward Test Folds, Trial 1

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Fold 1: 2022-07-03 to 2022-12-30 | 19 | 0.32 | 0.139 | -0.67 to 1.07 | 1.16 | 210 |
| Fold 2: 2022-12-30 to 2023-06-28 | 13 | 0.38 | 0.294 | -0.65 to 1.28 | 1.42 | 358 |
| Fold 3: 2023-06-28 to 2023-12-25 | 12 | 0.42 | 0.603 | -0.46 to 1.86 | 1.89 | 729 |
| Fold 4: 2023-12-25 to 2024-06-22 | 16 | 0.44 | 0.364 | -0.39 to 1.23 | 1.54 | 612 |
| Fold 5: 2024-06-22 to 2024-12-19 | 6 | 0.50 | 0.620 | -0.57 to 1.83 | 2.21 | 425 |
| Fold 6: 2024-12-19 to 2025-06-17 | 16 | 0.25 | -0.036 | -0.79 to 0.96 | 0.93 | -108 |
| **All test folds** | 82 | 0.37 | 0.277 | -0.11 to 0.68 | 1.37 | 2226 |

## Benchmarks

- Buy and hold, no costs: +2878.9% over the period.
- Random entries with the 4H and 1D trend, same exits, 20 seeds: mean expectancy 0.069R, 5th to 95th percentile -0.066R to 0.265R, mean 158 trades per seed. Strategy: 0.139R.

## By Pattern and Direction, Trial 1

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| ascending_triangle | 6 | 0.50 | 0.717 | -0.62 to 2.09 | 2.28 | 453 |
| bear_flag | 22 | 0.32 | 0.174 | -0.52 to 0.97 | 1.19 | 339 |
| bull_flag | 56 | 0.30 | 0.033 | -0.39 to 0.47 | 1.07 | 319 |
| descending_triangle | 6 | 0.17 | -0.419 | -1.05 to 0.83 | 0.48 | -297 |
| double_bottom | 5 | 0.20 | -0.389 | -1.07 to 0.93 | 0.59 | -187 |
| double_top | 2 | 0.00 | -1.029 | -1.05 to -1.00 | 0.00 | -239 |
| falling_wedge | 18 | 0.44 | 0.602 | -0.26 to 1.54 | 1.95 | 1042 |
| head_and_shoulders | 2 | 0.00 | -1.033 | -1.04 to -1.03 | 0.00 | -233 |
| inverse_head_and_shoulders | 3 | 0.67 | 1.555 | -1.05 to 2.93 | 5.80 | 488 |
| rising_wedge | 20 | 0.45 | 0.611 | -0.25 to 1.51 | 2.01 | 1235 |
| symmetrical_triangle | 36 | 0.22 | -0.129 | -0.67 to 0.46 | 0.78 | -695 |
| LONG | 112 | 0.34 | 0.232 | -0.10 to 0.59 | 1.32 | 2656 |
| SHORT | 64 | 0.28 | -0.024 | -0.41 to 0.38 | 0.92 | -431 |

## Trial 2: Candle Confirmation Required

Breakouts: 1240. Proposed: 166.

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Trial 2 at 1x costs | 126 | 0.32 | 0.140 | -0.18 to 0.45 | 1.17 | 1516 |
| Trial 2 at 1.5x costs | 122 | 0.32 | 0.132 | -0.18 to 0.45 | 1.15 | 1287 |
| Trial 2 at 2x costs | 118 | 0.33 | 0.165 | -0.19 to 0.50 | 1.20 | 1572 |

Walk-forward test folds at normal costs:

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Fold 1: 2022-07-03 to 2022-12-30 | 9 | 0.33 | 0.354 | -1.03 to 1.80 | 1.43 | 241 |
| Fold 2: 2022-12-30 to 2023-06-28 | 9 | 0.33 | 0.278 | -0.65 to 1.62 | 1.36 | 203 |
| Fold 3: 2023-06-28 to 2023-12-25 | 9 | 0.44 | 0.625 | -0.65 to 1.90 | 2.04 | 512 |
| Fold 4: 2023-12-25 to 2024-06-22 | 11 | 0.55 | 0.833 | -0.22 to 1.93 | 2.56 | 875 |
| Fold 5: 2024-06-22 to 2024-12-19 | 7 | 0.43 | 0.478 | -0.64 to 1.91 | 1.76 | 333 |
| Fold 6: 2024-12-19 to 2025-06-17 | 10 | 0.30 | 0.207 | -1.03 to 1.46 | 1.25 | 205 |
| **All test folds** | 55 | 0.40 | 0.471 | -0.04 to 1.00 | 1.69 | 2369 |

## Promotion Gate, Trial 1

| Gate | Required | Result | |
|---|---|---|---|
| Out-of-sample trades | At least 200 | 82 | **Not met** |
| Expectancy | Interval above zero | -0.11 to 0.68 | **Not met** |
| Profit factor at 1.5x costs | Above 1.2 | 1.34 | Passed |
| Positive folds | Most of 6 | 5 | Passed |
| Random benchmark | Above its 95th percentile | 0.277 | Passed |
| Nearby parameters | Similar results | Not tested | n/a |

## Limits

- Two trials were run, both declared in advance. No parameter was tuned.
- Fills use 15M candles, not 1M. A stop and target in the same candle count as a stop, so this can only make results worse (D034).
- Spread and slippage are conservative assumptions. Instrument rules are today's snapshot, used as a proxy for the whole period.
- One position at a time, and signals during an open trade are ignored. Runs are therefore path dependent: at higher costs the 2:1 rule rejects more marginal setups, which frees the position for other trades. On the trades two cost levels share, the higher cost always earns less.
- Patterns are labels from written rules. Some shapes that pass a rule, such as a wedge whose last two turning points sit on neighbouring candles, would not be drawn that way by a person.
- BTC and ETH were chosen with hindsight, which is survivorship bias.
- No news was used. Claude is not part of this test (D030).
