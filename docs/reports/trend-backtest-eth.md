# Daily Trend Backtest: ETHUSDT Perpetual

Simulated results. A profitable backtest is not proof of future profitability.

Strategy `daily_trend` version 1, the Turtle System 1 rules, registered before any run in [29-TREND-STRATEGY.md](../29-TREND-STRATEGY.md). Period 2020-01-01 to 2025-11-01, before the frozen holdout.

## Normal Costs

| Metric | Value |
|---|---|
| Trades | 68 |
| Net P/L after costs | 3389.97 |
| Total return | 33.90% |
| Win rate | 0.412 |
| Expectancy (R) | 0.460 |
| 95% interval for expectancy | -0.022 to 1.025 |
| Profit factor | 1.851 |
| Maximum drawdown | 7.29% |
| Sharpe (daily, 365 days, no risk-free rate) | 0.687 |
| Sortino | 2.474 |
| Cost share of gross profit | 0.042 |

Signals that reached the risk engine: 68. Exits: stop 66, tp1 2. A stop exit includes the trailing stop.

## Costs

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| 1x costs | 68 | 0.41 | 0.460 | -0.02 to 1.02 | 1.85 | 3390 |
| 2x costs | 68 | 0.41 | 0.448 | -0.03 to 1.01 | 1.82 | 3242 |

## Walk-Forward Test Folds

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Fold 1: 2022-07-03 to 2022-12-30 | 7 | 0.29 | -0.269 | -0.80 to 0.34 | 0.46 | -256 |
| Fold 2: 2022-12-30 to 2023-06-28 | 6 | 0.33 | -0.016 | -0.88 to 1.18 | 0.95 | -21 |
| Fold 3: 2023-06-28 to 2023-12-25 | 6 | 0.17 | -0.188 | -1.02 to 1.21 | 0.72 | -156 |
| Fold 4: 2023-12-25 to 2024-06-22 | 6 | 0.50 | 0.398 | -0.67 to 1.84 | 1.95 | 303 |
| Fold 5: 2024-06-22 to 2024-12-19 | 5 | 0.40 | 0.121 | -0.81 to 1.23 | 1.26 | 77 |
| Fold 6: 2024-12-19 to 2025-06-17 | 7 | 0.43 | -0.041 | -0.62 to 0.56 | 0.89 | -42 |
| **All test folds** | 37 | 0.35 | -0.011 | -0.38 to 0.42 | 0.96 | -96 |

## By Year and Direction

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| 2020 | 11 | 0.55 | 2.267 | 0.07 to 4.83 | 6.69 | 2646 |
| 2021 | 10 | 0.50 | 0.438 | -0.21 to 1.14 | 2.66 | 552 |
| 2022 | 10 | 0.40 | 0.214 | -0.60 to 1.47 | 1.44 | 262 |
| 2023 | 12 | 0.25 | -0.102 | -0.83 to 0.76 | 0.82 | -178 |
| 2024 | 12 | 0.42 | 0.225 | -0.48 to 1.09 | 1.52 | 340 |
| 2025 | 13 | 0.38 | -0.129 | -0.69 to 0.53 | 0.75 | -233 |
| LONG | 38 | 0.55 | 1.019 | 0.26 to 1.97 | 3.50 | 4368 |
| SHORT | 30 | 0.23 | -0.249 | -0.61 to 0.21 | 0.56 | -978 |

## Benchmarks

- Buy and hold, no costs: +2878.9%.
- Random days and directions with the same stops and exit, 20 seeds: mean 0.200R, 5th to 95th percentile -0.060R to 0.519R. Strategy: 0.460R.

## Limits

- One trial, nothing tuned. The holdout was not used (docs/29).
- Fills use 15M candles. Costs are conservative assumptions and funding is real.
- Few, fat-tailed trades: intervals are wide.
- BTC and ETH were chosen with hindsight.
