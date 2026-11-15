# Daily Trend, Checked All Day

Date: 2026-11-12
Status: Pre-registered on 2026-11-12, before any code or run of these rules. One run, and the decision rule below picks the version the money plan trades. Results go below "Results", and nothing above it changes.

## Why

The owner saw Binance demo trades opening at 00:00 UTC and asked for trades "all the time if there are signals". Python checks every coin every 15 minutes. But the daily trend (docs/29), which made two of the four Binance trades, decides only at the daily close. The original Turtle rules entered as soon as price crossed the 20-day range, during the day. The owner chose to test that, and to switch only if it is not worse.

Hypothesis, stated before any test: entering at the first 1H close beyond the prior 20-day range, rather than waiting for the daily close, earns at least as much per trade, because it catches the move earlier. This is an idea to test, not a claim that it works.

## Already Seen

- Version 1 (daily close) on BTC and ETH: +0.50R and +0.46R a trade (docs/29).
- On the six coins pooled, it was the best tested strategy, +0.397R a trade over 344 trades (2026-11-11).
- No intraday entry has been run on any data.

## Rules, Version 2

Everything is as in version 1 except when and where it enters:

| Part | Version 1 | Version 2 |
|---|---|---|
| Decided at | Each daily close | Each 1H close |
| Entry | A daily close beyond the previous 20 days' range | The first 1H close of the UTC day beyond the previous 20 complete days' range. Today's own candle does not count |
| Price | Market at the close | Market at that 1H close |
| ATR | ATR(20) of daily candles up to that day | ATR(20) of daily candles up to the previous day |
| Stop | 2 ATR from the entry | The same |
| Exit | The 10-day extreme, moved at each daily close | The same, at each daily close |
| Profit cap | 10R | The same |
| Once a day | – | At most one signal per coin and UTC day, so a stopped-out breakout does not re-enter the same day |

## Test

Both versions, on the first six coins, from 2020-01-01 to 2025-11-01, before the holdout, in the shared simulator: normal costs and twice the costs, 15M fills, real funding, one position per coin.

## Decision Rule

Version 2 replaces version 1 in the money plan, on Binance demo and the paper money plan, only if both hold at normal costs:
1. Its pooled mean R per trade is at least version 1's, less 0.05R.
2. The lower end of its 95% bootstrap interval for the mean R is above zero.

Otherwise version 1 stays. The original `Paper` account keeps version 1 either way. Version 2 keeps the full share if adopted, because it passes the same evidence bar.

## Results

Run once on 2026-11-12. Report: [trend-intraday.md](reports/trend-intraday.md). Simulated results.

| Coin | V1 trades | V1 mean R | V2 trades | V2 mean R | V2 at 2x costs |
|---|---|---|---|---|---|
| BTCUSDT | 71 | +0.439 | 85 | +0.369 | +0.342 |
| ETHUSDT | 68 | +0.372 | 78 | +0.428 | +0.405 |
| SOLUSDT | 37 | +0.529 | 46 | +0.294 | +0.274 |
| XRPUSDT | 52 | +0.317 | 65 | +0.245 | +0.224 |
| BNBUSDT | 60 | +0.280 | 74 | +0.226 | +0.201 |
| DOGEUSDT | 56 | +0.487 | 68 | +0.355 | +0.335 |

- **Version 1, pooled:** 344 trades, +0.397R a trade, 95% interval +0.165 to +0.664.
- **Version 2, pooled:** 416 trades, +0.325R a trade, 95% interval +0.109 to +0.542. At 2× costs, +0.302R.
- **Rule 1** (at least +0.347R): **failed**.
- **Rule 2** (interval above zero): passed.
- **Decision: version 1 stays.** The daily trend keeps deciding at the daily close.

Version 2 traded about 20% more often and earned less per trade. In total R the two were close: 135R for version 2 against 137R for version 1. It was better on ETH and worse on the other five coins.
