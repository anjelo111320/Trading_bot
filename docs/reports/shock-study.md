# Crash Warning Study

Simulated results. A profitable backtest is not proof of future profitability.

Pre-registered in [32-SHOCK-STUDY.md](../32-SHOCK-STUDY.md), run once, on history from 2020-01-01 or listing to 2025-11-01, before the frozen holdout. A down warning is a 1H close below the 12-candle low, on volume at least 2 times its 24-candle mean, with takers selling at least 55%. A large fall ahead is a low at least 6 ATR below the close within 6 candles.

## Warning Quality

| | 1H closes | Large fall ahead | Warnings | Per month | Precision | Lift | Random 95th | Episodes caught | Fall still ahead, median |
|---|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 51138 | 1.59% | 540 | 7.7 | 5.0% | 3.2 | 3.0% | 23 of 243 | 79% |
| ETHUSDT | 51138 | 1.61% | 559 | 8.0 | 7.2% | 4.5 | 2.5% | 33 of 227 | 78% |
| SOLUSDT | 44949 | 1.00% | 385 | 6.3 | 3.4% | 3.4 | 1.8% | 10 of 133 | 82% |
| XRPUSDT | 50996 | 1.73% | 578 | 8.3 | 7.1% | 4.1 | 2.4% | 35 of 265 | 81% |
| BNBUSDT | 50156 | 1.55% | 523 | 7.6 | 6.3% | 4.1 | 2.3% | 30 of 237 | 80% |
| DOGEUSDT | 46531 | 1.47% | 499 | 7.8 | 4.8% | 3.3 | 2.0% | 20 of 194 | 82% |
| **Pooled** | 294908 | 1.50% | 3084 | 7.6 | 5.8% | 3.8 | 1.8% | 151 of 1299 | 81% |

## Sensitivity, Not Used for the Decision

| | 1H closes | Large fall ahead | Warnings | Per month | Precision | Lift | Random 95th | Episodes caught | Fall still ahead, median |
|---|---|---|---|---|---|---|---|---|---|
| Volume 1.5x, pooled | 294908 | 1.50% | 4351 | 10.8 | 5.2% | 3.5 | 1.8% | 183 of 1299 | 82% |
| Volume 3x, pooled | 294908 | 1.50% | 1572 | 3.9 | 7.5% | 5.0 | 1.9% | 106 of 1299 | 78% |

## Filter Value

Long trades whose signal came within 12 hours after a down warning are the ones the filter would skip.

| Backtest | Skipped longs | Their mean | Other trades | Their mean |
|---|---|---|---|---|
| Pattern breakout, trial 1 | 10 | -0.603R | 780 | +0.100R |
| Daily trend | 0 | n/a | 345 | +0.437R |

## Decision Rule

| Condition | Result |
|---|---|
| Precision above the random 95th percentile | Met |
| Lift at least 2 | Met |
| Skipped pattern longs lost on average | Met |
| Skipped daily trend longs lost on average | **Not met** |

Decision: **not adopted**. The result is recorded and nothing changes.
