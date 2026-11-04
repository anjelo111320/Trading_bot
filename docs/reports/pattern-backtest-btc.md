# Pattern Breakout Backtest: BTCUSDT Perpetual

Simulated results. A profitable backtest is not proof of future profitability.

Strategy `pattern_breakout` version 1, pattern rule version 2. Rules were registered before any run in [27-PATTERN-SIGNAL-PLAN.md](../27-PATTERN-SIGNAL-PLAN.md). Period 2020-01-01 to 2025-11-01, before the frozen holdout (D029). Data: 53,887 1H, 13,472 4H, 2,246 1D and 215,545 15M candles, and 2,195 funding events.

## Trial 1 at Normal Costs

| Metric | Value |
|---|---|
| Trades | 162 |
| Net P/L after costs | 2476.24 |
| Total return | 24.76% |
| Win rate | 0.340 |
| Expectancy (R) | 0.159 |
| 95% interval for expectancy | -0.109 to 0.439 |
| Profit factor | 1.205 |
| Maximum drawdown | 10.45% |
| Sharpe (daily, 365 days, no risk-free rate) | 0.468 |
| Sortino | 0.968 |
| Cost share of gross profit | 0.075 |

## How Signals Were Made

Every 1H candle where a chart pattern broke out, and what the strategy decided there.

| Step | Count |
|---|---|
| Chart-pattern breakouts | 1187 |
| Refused: against the 4H or 1D trend | 839 |
| Refused: no reachable target | 74 |
| Proposed as BUY or SELL | 274 |
| Reached the risk engine, with no position open | 174 |
| Approved and filled | 162 |

Risk engine rejections:

- EXPOSURE_EXCEEDED: 6
- RR_BELOW_MIN: 8

## Costs

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Trial 1 at 1x costs | 162 | 0.34 | 0.159 | -0.11 to 0.44 | 1.20 | 2476 |
| Trial 1 at 1.5x costs | 159 | 0.33 | 0.115 | -0.16 to 0.39 | 1.14 | 1656 |
| Trial 1 at 2x costs | 156 | 0.33 | 0.088 | -0.18 to 0.38 | 1.10 | 1125 |

## Walk-Forward Test Folds, Trial 1

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Fold 1: 2022-07-03 to 2022-12-30 | 12 | 0.17 | -0.570 | -1.06 to 0.12 | 0.35 | -749 |
| Fold 2: 2022-12-30 to 2023-06-28 | 11 | 0.27 | -0.063 | -1.06 to 0.96 | 0.90 | -86 |
| Fold 3: 2023-06-28 to 2023-12-25 | 10 | 0.60 | 1.069 | -0.12 to 2.22 | 3.41 | 1132 |
| Fold 4: 2023-12-25 to 2024-06-22 | 14 | 0.36 | 0.010 | -0.78 to 0.93 | 1.01 | 10 |
| Fold 5: 2024-06-22 to 2024-12-19 | 14 | 0.50 | 0.367 | -0.45 to 1.18 | 1.71 | 600 |
| Fold 6: 2024-12-19 to 2025-06-17 | 13 | 0.23 | -0.224 | -1.06 to 0.64 | 0.70 | -376 |
| **All test folds** | 74 | 0.35 | 0.075 | -0.30 to 0.44 | 1.09 | 530 |

## Benchmarks

- Buy and hold, no costs: +1423.9% over the period.
- Random entries with the 4H and 1D trend, same exits, 20 seeds: mean expectancy 0.112R, 5th to 95th percentile 0.005R to 0.270R, mean 132 trades per seed. Strategy: 0.159R.

## By Pattern and Direction, Trial 1

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| ascending_triangle | 10 | 0.10 | -0.886 | -1.07 to -0.54 | 0.06 | -982 |
| bear_flag | 28 | 0.36 | 0.323 | -0.36 to 1.05 | 1.43 | 866 |
| bull_flag | 44 | 0.43 | 0.450 | -0.05 to 0.99 | 1.74 | 2096 |
| descending_triangle | 4 | 0.75 | 1.617 | -0.12 to 3.20 | 6.85 | 685 |
| double_bottom | 2 | 0.50 | 0.652 | -1.02 to 2.32 | 2.14 | 119 |
| falling_wedge | 16 | 0.38 | 0.365 | -0.54 to 1.34 | 1.56 | 618 |
| head_and_shoulders | 2 | 0.50 | 0.689 | -1.08 to 2.46 | 2.02 | 123 |
| inverse_head_and_shoulders | 3 | 0.33 | -0.062 | -1.04 to 1.90 | 1.04 | 9 |
| rectangle | 1 | 0.00 | -1.033 | n/a | 0.00 | -112 |
| rising_wedge | 22 | 0.41 | 0.383 | -0.37 to 1.18 | 1.54 | 814 |
| symmetrical_triangle | 30 | 0.13 | -0.551 | -1.02 to 0.05 | 0.40 | -1760 |
| LONG | 101 | 0.38 | 0.298 | -0.06 to 0.64 | 1.43 | 3049 |
| SHORT | 61 | 0.28 | -0.072 | -0.47 to 0.35 | 0.88 | -572 |

## By Market Regime at the Signal, Trial 1

Daily ADX of 25 or more is trending, below 20 ranging. Volatility ranks daily ATR against the trailing year: calm is the lowest quarter, volatile the highest. Labels use only data known at the signal. These are descriptions of the past, and a rule built from them needs fresh data to test.

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| trend: ranging | 46 | 0.37 | 0.311 | -0.21 to 0.84 | 1.44 | 1494 |
| trend: transition | 32 | 0.28 | -0.014 | -0.59 to 0.67 | 0.96 | -101 |
| trend: trending | 84 | 0.35 | 0.141 | -0.21 to 0.55 | 1.18 | 1083 |
| volatility: calm | 56 | 0.39 | 0.464 | -0.02 to 0.97 | 1.70 | 2646 |
| volatility: normal | 73 | 0.38 | 0.271 | -0.11 to 0.70 | 1.40 | 2053 |
| volatility: volatile | 33 | 0.15 | -0.609 | -0.94 to -0.20 | 0.30 | -2223 |

## Trial 2: Candle Confirmation Required

Breakouts: 1187. Proposed: 154.

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Trial 2 at 1x costs | 112 | 0.35 | 0.182 | -0.13 to 0.50 | 1.24 | 1958 |
| Trial 2 at 1.5x costs | 108 | 0.34 | 0.143 | -0.16 to 0.49 | 1.18 | 1431 |
| Trial 2 at 2x costs | 106 | 0.34 | 0.134 | -0.20 to 0.48 | 1.16 | 1254 |

Walk-forward test folds at normal costs:

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Fold 1: 2022-07-03 to 2022-12-30 | 7 | 0.14 | -0.572 | -1.08 to 0.41 | 0.37 | -436 |
| Fold 2: 2022-12-30 to 2023-06-28 | 7 | 0.43 | 0.512 | -0.57 to 1.97 | 1.80 | 366 |
| Fold 3: 2023-06-28 to 2023-12-25 | 7 | 0.57 | 0.943 | -0.46 to 2.50 | 2.89 | 707 |
| Fold 4: 2023-12-25 to 2024-06-22 | 13 | 0.38 | 0.089 | -0.76 to 1.03 | 1.11 | 114 |
| Fold 5: 2024-06-22 to 2024-12-19 | 10 | 0.40 | 0.129 | -0.82 to 1.14 | 1.20 | 150 |
| Fold 6: 2024-12-19 to 2025-06-17 | 10 | 0.20 | -0.325 | -1.07 to 0.72 | 0.60 | -392 |
| **All test folds** | 54 | 0.35 | 0.099 | -0.35 to 0.57 | 1.12 | 509 |

## Promotion Gate, Trial 1

| Gate | Required | Result | |
|---|---|---|---|
| Out-of-sample trades | At least 200 | 74 | **Not met** |
| Expectancy | Interval above zero | -0.30 to 0.44 | **Not met** |
| Profit factor at 1.5x costs | Above 1.2 | 1.01 | **Not met** |
| Positive folds | Most of 6 | 3 | **Not met** |
| Random benchmark | Above its 95th percentile | 0.075 | **Not met** |
| Nearby parameters | Similar results | Not tested | n/a |

## Limits

- Two trials were run, both declared in advance. No parameter was tuned.
- Fills use 15M candles, not 1M. A stop and target in the same candle count as a stop, so this can only make results worse (D034).
- Spread and slippage are conservative assumptions. Instrument rules are today's snapshot, used as a proxy for the whole period.
- One position at a time, and signals during an open trade are ignored. Runs are therefore path dependent: at higher costs the 2:1 rule rejects more marginal setups, which frees the position for other trades. On the trades two cost levels share, the higher cost always earns less.
- Patterns are labels from written rules. Some shapes that pass a rule, such as a wedge whose last two turning points sit on neighbouring candles, would not be drawn that way by a person.
- BTC and ETH were chosen with hindsight, which is survivorship bias.
- No news was used. Claude is not part of this test (D030).
