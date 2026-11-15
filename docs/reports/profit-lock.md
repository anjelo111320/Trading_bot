# Profit Lock Study

Simulated results. A profitable backtest is not proof of future profitability.

Pre-registered in [43-PROFIT-LOCK-STUDY.md](../43-PROFIT-LOCK-STUDY.md) and run once. The tested strategies from 2020-01-01, or the coin's first candle, and the 15M rule from 2023-11-01, to 2025-11-01. Ten coins, each a separate 10,000 account at 1% risk per trade. The lock decides at every 15-minute close.

Replays with no rule: 6,093; matching the engine: 6,093.

## Change in R per trade, the lock minus own exits, 1x costs

| Strategy | Trades | Lock acted | Own exits | With the lock | Change | 95% interval | Change at 2x costs | R kept where it helped | R given up where it hurt |
|---|---|---|---|---|---|---|---|---|---|
| `daily_trend` | 470 | 171 | +0.318 | +0.201 | -0.117 | -0.251 to +0.002 | -0.117 | +63.4 | -118.4 |
| `pattern_breakout` | 997 | 419 | +0.068 | +0.023 | -0.045 | -0.111 to +0.021 | -0.054 | +260.7 | -305.3 |
| `fvg_choch` | 417 | 169 | +0.044 | +0.029 | -0.015 | -0.093 to +0.064 | +0.008 | +81.4 | -87.5 |
| `trend_break_baseline` | 1498 | 566 | -0.046 | -0.088 | -0.042 | -0.090 to +0.006 | -0.055 | +319.2 | -382.8 |
| **All four pooled** | 3382 | 1325 | +0.049 | -0.001 | -0.050 | -0.086 to -0.015 | -0.060 | +724.7 | -894.1 |

## By coin, change in R per trade at 1x costs

| Coin | daily_trend | pattern_breakout | fvg_choch | trend_break_baseline |
|---|---|---|---|---|
| BTCUSDT | -0.193 (71) | +0.002 (162) | -0.161 (26) | -0.047 (113) |
| ETHUSDT | -0.145 (68) | +0.015 (176) | +0.035 (52) | -0.083 (170) |
| SOLUSDT | -0.125 (37) | +0.021 (87) | -0.019 (34) | -0.050 (212) |
| XRPUSDT | -0.039 (52) | -0.150 (108) | +0.000 (41) | +0.011 (175) |
| BNBUSDT | +0.060 (60) | -0.124 (132) | -0.011 (40) | +0.074 (115) |
| DOGEUSDT | -0.202 (56) | +0.037 (125) | +0.029 (62) | -0.009 (216) |
| ZECUSDT | -0.267 (52) | -0.121 (82) | -0.032 (56) | -0.118 (84) |
| 1000PEPEUSDT | -0.255 (36) | -0.190 (45) | +0.082 (56) | -0.119 (245) |
| HYPEUSDT | +0.000 (6) | +0.032 (13) | -0.308 (9) | -0.006 (58) |
| NEARUSDT | +0.186 (32) | -0.053 (67) | -0.110 (41) | -0.024 (110) |

## Decision

Applied as pre-registered.

- `daily_trend`: no clear effect. The lock stays, as the owner chose (D066).
- `pattern_breakout`: no clear effect. The lock stays, as the owner chose (D066).
- `fvg_choch`: no clear effect. The lock stays, as the owner chose (D066).
- `trend_break_baseline`: no clear effect. The lock stays, as the owner chose (D066).

## Limits

- Fills are 15-minute candles. The live lock reads the mark price every minute, so the test sees candle extremes the live lock may miss, and it takes the stop first when a stop and the lock trigger fall in one candle.
- The 15M rule is tested on two years only, on 15-minute fills (docs/42).
- The coins move together, so the intervals are narrower than they should be.
- A result is not proof of future profit.
