# Trend Pullback Backtest: BTCUSDT Perpetual

Simulated results. A profitable backtest is not proof of future profitability.

Strategy `trend_pullback` version 1, registered before any run in [31-PULLBACK-STRATEGY.md](../31-PULLBACK-STRATEGY.md). Period 2020-01-01 to 2025-11-01, before the frozen holdout.

## Normal Costs

| Metric | Value |
|---|---|
| Trades | 513 |
| Net P/L after costs | -5736.01 |
| Total return | -57.36% |
| Win rate | 0.261 |
| Expectancy (R) | -0.176 |
| 95% interval for expectancy | -0.311 to -0.033 |
| Profit factor | 0.781 |
| Maximum drawdown | 58.06% |
| Sharpe (daily, 365 days, no risk-free rate) | -0.944 |
| Sortino | -1.469 |
| Cost share of gross profit | 0.146 |

Signals that reached the risk engine: 1665. Exits: stop 405, tp3 71, tp2 21, tp1 16.

## Funnel

| What happened at a 1H close | Count |
|---|---|
| no reversal candle with the trend | 24454 |
| trends disagree | 21237 |
| proposed | 2419 |
| the reversal is not at a support level | 1981 |
| the reversal is not at a resistance level | 1013 |
| no reachable target | 40 |

## Costs

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| 1x costs | 513 | 0.26 | -0.176 | -0.31 to -0.03 | 0.78 | -5736 |
| 1.5x costs | 459 | 0.26 | -0.209 | -0.36 to -0.06 | 0.75 | -5750 |
| 2x costs | 400 | 0.25 | -0.276 | -0.44 to -0.10 | 0.70 | -5983 |

## Walk-Forward Test Folds

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Fold 1: 2022-07-03 to 2022-12-30 | 47 | 0.21 | -0.419 | -0.79 to 0.01 | 0.52 | -1007 |
| Fold 2: 2022-12-30 to 2023-06-28 | 32 | 0.38 | 0.131 | -0.42 to 0.70 | 1.17 | 177 |
| Fold 3: 2023-06-28 to 2023-12-25 | 15 | 0.40 | 0.365 | -0.53 to 1.35 | 1.51 | 255 |
| Fold 4: 2023-12-25 to 2024-06-22 | 43 | 0.26 | -0.226 | -0.68 to 0.25 | 0.72 | -470 |
| Fold 5: 2024-06-22 to 2024-12-19 | 34 | 0.24 | -0.181 | -0.77 to 0.39 | 0.78 | -284 |
| Fold 6: 2024-12-19 to 2025-06-17 | 28 | 0.29 | -0.067 | -0.63 to 0.58 | 0.91 | -87 |
| **All test folds** | 199 | 0.28 | -0.140 | -0.36 to 0.09 | 0.81 | -1416 |

## By Year, Side and Candle

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| 2020 | 89 | 0.30 | 0.004 | -0.35 to 0.37 | 1.00 | -22 |
| 2021 | 160 | 0.23 | -0.273 | -0.50 to -0.02 | 0.66 | -3379 |
| 2022 | 101 | 0.25 | -0.275 | -0.56 to 0.05 | 0.67 | -1497 |
| 2023 | 47 | 0.38 | 0.205 | -0.29 to 0.73 | 1.28 | 432 |
| 2024 | 77 | 0.25 | -0.206 | -0.55 to 0.16 | 0.74 | -755 |
| 2025 | 39 | 0.23 | -0.325 | -0.75 to 0.18 | 0.63 | -515 |
| LONG | 284 | 0.26 | -0.181 | -0.36 to 0.02 | 0.80 | -3000 |
| SHORT | 229 | 0.26 | -0.169 | -0.37 to 0.05 | 0.76 | -2736 |
| bearish_engulfing | 138 | 0.28 | -0.111 | -0.38 to 0.18 | 0.88 | -793 |
| bearish_harami | 12 | 0.17 | -0.562 | -1.12 to 0.25 | 0.44 | -396 |
| bearish_marubozu | 8 | 0.50 | 0.709 | -0.64 to 1.94 | 1.98 | 267 |
| bullish_engulfing | 132 | 0.30 | -0.071 | -0.35 to 0.24 | 0.97 | -196 |
| bullish_harami | 7 | 0.14 | -0.638 | -1.13 to 0.33 | 0.21 | -376 |
| bullish_marubozu | 13 | 0.31 | -0.103 | -0.89 to 0.79 | 0.90 | -58 |
| dark_cloud_cover | 11 | 0.18 | -0.468 | -1.12 to 0.49 | 0.38 | -443 |
| evening_star | 1 | 0.00 | -1.050 | n/a | 0.00 | -61 |
| hammer | 4 | 0.50 | 0.643 | -1.13 to 2.41 | 2.72 | 257 |
| morning_star | 5 | 0.60 | 1.101 | -0.44 to 2.64 | 3.01 | 374 |
| piercing_line | 11 | 0.36 | 0.151 | -0.77 to 1.25 | 1.59 | 263 |
| pin_bar | 126 | 0.20 | -0.358 | -0.62 to -0.09 | 0.53 | -3378 |
| three_black_crows | 1 | 1.00 | 0.484 | n/a | n/a | 27 |
| three_inside_down | 1 | 1.00 | 2.344 | n/a | n/a | 95 |
| three_outside_down | 14 | 0.21 | -0.227 | -1.10 to 0.70 | 0.68 | -233 |
| three_outside_up | 18 | 0.17 | -0.514 | -1.10 to 0.09 | 0.38 | -647 |
| three_white_soldiers | 1 | 0.00 | -1.153 | n/a | 0.00 | -77 |
| tweezer_bottom | 4 | 0.25 | -0.243 | -1.14 to 1.50 | 0.75 | -55 |
| tweezer_top | 6 | 0.17 | -0.868 | -1.14 to -0.34 | 0.08 | -306 |

## Benchmarks

- Buy and hold, no costs: +1423.9% over the period.
- Random 1H closes where 4H and 1D agree, with this strategy's stops and targets, 20 seeds of about 582 trades: mean -0.005R, 5th to 95th percentile -0.064R to 0.058R. Strategy: -0.176R.

## Promotion Gate

| Gate | Required | Result | |
|---|---|---|---|
| Out-of-sample trades | At least 200 | 199 | **Not met** |
| Expectancy | Interval above zero | -0.36 to 0.09 | **Not met** |
| Profit factor at 1.5x costs | Above 1.2 | 0.80 | **Not met** |
| Positive folds | Most of 6 | 2 | **Not met** |
| Random benchmark | Above its 95th percentile | -0.140 | **Not met** |
| Nearby parameters | Similar results | Not tested | n/a |

## Limits

- One trial, nothing tuned. The holdout was not used (docs/31).
- Fills use 15M candles. Costs are conservative assumptions and funding is real.
- Several strategies have been tested on these years, so a borderline result is weak.
- BTC and ETH were chosen with hindsight.
