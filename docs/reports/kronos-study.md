# Kronos Forecast Track Record

Generated 2026-11-05 07:31 UTC by `trading_intel.entrypoints.forecast report --reasons study`. Model: NeoQuasar/Kronos-small at 901c26c, 30 paths, 24 1H candles ahead. Baseline: time machine version 1, 10,000 paths resampled from the coin's last 60 days. Personal research data (D006).

**Resolved forecasts: 104. Status: worse than baseline.** The status needs at least 100 forecasts, and turns "better than baseline" only when both scores below favour Kronos with 95% confidence.

## Direction

Each forecast says what share of its paths end higher after 24 hours. The Brier score measures how far that share was from what happened: 0 is perfect, and always saying 50% scores 0.25.

| | Kronos | Baseline | Always 50% |
|---|---|---|---|
| Brier score | 0.393 | 0.252 | 0.250 |

Kronos minus baseline: +0.140, 95% interval +0.063 to +0.220. Below zero favours Kronos.

| Kronos said, share ending higher | Forecasts | Average said | Actually ended higher |
|---|---|---|---|
| 0% to 20% | 46 | 6% | 43% |
| 20% to 40% | 13 | 28% | 69% |
| 40% to 60% | 13 | 50% | 38% |
| 60% to 80% | 4 | 70% | 50% |
| 80% to 100% | 28 | 99% | 54% |

## Range

How often the real value fell inside each forecast's 10th to 90th percentile band. An honest band holds it 80% of the time. Less means the forecast was overconfident.

| Measure | Kronos | Baseline | Honest band |
|---|---|---|---|
| Highest price | 36% | 81% | 80% |
| Lowest price | 38% | 73% | 80% |
| Close after 24 hours | 24% | 79% | 80% |

## Whole Distribution

The continuous ranked probability score of the 24-hour close, in percent of price. Lower is better.

| | Kronos | Baseline |
|---|---|---|
| CRPS | 2.397% | 1.480% |

Kronos minus baseline: +0.917, 95% interval +0.513 to +1.284 percentage points.

Where each real close fell among the forecast's closes, in tenths. A calibrated forecast spreads evenly. Piles at both ends mean bands that are too narrow.

| Tenth | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| Kronos | 33 | 3 | 1 | 3 | 3 | 4 | 4 | 3 | 4 | 46 |
| Baseline | 10 | 12 | 11 | 10 | 9 | 10 | 8 | 12 | 10 | 12 |

## By Coin

| Coin | Forecasts | Brier, Kronos | Brier, baseline | CRPS, Kronos | CRPS, baseline |
|---|---|---|---|---|---|
| BTCUSDT | 52 | 0.431 | 0.251 | 2.107% | 1.074% |
| ETHUSDT | 52 | 0.354 | 0.254 | 2.688% | 1.887% |

## Limits

- Kronos samples 30 paths, so its shares move in steps of about 3% and its tails are rough. The baseline samples 10,000.
- The intervals assume forecasts are independent. Forecasts whose 24 hours overlap are not, which makes the intervals too narrow.
- Study days are new to the model, whose weights were last changed on 2025-09-09. Days before that may be in its training data and are never used.
- A score that favours Kronos still says nothing about profit after costs.
