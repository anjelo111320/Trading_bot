# New Coins and the 15M Rule Study

Simulated results. A profitable backtest is not proof of future profitability.

Pre-registered in [42-NEW-COIN-STUDY.md](../42-NEW-COIN-STUDY.md) and run once. Each coin is a separate 10,000 account at 1% risk per trade.

## Part A: tested strategies on the new coins, 2020-01-01 or the first candle to 2025-11-01

### daily_trend

| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Max drawdown | Expectancy at 2x costs | Note |
|---|---|---|---|---|---|---|---|---|
| ZECUSDT | 52 | 0.31 | +0.156 | -0.34 to +0.79 | 1.33 | 12.6% | +0.145 | added untested |
| 1000PEPEUSDT | 36 | 0.31 | +0.360 | -0.35 to +1.27 | 1.68 | 4.4% | +0.354 | added untested |
| HYPEUSDT | 6 | 0.00 | -0.644 | -0.91 to -0.37 | 0.00 | 3.8% | -0.652 | added untested, lost with 95% confidence |
| NEARUSDT | 32 | 0.41 | -0.139 | -0.43 to +0.16 | 0.67 | 5.1% | -0.148 | added untested |
| **4 coins pooled** | 126 | 0.32 | +0.101 | -0.21 to +0.48 | 1.20 | n/a | +0.092 | pooled |

### pattern_breakout

| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Max drawdown | Expectancy at 2x costs | Note |
|---|---|---|---|---|---|---|---|---|
| ZECUSDT | 82 | 0.30 | +0.035 | -0.31 to +0.41 | 1.02 | 16.0% | -0.023 | added untested |
| 1000PEPEUSDT | 45 | 0.40 | +0.459 | -0.10 to +1.10 | 1.69 | 5.8% | +0.397 | added untested |
| HYPEUSDT | 13 | 0.08 | -0.786 | -1.05 to -0.28 | 0.17 | 9.6% | -0.798 | added untested, lost with 95% confidence |
| NEARUSDT | 67 | 0.24 | -0.105 | -0.49 to +0.33 | 0.84 | 15.5% | -0.131 | added untested |
| **4 coins pooled** | 207 | 0.29 | +0.030 | -0.20 to +0.27 | 1.04 | n/a | -0.013 | pooled |

### fvg_choch

| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Max drawdown | Expectancy at 2x costs | Note |
|---|---|---|---|---|---|---|---|---|
| ZECUSDT | 56 | 0.36 | +0.077 | -0.32 to +0.50 | 1.10 | 8.8% | +0.047 | added untested |
| 1000PEPEUSDT | 56 | 0.25 | -0.185 | -0.57 to +0.25 | 0.75 | 18.2% | -0.275 | added untested |
| HYPEUSDT | 9 | 0.33 | -0.039 | -0.89 to +1.05 | 0.88 | 2.9% | -0.161 | added untested |
| NEARUSDT | 41 | 0.44 | +0.478 | -0.08 to +1.03 | 1.79 | 5.6% | +0.245 | added untested |
| **4 coins pooled** | 162 | 0.34 | +0.082 | -0.17 to +0.33 | 1.12 | n/a | -0.028 | pooled |

## Part B: the 15M rule on all ten coins, 2023-11-01 or the first candle to 2025-11-01, on 15-minute fills

### trend_break_baseline

| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Max drawdown | Expectancy at 2x costs | Note |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 113 | 0.30 | -0.013 | -0.32 to +0.32 | 0.97 | 15.3% | -0.229 |  |
| ETHUSDT | 170 | 0.29 | -0.082 | -0.32 to +0.17 | 0.87 | 17.4% | -0.084 |  |
| SOLUSDT | 212 | 0.29 | -0.047 | -0.28 to +0.19 | 0.93 | 26.8% | +0.050 |  |
| XRPUSDT | 175 | 0.29 | -0.101 | -0.35 to +0.15 | 0.86 | 21.9% | -0.178 |  |
| BNBUSDT | 115 | 0.26 | -0.190 | -0.46 to +0.11 | 0.77 | 23.8% | -0.273 |  |
| DOGEUSDT | 216 | 0.30 | -0.038 | -0.25 to +0.18 | 0.93 | 19.8% | -0.054 |  |
| ZECUSDT | 84 | 0.30 | +0.000 | -0.33 to +0.35 | 0.99 | 10.0% | -0.043 | added untested |
| 1000PEPEUSDT | 245 | 0.33 | +0.094 | -0.12 to +0.31 | 1.13 | 17.0% | +0.035 | added untested |
| HYPEUSDT | 58 | 0.24 | -0.238 | -0.60 to +0.18 | 0.71 | 17.4% | -0.306 | added untested |
| NEARUSDT | 110 | 0.31 | -0.039 | -0.33 to +0.26 | 0.92 | 17.4% | -0.218 | added untested |
| **10 coins pooled** | 1498 | 0.30 | -0.046 | -0.13 to +0.04 | 0.93 | n/a | -0.091 | pooled |

### trend_break_loose

| Coin | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Max drawdown | Expectancy at 2x costs | Note |
|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 158 | 0.32 | +0.008 | -0.25 to +0.27 | 0.99 | 15.5% | -0.179 |  |
| ETHUSDT | 235 | 0.27 | -0.144 | -0.35 to +0.07 | 0.81 | 30.9% | -0.217 |  |
| SOLUSDT | 290 | 0.28 | -0.109 | -0.29 to +0.08 | 0.86 | 39.2% | -0.151 |  |
| XRPUSDT | 235 | 0.30 | -0.091 | -0.29 to +0.13 | 0.87 | 28.5% | -0.143 |  |
| BNBUSDT | 169 | 0.26 | -0.189 | -0.43 to +0.06 | 0.76 | 26.0% | -0.120 |  |
| DOGEUSDT | 319 | 0.27 | -0.178 | -0.35 to -0.01 | 0.76 | 44.0% | -0.197 | lost with 95% confidence |
| ZECUSDT | 111 | 0.31 | -0.010 | -0.29 to +0.27 | 0.97 | 13.7% | -0.138 | added untested |
| 1000PEPEUSDT | 349 | 0.32 | +0.009 | -0.16 to +0.19 | 1.00 | 33.9% | -0.063 | added untested |
| HYPEUSDT | 86 | 0.20 | -0.413 | -0.69 to -0.11 | 0.54 | 30.3% | -0.554 | added untested, lost with 95% confidence |
| NEARUSDT | 143 | 0.27 | -0.150 | -0.41 to +0.13 | 0.78 | 22.4% | -0.192 | added untested |
| **10 coins pooled** | 2095 | 0.28 | -0.109 | -0.18 to -0.04 | 0.85 | n/a | -0.169 | pooled |

## Decision

Applied as pre-registered.

- Left out, lost with 95% confidence: daily_trend on HYPEUSDT, pattern_breakout on HYPEUSDT, trend_break_loose on DOGEUSDT, trend_break_loose on HYPEUSDT.
- Recommended to the owner to switch off on every coin, ten-coin interval below zero: trend_break_loose.
- Mean below zero, interval includes zero, still trading: daily_trend on NEARUSDT, pattern_breakout on NEARUSDT, fvg_choch on 1000PEPEUSDT, fvg_choch on HYPEUSDT, trend_break_baseline on BTCUSDT, trend_break_baseline on ETHUSDT, trend_break_baseline on SOLUSDT, trend_break_baseline on XRPUSDT, trend_break_baseline on BNBUSDT, trend_break_baseline on DOGEUSDT, trend_break_baseline on HYPEUSDT, trend_break_baseline on NEARUSDT, trend_break_loose on ETHUSDT, trend_break_loose on SOLUSDT, trend_break_loose on XRPUSDT, trend_break_loose on BNBUSDT, trend_break_loose on ZECUSDT, trend_break_loose on NEARUSDT.

## Limits

- HYPE has 5 months of history before the holdout, so its results are weak.
- Part B fills on 15-minute candles, coarser than the 1-minute fills the 15M rule needs.
- The coins move together, so pooled intervals are narrower than they should be.
- The new coins were chosen in 2026 because they were trending then.
- A pass is not proof of future profit.
