# Signal Score Study

Simulated results. A profitable backtest is not proof of future profitability.

Score version 1, pre-registered in [34-SIGNAL-SCORE.md](../34-SIGNAL-SCORE.md) and run once. Period 2020-01-01, or the coin's first candle, to 2025-11-01, before the frozen holdout. Each coin is a separate 10,000 account at 1% risk per trade, with funding charged in every year.

Filled trades: 1134. Scored: 1098. Left out with an unknown condition: 36.

## Decision

| Check | Result | Passed |
|---|---|---|
| 1. Strong minus weak, pooled, with its 95% interval above zero | +0.092R, -0.15 to +0.32 | no |
| 2. Above zero for each strategy | daily_trend +0.144R, pattern_breakout +0.067R | yes |
| 3. Above zero on the four new coins pooled | +0.015R | yes |
| 4. Above zero among longs and among shorts | LONG +0.178R, SHORT -0.153R | no |
| 5. Above zero in at least 4 of the 6 years | 2 of 6 | no |
| 6. Scored sizing has a higher return to drawdown | +5.439 against +6.034 unscored | no |

**The score does not pass. Nothing changes in trading.**

## Strong and Weak Signals at Normal Costs

A signal is weak when two or more of its conditions are against it.

| | Strong trades | Strong mean (R) | Weak trades | Weak mean (R) | Difference (R) | 95% interval |
|---|---|---|---|---|---|---|
| **All** | 687 | +0.193 | 411 | +0.101 | +0.092 | -0.15 to +0.32 |
| daily_trend | 212 | +0.422 | 125 | +0.278 | +0.144 | -0.34 to +0.60 |
| pattern_breakout | 475 | +0.091 | 286 | +0.024 | +0.067 | -0.19 to +0.32 |
| BTCUSDT | 167 | +0.361 | 54 | -0.233 | +0.595 | +0.05 to +1.12 |
| ETHUSDT | 123 | +0.088 | 97 | +0.182 | -0.094 | -0.58 to +0.37 |
| SOLUSDT | 72 | +0.181 | 52 | +0.099 | +0.082 | -0.67 to +0.76 |
| XRPUSDT | 95 | +0.375 | 65 | +0.079 | +0.296 | -0.34 to +0.92 |
| BNBUSDT | 131 | +0.033 | 61 | +0.260 | -0.227 | -0.86 to +0.33 |
| DOGEUSDT | 99 | +0.086 | 82 | +0.125 | -0.040 | -0.60 to +0.57 |
| Four new coins | 397 | +0.155 | 260 | +0.140 | +0.015 | -0.32 to +0.33 |
| LONG | 461 | +0.334 | 180 | +0.157 | +0.178 | -0.17 to +0.52 |
| SHORT | 226 | -0.095 | 231 | +0.057 | -0.153 | -0.45 to +0.14 |
| 2020 | 61 | +0.703 | 17 | -0.371 | +1.074 | +0.07 to +2.03 |
| 2021 | 141 | +0.314 | 64 | +0.435 | -0.121 | -0.77 to +0.52 |
| 2022 | 118 | +0.147 | 76 | +0.196 | -0.049 | -0.62 to +0.47 |
| 2023 | 114 | -0.065 | 76 | +0.293 | -0.359 | -0.91 to +0.17 |
| 2024 | 143 | +0.356 | 73 | -0.176 | +0.532 | +0.06 to +1.05 |
| 2025 | 110 | -0.139 | 105 | -0.042 | -0.097 | -0.51 to +0.31 |

At 2x costs, reported only: difference +0.094R, -0.16 to +0.33.

## Sizing

Cumulative R in exit order, pooled over both strategies and six coins, each trade weighed by its strategy's money-plan share.

| | Total (R) | Largest fall (R) | Total over largest fall |
|---|---|---|---|
| Without the score | +149.2 | 24.7 | +6.034 |
| Weak signals at half | +130.2 | 23.9 | +5.439 |

## Each Condition on Its Own

A description only. Slicing six ways invites fitting, so none of these can change trading.

| Condition | Strategy | For: trades | For: mean (R) | Against: trades | Against: mean (R) |
|---|---|---|---|---|---|
| Coin's long-term trend | daily_trend | 230 | +0.474 | 107 | +0.142 |
| Coin's long-term trend | pattern_breakout | 533 | +0.022 | 228 | +0.167 |
| Bitcoin's long-term trend | daily_trend | 180 | +0.502 | 88 | +0.083 |
| Bitcoin's long-term trend | pattern_breakout | 414 | -0.047 | 195 | +0.249 |
| Volume | daily_trend | 283 | +0.305 | 54 | +0.702 |
| Volume | pattern_breakout | 634 | +0.119 | 127 | -0.203 |
| Funding | daily_trend | 137 | +0.241 | 200 | +0.456 |
| Funding | pattern_breakout | 288 | +0.283 | 473 | -0.067 |

## Limits

- The six coins move together, so their trades are not independent and the intervals are narrower than they should be.
- A coin's trend and Bitcoin's often agree, so the conditions overlap.
- Early trades with an unknown condition are left out, so 2020 counts less than in docs/27 and docs/29.
- Funding before March 2023 is charged at the last 15M close, not the mark price.
- A pass is not proof of future profit.
