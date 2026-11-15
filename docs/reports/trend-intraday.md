# Daily Trend, Checked All Day: Results

Pre-registered in docs/41. Six coins, 2020-01-01 to 2025-11-01, before the holdout, in the shared simulator. Simulated results; R per trade after fees, spread, slippage and funding.

| Coin | V1 trades | V1 mean R | V2 trades | V2 mean R | V2 at 2x costs |
|---|---|---|---|---|---|
| BTCUSDT | 71 | +0.439 | 85 | +0.369 | +0.342 |
| ETHUSDT | 68 | +0.372 | 78 | +0.428 | +0.405 |
| SOLUSDT | 37 | +0.529 | 46 | +0.294 | +0.274 |
| XRPUSDT | 52 | +0.317 | 65 | +0.245 | +0.224 |
| BNBUSDT | 60 | +0.280 | 74 | +0.226 | +0.201 |
| DOGEUSDT | 56 | +0.487 | 68 | +0.355 | +0.335 |

- Version 1, pooled: 344 trades, +0.397R a trade, 95% interval +0.165 to +0.664.
- Version 2, pooled: 416 trades, +0.325R a trade, 95% interval +0.109 to +0.542; at 2x costs +0.302R.
- Rule 1, at least version 1 less 0.05R: failed.
- Rule 2, interval above zero: passed.
- Decision: version 1 stays.
