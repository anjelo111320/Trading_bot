# Pattern Breakout Holdout Run

Simulated results. A profitable backtest is not proof of future profitability.

The single holdout run for versions 1 and 2, 2025-11-01 to 2026-11-01 (D029, D037). Nothing was tuned on this year. Version 2 is version 1 plus no new trade when daily volatility is in the highest quarter of its year, a rule found in 2020 to 2025 data.

| Coin | Version | Costs | Trades | Win rate | Expectancy (R) | 95% interval | Profit factor | Net P/L | Max drawdown |
|---|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 1 | 1x | 23 | 0.35 | 0.295 | -0.50 to 1.14 | 1.42 | 635 | 4.8% |
| BTCUSDT | 1 | 2x | 23 | 0.35 | 0.137 | -0.61 to 0.95 | 1.19 | 288 | 4.8% |
| BTCUSDT | 2 | 1x | 22 | 0.32 | 0.168 | -0.59 to 1.08 | 1.22 | 332 | 5.8% |
| BTCUSDT | 2 | 2x | 22 | 0.32 | -0.004 | -0.71 to 0.85 | 1.01 | 8 | 5.7% |
| ETHUSDT | 1 | 1x | 23 | 0.22 | -0.325 | -0.89 to 0.35 | 0.61 | -700 | 8.7% |
| ETHUSDT | 1 | 2x | 23 | 0.22 | -0.372 | -0.94 to 0.31 | 0.58 | -753 | 8.8% |
| ETHUSDT | 2 | 1x | 18 | 0.22 | -0.328 | -0.92 to 0.45 | 0.60 | -558 | 8.7% |
| ETHUSDT | 2 | 2x | 18 | 0.22 | -0.378 | -0.97 to 0.41 | 0.57 | -603 | 8.7% |

Buy and hold over the same year, no costs: BTCUSDT -29.2%, ETHUSDT -41.4%.

## Limits

- One year and a few dozen trades per coin and version. This is far short of the 200 out-of-sample trades the promotion gate needs, so it is a check, not proof.
- This holdout is now spent for both versions. A changed strategy needs fresh data, normally from forward paper trading.
- Fills use 15M candles, costs are conservative assumptions, and BTC and ETH were chosen with hindsight.
