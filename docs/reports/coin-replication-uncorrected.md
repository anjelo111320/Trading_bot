# Six-Coin Replication Study

Simulated results. A profitable backtest is not proof of future profitability.

Pre-registered in [33-COIN-REPLICATION.md](../33-COIN-REPLICATION.md) and run once. Period 2020-01-01, or the coin's first candle, to 2025-11-01, before the frozen holdout. Each coin is a separate 10,000 account at 1% risk per trade.

## pattern_breakout

| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Max drawdown | Expectancy at 2x costs | Note |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 162 | 0.34 | +0.159 | -0.11 to +0.44 | 1.20 | 10.5% | +0.088 | known before, docs/27 and docs/29 |
| ETHUSDT | 176 | 0.32 | +0.139 | -0.12 to +0.40 | 1.16 | 15.1% | +0.162 | known before, docs/27 and docs/29 |
| SOLUSDT | 87 | 0.28 | -0.012 | -0.36 to +0.37 | 0.97 | 18.6% | -0.076 |  |
| XRPUSDT | 108 | 0.34 | +0.232 | -0.13 to +0.62 | 1.30 | 12.7% | +0.198 |  |
| BNBUSDT | 132 | 0.28 | +0.047 | -0.27 to +0.35 | 1.04 | 20.8% | +0.012 |  |
| DOGEUSDT | 125 | 0.28 | -0.065 | -0.35 to +0.24 | 0.91 | 21.4% | -0.102 |  |
| **Four new coins** | 452 | 0.29 | +0.049 | -0.12 to +0.22 | 1.06 | n/a | +0.009 | pooled |
| **All six coins** | 790 | 0.31 | +0.091 | -0.03 to +0.22 | 1.11 | n/a | +0.059 | pooled |

## daily_trend

| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Max drawdown | Expectancy at 2x costs | Note |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 71 | 0.41 | +0.498 | +0.01 to +1.07 | 1.84 | 5.0% | +0.483 | known before, docs/27 and docs/29 |
| ETHUSDT | 68 | 0.41 | +0.460 | -0.02 to +1.02 | 1.85 | 7.3% | +0.448 | known before, docs/27 and docs/29 |
| SOLUSDT | 37 | 0.43 | +0.547 | -0.11 to +1.41 | 2.31 | 3.0% | +0.537 |  |
| XRPUSDT | 52 | 0.33 | +0.347 | -0.29 to +1.07 | 1.60 | 9.7% | +0.334 | seen before registration |
| BNBUSDT | 60 | 0.33 | +0.315 | -0.18 to +0.92 | 1.53 | 10.2% | +0.301 |  |
| DOGEUSDT | 56 | 0.34 | +0.497 | -0.17 to +1.30 | 2.10 | 5.7% | +0.487 |  |
| **Four new coins** | 205 | 0.35 | +0.415 | +0.09 to +0.77 | 1.81 | n/a | +0.403 | pooled |
| **All six coins** | 344 | 0.38 | +0.441 | +0.20 to +0.70 | 1.82 | n/a | +0.428 | pooled |

## Decision

Applied as pre-registered. A share is a fraction of the account's 1% risk per trade.

| Strategy | Share | Coins left out | Six coins, mean and interval | Four new coins, mean | Six coins at 2x costs, mean |
|---|---|---|---|---|---|
| pattern_breakout | 0.5 | none | +0.091, -0.03 to +0.22 | +0.049 | +0.059 |
| daily_trend | 1 | none | +0.441, +0.20 to +0.70 | +0.415 | +0.428 |
| trend_break_baseline (15M) | 0.25 | none | not testable before the holdout | n/a | n/a |

## Limits

- The six coins move together, so their trades are not independent and the pooled interval is narrower than it should be.
- The coins were chosen in 2026 from those still trading, so they are survivors.
- Pooled drawdown is not shown, because each coin ran as its own account.
- A pass is not proof of future profit.
