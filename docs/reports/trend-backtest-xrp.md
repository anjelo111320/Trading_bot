# Daily Trend Backtest: XRPUSDT Perpetual

Simulated results. A profitable backtest is not proof of future profitability.

Strategy `daily_trend` version 1, the Turtle System 1 rules, registered before any run in [29-TREND-STRATEGY.md](../29-TREND-STRATEGY.md). Period 2020-01-01 to 2025-11-01, before the frozen holdout.

## Normal Costs

| Metric | Value |
|---|---|
| Trades | 52 |
| Net P/L after costs | 1753.46 |
| Total return | 17.53% |
| Win rate | 0.327 |
| Expectancy (R) | 0.347 |
| 95% interval for expectancy | -0.286 to 1.073 |
| Profit factor | 1.604 |
| Maximum drawdown | 9.67% |
| Sharpe (daily, 365 days, no risk-free rate) | 0.398 |
| Sortino | 1.515 |
| Cost share of gross profit | 0.029 |

Signals that reached the risk engine: 94. Exits: stop 49, tp1 3. A stop exit includes the trailing stop.

## Costs

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| 1x costs | 52 | 0.33 | 0.347 | -0.29 to 1.07 | 1.60 | 1753 |
| 2x costs | 52 | 0.33 | 0.334 | -0.30 to 1.06 | 1.57 | 1656 |

## Walk-Forward Test Folds

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Fold 1: 2022-07-03 to 2022-12-30 | 3 | 0.67 | -0.125 | -1.02 to 0.54 | 0.63 | -41 |
| Fold 2: 2022-12-30 to 2023-06-28 | 5 | 0.00 | -0.448 | -0.79 to -0.16 | 0.00 | -237 |
| Fold 3: 2023-06-28 to 2023-12-25 | 5 | 0.40 | -0.067 | -0.96 to 0.95 | 0.87 | -38 |
| Fold 4: 2023-12-25 to 2024-06-22 | 4 | 0.25 | -0.739 | -1.04 to -0.19 | 0.03 | -305 |
| Fold 5: 2024-06-22 to 2024-12-19 | 10 | 0.30 | 1.508 | -0.71 to 4.53 | 3.59 | 1537 |
| Fold 6: 2024-12-19 to 2025-06-17 | 5 | 0.20 | -0.458 | -0.86 to 0.13 | 0.22 | -267 |
| **All test folds** | 32 | 0.28 | 0.215 | -0.53 to 1.24 | 1.34 | 648 |

## By Year and Direction

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| 2020 | 2 | 0.00 | -1.018 | -1.02 to -1.01 | 0.00 | -198 |
| 2021 | 12 | 0.42 | 0.675 | -0.58 to 2.63 | 2.29 | 763 |
| 2022 | 6 | 0.67 | 0.541 | -0.54 to 1.86 | 2.70 | 335 |
| 2023 | 10 | 0.20 | -0.258 | -0.74 to 0.29 | 0.48 | -276 |
| 2024 | 14 | 0.29 | 0.866 | -0.78 to 3.17 | 2.36 | 1232 |
| 2025 | 8 | 0.25 | -0.102 | -0.72 to 0.75 | 0.78 | -103 |
| LONG | 32 | 0.31 | 0.594 | -0.42 to 1.83 | 1.92 | 1872 |
| SHORT | 20 | 0.35 | -0.049 | -0.47 to 0.46 | 0.86 | -118 |

## Benchmarks

- Buy and hold, no costs: +1173.1%.
- Random days and directions with the same stops and exit, 20 seeds: mean 0.161R, 5th to 95th percentile -0.118R to 0.520R. Strategy: 0.347R.

## Limits

- One trial, nothing tuned. The holdout was not used (docs/29).
- Fills use 15M candles. Costs are conservative assumptions and funding is real.
- Few, fat-tailed trades: intervals are wide.
- BTC and ETH were chosen with hindsight.
