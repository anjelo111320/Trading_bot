# 4H Gap and 15M CHoCH Study

Simulated results. A profitable backtest is not proof of future profitability.

Strategy `fvg_choch` version 1, pre-registered in [35-FVG-CHOCH-STRATEGY.md](../35-FVG-CHOCH-STRATEGY.md) and run once. Period 2020-01-01, or the coin's first candle, to 2025-11-01, before the frozen holdout. Each coin is a separate 10,000 account at 1% risk per trade. Fills use 15M candles.

## By Coin, Normal Costs

| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Max drawdown | Expectancy at 2x costs |
|---|---|---|---|---|---|---|---|
| BTCUSDT | 26 | 0.46 | +0.547 | -0.12 to +1.22 | 1.88 | 4.7% | -0.105 |
| ETHUSDT | 52 | 0.29 | -0.132 | -0.52 to +0.31 | 0.82 | 12.2% | -0.372 |
| SOLUSDT | 34 | 0.38 | +0.229 | -0.35 to +0.81 | 1.29 | 5.3% | +0.341 |
| XRPUSDT | 41 | 0.20 | -0.429 | -0.82 to +0.01 | 0.49 | 15.3% | -0.791 |
| BNBUSDT | 40 | 0.40 | +0.260 | -0.25 to +0.79 | 1.37 | 5.8% | -0.169 |
| DOGEUSDT | 62 | 0.29 | -0.045 | -0.41 to +0.39 | 0.95 | 6.4% | +0.235 |

## Pooled

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Six coins at 1x costs | 255 | 0.32 | +0.020 | -0.18 to +0.23 | 1.03 | 464 |
| Six coins at 1.5x costs | 195 | 0.30 | -0.065 | -0.30 to +0.17 | 0.93 | -945 |
| Six coins at 2x costs | 156 | 0.29 | -0.144 | -0.38 to +0.11 | 0.85 | -1597 |
| SOL, XRP, BNB and DOGE at 1x costs | 177 | 0.31 | -0.012 | -0.24 to +0.24 | 0.98 | -230 |

Signals that reached the risk engine: 1602. Filled trades: 255. Exits: stop 187, tp3 37, tp2 16, tp1 15.

## Funnel

Every 15M CHoCH in the window, on all six coins, and what the strategy decided there.

| What happened at a CHoCH | Count |
|---|---|
| CHoCH against the 4H trend | 22152 |
| the pullback did not reach an open 4H gap | 16405 |
| proposed | 1634 |
| no open 15M gap in the move | 1580 |
| no reachable target | 193 |

Risk engine rejections: RR_BELOW_MIN 752, EXPOSURE_EXCEEDED 712, SPREAD_TOO_WIDE 237.

## Walk-Forward Test Folds, Six Coins Pooled

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| Fold 1: 2022-07-03 to 2022-12-30 | 19 | 0.47 | 0.597 | -0.22 to 1.42 | 2.05 | 1018 |
| Fold 2: 2022-12-30 to 2023-06-28 | 14 | 0.29 | -0.022 | -0.84 to 0.85 | 0.97 | -29 |
| Fold 3: 2023-06-28 to 2023-12-25 | 9 | 0.44 | 0.499 | -0.70 to 1.70 | 1.83 | 405 |
| Fold 4: 2023-12-25 to 2024-06-22 | 17 | 0.41 | 0.333 | -0.47 to 1.16 | 1.54 | 542 |
| Fold 5: 2024-06-22 to 2024-12-19 | 23 | 0.17 | -0.571 | -0.97 to -0.06 | 0.36 | -1224 |
| Fold 6: 2024-12-19 to 2025-06-17 | 21 | 0.33 | 0.092 | -0.61 to 0.88 | 1.14 | 192 |
| **All test folds** | 103 | 0.34 | 0.097 | -0.22 to 0.42 | 1.14 | 904 |

## By Year and Side, Six Coins Pooled

| | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L |
|---|---|---|---|---|---|---|
| 2020 | 18 | 0.44 | +0.457 | -0.31 to +1.31 | 1.75 | 748 |
| 2021 | 84 | 0.32 | -0.015 | -0.37 to +0.34 | 0.98 | -100 |
| 2022 | 45 | 0.36 | +0.173 | -0.30 to +0.71 | 1.25 | 694 |
| 2023 | 25 | 0.36 | +0.223 | -0.50 to +0.94 | 1.34 | 531 |
| 2024 | 39 | 0.26 | -0.256 | -0.67 to +0.20 | 0.68 | -933 |
| 2025 | 44 | 0.27 | -0.117 | -0.54 to +0.40 | 0.85 | -477 |
| LONG | 130 | 0.37 | +0.168 | -0.13 to +0.46 | 1.26 | 2094 |
| SHORT | 125 | 0.27 | -0.133 | -0.40 to +0.15 | 0.82 | -1630 |

## Benchmark

Random 15M closes where the 4H trend is up or down, entering at market in that direction with this strategy's stops and targets, 20 seeds of about 666 trades pooled across the coins: mean -0.075R, 5th to 95th percentile -0.185R to +0.089R. Strategy: +0.020R.

## Promotion Gate from docs/27, Reported Only

| Gate | Required | Result | |
|---|---|---|---|
| Out-of-sample trades | At least 200 | 103 | **Not met** |
| Expectancy | Interval above zero | -0.22 to 0.42 | **Not met** |
| Profit factor at 1.5x costs | Above 1.2 | 1.02 | **Not met** |
| Positive folds | Most of 6 | 4 | Passed |
| Random benchmark | Above its 95th percentile | 0.097 | Passed |
| Nearby parameters | Similar results | Not tested | n/a |

## Decision

Pooled six-coin expectancy +0.020R is above zero. It joins the money plan at a share of **0.5** of the 1% risk (docs/33 rule: interval -0.18 to +0.23, four coins pooled -0.012R, 2x costs -0.144R).

Coins left out, lost with 95% confidence: none.

## Limits

- One trial, nothing tuned. The holdout was not used.
- Fills use 15M candles. A stop and a target in one candle count as the stop, and a target in the candle where the limit fills is not counted.
- Limit fills pay the maker fee and no spread, while the benchmark's market entries pay the taker fee, spread and slippage.
- The six coins move together, they are survivors, and several strategies have been tested on these years.
