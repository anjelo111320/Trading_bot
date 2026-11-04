# Daily Trend Backtest: BTCUSDT Perpetual

Simulated results. A profitable backtest is not proof of future profitability.

Strategy `daily_trend` version 1, the Turtle System 1 rules, registered before any run in [29-TREND-STRATEGY.md](../29-TREND-STRATEGY.md). Period 2020-01-01 to 2025-11-01, before the frozen holdout.

## Normal Costs

| Metric | Value |
|---|---|
| Trades | 71 |
| Net P/L after costs | 3857.45 |
| Total return | 38.57% |
| Win rate | 0.408 |
| Expectancy (R) | 0.498 |
| 95% interval for expectancy | 0.013 to 1.065 |
| Profit factor | 1.844 |
| Maximum drawdown | 5.02% |
| Sharpe (daily, 365 days, no risk-free rate) | 0.719 |
| Sortino | 2.611 |
| Cost share of gross profit | 0.042 |

Signals that reached the risk engine: 71. Exits: stop 69, tp1 2. A stop exit includes the trailing stop.

## Costs

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| 1x costs | 71 | 0.41 | 0.498 | 0.01 to 1.07 | 1.84 | 3857 |
| 2x costs | 71 | 0.41 | 0.483 | -0.00 to 1.05 | 1.80 | 3632 |

## Walk-Forward Test Folds

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Fold 1: 2022-07-03 to 2022-12-30 | 6 | 0.33 | -0.280 | -0.80 to 0.32 | 0.40 | -218 |
| Fold 2: 2022-12-30 to 2023-06-28 | 7 | 0.43 | 0.858 | -0.72 to 3.22 | 2.48 | 749 |
| Fold 3: 2023-06-28 to 2023-12-25 | 5 | 0.20 | 0.183 | -0.82 to 1.81 | 1.35 | 117 |
| Fold 4: 2023-12-25 to 2024-06-22 | 6 | 0.33 | 0.381 | -0.99 to 2.73 | 1.54 | 288 |
| Fold 5: 2024-06-22 to 2024-12-19 | 8 | 0.38 | 0.209 | -0.80 to 1.66 | 1.36 | 205 |
| Fold 6: 2024-12-19 to 2025-06-17 | 5 | 0.40 | -0.077 | -0.90 to 0.81 | 0.82 | -63 |
| **All test folds** | 37 | 0.35 | 0.238 | -0.35 to 0.91 | 1.41 | 1077 |

## By Year and Direction

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| 2020 | 11 | 0.55 | 2.370 | 0.23 to 4.81 | 7.09 | 2764 |
| 2021 | 11 | 0.45 | 0.113 | -0.59 to 0.90 | 1.23 | 155 |
| 2022 | 12 | 0.50 | 0.114 | -0.38 to 0.68 | 1.32 | 168 |
| 2023 | 12 | 0.33 | 0.577 | -0.55 to 2.08 | 2.04 | 866 |
| 2024 | 14 | 0.36 | 0.283 | -0.74 to 1.68 | 1.45 | 492 |
| 2025 | 11 | 0.27 | -0.384 | -0.87 to 0.17 | 0.40 | -588 |
| LONG | 42 | 0.45 | 0.946 | 0.13 to 1.92 | 2.80 | 4573 |
| SHORT | 29 | 0.34 | -0.152 | -0.48 to 0.23 | 0.65 | -715 |

## Benchmarks

- Buy and hold, no costs: +1423.9%.
- Random days and directions with the same stops and exit, 20 seeds: mean 0.140R, 5th to 95th percentile -0.119R to 0.389R. Strategy: 0.498R.

## Limits

- One trial, nothing tuned. The holdout was not used (docs/29).
- Fills use 15M candles. Costs are conservative assumptions and funding is real.
- Few, fat-tailed trades: intervals are wide.
- BTC and ETH were chosen with hindsight.
