# Trend Pullback Backtest: ETHUSDT Perpetual

Simulated results. A profitable backtest is not proof of future profitability.

Strategy `trend_pullback` version 1, registered before any run in [31-PULLBACK-STRATEGY.md](../31-PULLBACK-STRATEGY.md). Period 2020-01-01 to 2025-11-01, before the frozen holdout.

## Normal Costs

| Metric | Value |
|---|---|
| Trades | 696 |
| Net P/L after costs | -6093.92 |
| Total return | -60.94% |
| Win rate | 0.274 |
| Expectancy (R) | -0.138 |
| 95% interval for expectancy | -0.263 to -0.011 |
| Profit factor | 0.832 |
| Maximum drawdown | 64.25% |
| Sharpe (daily, 365 days, no risk-free rate) | -0.898 |
| Sortino | -1.414 |
| Cost share of gross profit | 0.133 |

Signals that reached the risk engine: 1565. Exits: stop 550, tp3 103, tp1 23, tp2 20.

## Funnel

| What happened at a 1H close | Count |
|---|---|
| no reversal candle with the trend | 25395 |
| trends disagree | 20117 |
| proposed | 2486 |
| the reversal is not at a support level | 1897 |
| the reversal is not at a resistance level | 1219 |
| no reachable target | 30 |

## Costs

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| 1x costs | 696 | 0.27 | -0.138 | -0.26 to -0.01 | 0.83 | -6094 |
| 1.5x costs | 643 | 0.27 | -0.181 | -0.31 to -0.05 | 0.80 | -6529 |
| 2x costs | 554 | 0.27 | -0.202 | -0.34 to -0.06 | 0.79 | -6165 |

## Walk-Forward Test Folds

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Fold 1: 2022-07-03 to 2022-12-30 | 66 | 0.27 | -0.162 | -0.56 to 0.28 | 0.79 | -750 |
| Fold 2: 2022-12-30 to 2023-06-28 | 33 | 0.18 | -0.587 | -0.94 to -0.16 | 0.35 | -1144 |
| Fold 3: 2023-06-28 to 2023-12-25 | 25 | 0.24 | -0.236 | -0.83 to 0.41 | 0.70 | -331 |
| Fold 4: 2023-12-25 to 2024-06-22 | 53 | 0.28 | -0.110 | -0.53 to 0.34 | 0.86 | -298 |
| Fold 5: 2024-06-22 to 2024-12-19 | 53 | 0.28 | -0.104 | -0.52 to 0.36 | 0.85 | -297 |
| Fold 6: 2024-12-19 to 2025-06-17 | 77 | 0.27 | -0.183 | -0.53 to 0.19 | 0.77 | -639 |
| **All test folds** | 307 | 0.26 | -0.200 | -0.37 to -0.02 | 0.74 | -3461 |

## By Year, Side and Candle

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| 2020 | 130 | 0.28 | -0.124 | -0.40 to 0.17 | 0.84 | -1451 |
| 2021 | 138 | 0.26 | -0.186 | -0.43 to 0.07 | 0.79 | -1862 |
| 2022 | 142 | 0.32 | 0.055 | -0.22 to 0.36 | 1.06 | 394 |
| 2023 | 63 | 0.21 | -0.441 | -0.76 to -0.09 | 0.48 | -1601 |
| 2024 | 105 | 0.30 | -0.070 | -0.38 to 0.25 | 0.90 | -411 |
| 2025 | 118 | 0.25 | -0.231 | -0.51 to 0.04 | 0.72 | -1163 |
| LONG | 428 | 0.26 | -0.210 | -0.36 to -0.06 | 0.76 | -5766 |
| SHORT | 268 | 0.30 | -0.024 | -0.23 to 0.18 | 0.97 | -328 |
| bearish_engulfing | 132 | 0.26 | -0.185 | -0.45 to 0.11 | 0.81 | -1248 |
| bearish_harami | 16 | 0.44 | 0.323 | -0.52 to 1.16 | 1.81 | 486 |
| bearish_marubozu | 10 | 0.30 | 0.053 | -1.06 to 1.17 | 0.74 | -134 |
| bullish_engulfing | 198 | 0.28 | -0.094 | -0.32 to 0.14 | 0.89 | -1209 |
| bullish_harami | 10 | 0.20 | -0.360 | -1.10 to 0.70 | 0.60 | -273 |
| bullish_marubozu | 15 | 0.13 | -0.603 | -1.10 to 0.15 | 0.28 | -696 |
| dark_cloud_cover | 12 | 0.00 | -1.099 | -1.12 to -1.08 | 0.00 | -740 |
| evening_star | 4 | 0.50 | 0.852 | -1.09 to 2.79 | 2.08 | 136 |
| hammer | 11 | 0.45 | 0.497 | -0.48 to 1.50 | 2.05 | 456 |
| hanging_man | 2 | 0.00 | -1.165 | -1.18 to -1.15 | 0.00 | -140 |
| morning_star | 4 | 0.25 | -0.255 | -1.12 to 1.43 | 0.45 | -98 |
| piercing_line | 24 | 0.33 | -0.003 | -0.60 to 0.69 | 1.08 | 86 |
| pin_bar | 193 | 0.26 | -0.203 | -0.42 to 0.02 | 0.74 | -2731 |
| shooting_star | 4 | 0.25 | -0.050 | -1.13 to 2.08 | 0.63 | -83 |
| three_black_crows | 2 | 0.50 | 1.440 | -1.05 to 3.93 | 3.56 | 174 |
| three_inside_down | 3 | 0.67 | 1.079 | -1.09 to 2.78 | 5.47 | 267 |
| three_inside_up | 2 | 1.00 | 3.215 | 2.65 to 3.78 | n/a | 517 |
| three_outside_down | 14 | 0.43 | 0.347 | -0.56 to 1.36 | 1.48 | 243 |
| three_outside_up | 20 | 0.25 | -0.258 | -0.81 to 0.45 | 0.71 | -341 |
| three_white_soldiers | 3 | 0.00 | -1.112 | -1.20 to -1.06 | 0.00 | -250 |
| tweezer_bottom | 7 | 0.14 | -0.573 | -1.13 to 0.51 | 0.30 | -291 |
| tweezer_top | 10 | 0.20 | -0.398 | -1.12 to 0.64 | 0.64 | -224 |

## Benchmarks

- Buy and hold, no costs: +2878.9% over the period.
- Random 1H closes where 4H and 1D agree, with this strategy's stops and targets, 20 seeds of about 817 trades: mean -0.063R, 5th to 95th percentile -0.137R to -0.008R. Strategy: -0.138R.

## Promotion Gate

| Gate | Required | Result | |
|---|---|---|---|
| Out-of-sample trades | At least 200 | 307 | Passed |
| Expectancy | Interval above zero | -0.37 to -0.02 | **Not met** |
| Profit factor at 1.5x costs | Above 1.2 | 0.70 | **Not met** |
| Positive folds | Most of 6 | 0 | **Not met** |
| Random benchmark | Above its 95th percentile | -0.200 | **Not met** |
| Nearby parameters | Similar results | Not tested | n/a |

## Limits

- One trial, nothing tuned. The holdout was not used (docs/31).
- Fills use 15M candles. Costs are conservative assumptions and funding is real.
- Several strategies have been tested on these years, so a borderline result is weak.
- BTC and ETH were chosen with hindsight.
