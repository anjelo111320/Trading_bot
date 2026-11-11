# News Move Strategy: Price Rules Alone

Context for docs/40, not a test of the strategy: no news check, because there is no
labelled news history. Window 2020-01-01 to 2025-11-01. Simulated results.

| Coin | Trades | Mean R | Win rate | Mean R at stressed costs |
|---|---|---|---|---|
| BTCUSDT | 780 | -0.047 | 35% | -0.115 |
| ETHUSDT | 1073 | +0.088 | 38% | -0.125 |
| SOLUSDT | 601 | +0.040 | 37% | +0.030 |
| XRPUSDT | 538 | +0.004 | 36% | -0.021 |
| BNBUSDT | 741 | +0.005 | 35% | -0.020 |
| DOGEUSDT | 822 | -0.015 | 35% | -0.110 |

Pooled, normal costs: 4555 trades, mean +0.017R, 95% interval -0.028 to +0.059.
Pooled, stressed costs: 1114 trades, mean -0.060R, 95% interval -0.148 to +0.027.
