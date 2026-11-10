# Six-Coin Replication Study

Simulated results. A profitable backtest is not proof of future profitability.

Pre-registered in [33-COIN-REPLICATION.md](../33-COIN-REPLICATION.md) and run once. Period 2020-01-01, or the coin's first candle, to 2025-11-01, before the frozen holdout. Each coin is a separate 10,000 account at 1% risk per trade.

## pattern_breakout

| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Max drawdown | Expectancy at 2x costs | Note |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 162 | 0.34 | +0.136 | -0.13 to +0.42 | 1.17 | 10.9% | +0.066 | known before, docs/27 and docs/29 |
| ETHUSDT | 176 | 0.32 | +0.120 | -0.14 to +0.38 | 1.14 | 16.1% | +0.142 | known before, docs/27 and docs/29 |
| SOLUSDT | 87 | 0.28 | -0.016 | -0.36 to +0.36 | 0.96 | 18.7% | -0.080 |  |
| XRPUSDT | 108 | 0.34 | +0.225 | -0.13 to +0.61 | 1.29 | 12.7% | +0.191 |  |
| BNBUSDT | 132 | 0.28 | +0.026 | -0.29 to +0.33 | 1.02 | 21.2% | -0.007 |  |
| DOGEUSDT | 125 | 0.28 | -0.068 | -0.35 to +0.23 | 0.90 | 21.3% | -0.105 |  |
| **Four new coins** | 452 | 0.29 | +0.040 | -0.13 to +0.21 | 1.04 | n/a | -0.000 | pooled |
| **All six coins** | 790 | 0.31 | +0.077 | -0.04 to +0.20 | 1.09 | n/a | +0.045 | pooled |

## daily_trend

| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Max drawdown | Expectancy at 2x costs | Note |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 71 | 0.41 | +0.439 | -0.03 to +0.98 | 1.75 | 4.9% | +0.424 | known before, docs/27 and docs/29 |
| ETHUSDT | 68 | 0.41 | +0.372 | -0.07 to +0.89 | 1.68 | 7.5% | +0.360 | known before, docs/27 and docs/29 |
| SOLUSDT | 37 | 0.43 | +0.529 | -0.13 to +1.39 | 2.26 | 3.0% | +0.519 |  |
| XRPUSDT | 52 | 0.31 | +0.317 | -0.31 to +1.04 | 1.54 | 9.8% | +0.304 | seen before registration |
| BNBUSDT | 60 | 0.35 | +0.280 | -0.21 to +0.86 | 1.47 | 10.2% | +0.266 |  |
| DOGEUSDT | 56 | 0.34 | +0.487 | -0.18 to +1.29 | 2.06 | 6.0% | +0.477 |  |
| **Four new coins** | 205 | 0.35 | +0.391 | +0.07 to +0.74 | 1.75 | n/a | +0.379 | pooled |
| **All six coins** | 344 | 0.38 | +0.397 | +0.16 to +0.65 | 1.74 | n/a | +0.385 | pooled |

## Decision

Applied as pre-registered. A share is a fraction of the account's 1% risk per trade.

| Strategy | Share | Coins left out | Six coins, mean and interval | Four new coins, mean | Six coins at 2x costs, mean |
|---|---|---|---|---|---|
| pattern_breakout | 0.5 | none | +0.077, -0.04 to +0.20 | +0.040 | +0.045 |
| daily_trend | 1 | none | +0.397, +0.16 to +0.65 | +0.391 | +0.385 |
| trend_break_baseline (15M) | 0.25 | none | not testable before the holdout | n/a | n/a |

## Limits

- The six coins move together, so their trades are not independent and the pooled interval is narrower than it should be.
- The coins were chosen in 2026 from those still trading, so they are survivors.
- Pooled drawdown is not shown, because each coin ran as its own account.
- A pass is not proof of future profit.
