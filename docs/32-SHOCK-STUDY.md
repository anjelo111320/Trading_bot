# Crash Warning Study

Date: 2026-11-06
Status: Pre-registered before any run. Results are added below once, without changing the rules.

## Why This Study

On 2026-11-05, BTC fell 6.1% and ETH 7.7% in under four hours. Nothing in the data warned before the fall began, but its first leg did: at 12:00 UTC a 1H candle closed below the 12-hour low, on high volume, with sellers in control, and 85% of BTC's fall came after that close. The owner asked whether the system can detect such a fall early. This study asks whether that kind of first leg warns of a large fall often enough, and early enough, to block new long trades for a while.

## Definitions

All on closed 1H candles of a perpetual, with ATR the 14-candle 1H ATR at the candle.

| Term | Definition, fixed before any run |
|---|---|
| Down warning | At a 1H close: the close is below the lowest low of the previous 12 candles, the candle's volume is at least 2 times the mean volume of the previous 24 candles, and takers sold at least 55% of the volume, so taker buy volume is at most 45% |
| Large fall ahead | The lowest low of the next 6 candles is at least 6 ATR below this close |
| Episode | A run of consecutive closes that each have a large fall ahead |
| Caught episode | An episode with a down warning at one of its closes |
| Share of the fall still ahead | For a caught episode: from the first warning's close to the episode's lowest low, divided by the same from the episode's first close |

The thresholds are common conventions: a 12-hour range, volume twice its day average, and a clear seller majority. On 2026-11-05 the 12:00 UTC candle had volume 1.9 times its average, so these rules would have warned at 14:59 UTC instead. That example is outside the test period and was not used to choose them.

## Test

- Coins: BTC, ETH, SOL, XRP, BNB and DOGE perpetuals, from 2020-01-01 or listing to 2025-11-01, before the holdout (D029).
- **Warning quality**, per coin and pooled:
  - Base rate: the share of all closes with a large fall ahead.
  - Precision: the share of warnings with a large fall ahead.
  - Lift: precision divided by the base rate.
  - Recall: the share of episodes caught, and the median share of the fall still ahead.
  - Warnings per month.
  - Benchmark: 20 seeded draws of as many random closes as there were warnings. The warning beats it if its precision is above the draws' 95th percentile.
- **Filter value**: in the pattern breakout (docs/27, trial 1) and daily trend (docs/29) backtests, the long trades whose signal came within 12 hours after a down warning are the ones a filter would have skipped. Their mean result in R is compared with the other trades. The backtests run once more, unchanged, for this.
- Sensitivity, reported but not used for the decision: volume multiples of 1.5 and 3.

## Decision Rule

The filter "no new long for 12 hours after a down warning" joins the paper loop only if all of these hold, pooled across coins:

1. The warning's precision is above the random benchmark's 95th percentile.
2. Its lift is at least 2.
3. The long trades it would have skipped lost money on average, in both the pattern and the daily trend backtests.

Otherwise the result is recorded and nothing changes.

## Limits

- Large falls cluster in a few market periods, so the pooled samples are not independent.
- Skipping a trade can let a later one happen in a backtest. That second-order effect is not simulated.
- Liquidation bursts and open interest, which were the clearest signs on 2026-11-05, have no history before November 2026 and are not tested here. They can only be tested going forward.
- Several studies have now used these years, so a borderline result is weak evidence.
