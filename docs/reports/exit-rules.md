# Exit Rules Study

Simulated results. A profitable backtest is not proof of future profitability.

Pre-registered in [37-EXIT-RULES.md](../37-EXIT-RULES.md) and run once. Period 2020-01-01, or the coin's first candle, to 2025-11-01, before the frozen holdout. Each coin is a separate 10,000 account at 1% risk per trade. Fills use 15M candles. Every change is in R per trade, a rule's result minus the strategy's own exits on the same entry.

Replay check: 2646 trades replayed with no rule, 0 different from the backtest engine.

## daily_trend

| Rule | Trades | Rule acted on | Own exits (R) | With the rule (R) | Change | 95% interval | 99.4% interval | Change at 2x costs | Change, four coins | Passes |
|---|---|---|---|---|---|---|---|---|---|---|
| breakeven | 344 | 157 | +0.397 | +0.374 | -0.023 | -0.105 to +0.036 | -0.145 to +0.052 | -0.021 | -0.003 | no |
| stall_exit | 344 | 106 | +0.397 | +0.369 | -0.028 | -0.133 to +0.056 | -0.180 to +0.086 | -0.028 | +0.019 | no |
| swing_trail | 344 | 101 | +0.397 | +0.406 | +0.009 | -0.006 to +0.022 | -0.013 to +0.026 | +0.009 | +0.008 | no |

Where each rule acted, at 1x costs, split by how the trade did with its own exits:

| Rule | Acted on | Own winners: trades, mean change | Own losers: trades, mean change |
|---|---|---|---|
| breakeven | 157 | 119, -0.219 | 38, +0.475 |
| stall_exit | 106 | 101, -0.138 | 5, +0.858 |
| swing_trail | 101 | 88, +0.021 | 13, +0.088 |

Mean change by coin, at 1x costs:

| Rule | BTCUSDT | ETHUSDT | SOLUSDT | XRPUSDT | BNBUSDT | DOGEUSDT |
|---|---|---|---|---|---|---|
| breakeven | -0.082 | -0.024 | +0.037 | +0.062 | +0.048 | -0.142 |
| stall_exit | -0.052 | -0.144 | -0.098 | +0.103 | +0.080 | -0.048 |
| swing_trail | -0.016 | +0.037 | +0.021 | +0.004 | +0.014 | -0.003 |

## pattern_breakout

| Rule | Trades | Rule acted on | Own exits (R) | With the rule (R) | Change | 95% interval | 99.4% interval | Change at 2x costs | Change, four coins | Passes |
|---|---|---|---|---|---|---|---|---|---|---|
| breakeven | 790 | 409 | +0.077 | +0.073 | -0.005 | -0.075 to +0.065 | -0.101 to +0.087 | -0.019 | -0.023 | no |
| stall_exit | 790 | 313 | +0.077 | +0.036 | -0.042 | -0.129 to +0.047 | -0.167 to +0.071 | -0.045 | -0.067 | no |
| swing_trail | 790 | 395 | +0.077 | +0.077 | -0.001 | -0.078 to +0.074 | -0.108 to +0.105 | -0.020 | -0.016 | no |

Where each rule acted, at 1x costs, split by how the trade did with its own exits:

| Rule | Acted on | Own winners: trades, mean change | Own losers: trades, mean change |
|---|---|---|---|
| breakeven | 409 | 240, -0.763 | 169, +1.061 |
| stall_exit | 313 | 169, -1.783 | 144, +1.862 |
| swing_trail | 395 | 229, -0.969 | 166, +1.333 |

Mean change by coin, at 1x costs:

| Rule | BTCUSDT | ETHUSDT | SOLUSDT | XRPUSDT | BNBUSDT | DOGEUSDT |
|---|---|---|---|---|---|---|
| breakeven | -0.009 | +0.045 | +0.094 | -0.088 | -0.114 | +0.048 |
| stall_exit | -0.015 | -0.001 | +0.141 | -0.212 | -0.152 | +0.002 |
| swing_trail | -0.024 | +0.060 | +0.119 | -0.116 | -0.089 | +0.052 |

## fvg_choch

| Rule | Trades | Rule acted on | Own exits (R) | With the rule (R) | Change | 95% interval | 99.4% interval | Change at 2x costs | Change, four coins | Passes |
|---|---|---|---|---|---|---|---|---|---|---|
| breakeven | 255 | 131 | +0.020 | -0.053 | -0.073 | -0.197 to +0.041 | -0.252 to +0.082 | -0.082 | -0.094 | no |
| stall_exit | 255 | 82 | +0.020 | -0.013 | -0.034 | -0.148 to +0.083 | -0.189 to +0.126 | +0.006 | -0.043 | no |
| swing_trail | 255 | 131 | +0.020 | -0.048 | -0.068 | -0.176 to +0.033 | -0.215 to +0.074 | -0.017 | -0.073 | no |

Where each rule acted, at 1x costs, split by how the trade did with its own exits:

| Rule | Acted on | Own winners: trades, mean change | Own losers: trades, mean change |
|---|---|---|---|
| breakeven | 131 | 81, -0.915 | 50, +1.110 |
| stall_exit | 82 | 45, -1.583 | 37, +1.693 |
| swing_trail | 131 | 81, -0.795 | 50, +0.939 |

Mean change by coin, at 1x costs:

| Rule | BTCUSDT | ETHUSDT | SOLUSDT | XRPUSDT | BNBUSDT | DOGEUSDT |
|---|---|---|---|---|---|---|
| breakeven | -0.117 | +0.019 | -0.294 | +0.088 | -0.093 | -0.105 |
| stall_exit | -0.127 | +0.045 | -0.214 | +0.181 | -0.213 | +0.013 |
| swing_trail | -0.147 | -0.013 | -0.229 | +0.070 | -0.168 | -0.022 |

## AI Check Counts

How often an AI exit manager would have been asked, from the trades with their own exits at 1x costs, at each 15M close while a trade was open. CHoCH against the trade, news and events are not counted, so these are lower bounds.

| Strategy | Trades | Open trade-days | Stall past +1R | Rejected near a target | Volatility jump | Checks per trade | Checks per open trade-day |
|---|---|---|---|---|---|---|---|
| daily_trend | 344 | 5269 | 1217 | 1 | 8744 | 28.96 | 1.89 |
| pattern_breakout | 790 | 3136 | 1152 | 46 | 5373 | 8.32 | 2.10 |
| fvg_choch | 255 | 112 | 147 | 29 | 109 | 1.12 | 2.54 |
| **All three** | 1389 | 8518 | 2516 | 76 | 14226 | 12.11 | 1.97 |

At about 10 open trades, that is about 20 checks a day, before CHoCH, news and event checks.

## Decision

Applied as pre-registered.

- `daily_trend`: no rule passed. It **keeps its own exits**.
- `pattern_breakout`: no rule passed. It **keeps its own exits**.
- `fvg_choch`: no rule passed. It **keeps its own exits**.

## Limits

- One trial, nothing tuned. The holdout was not used.
- Entries are held fixed, so a coin freed earlier for its next signal is not counted.
- Fills use 15M candles, and a market exit at the next open uses the backtest costs.
- The six coins move together, they are survivors, and several strategies have been tested on these years.
