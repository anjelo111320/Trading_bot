# Indicator and Pattern Rules

Date: 2026-11-02
Rule version: 1. Changing a rule raises this version, and stored results keep the version they used.

This turns the requirements in [05-TECHNICAL-ANALYSIS.md](05-TECHNICAL-ANALYSIS.md) into exact rules. Nothing here predicts price. Many of these labels describe subjective ideas in a fixed way, so a label means "this rule fired", not "this is objectively an order block".

## Shared Rules

- Input is closed candles only, oldest first. The type system refuses forming candles.
- A result is dated by `detected_at`, the close time of the candle that made it knowable. `formed_at` may be earlier.
- Prefix stability: anything known at time T is identical whether or not later candles exist. A test proves this for every indicator and pattern.
- A missing candle is never filled. The series reports it, and analysis treats that data as less reliable.
- Warm-up values are empty rather than estimated.
- Floats are used inside this engine only (D015). Prices used for trades come from stored `Decimal` values.

## Indicators

| Indicator | Definition | Warm-up |
|---|---|---|
| SMA(n) | Mean of the last n closes | n - 1 |
| EMA(n) | Seeded with SMA(n), then alpha = 2 / (n + 1) | n - 1 |
| VWAP | Sum of typical price × volume over sum of volume, reset at 00:00 UTC | None. Empty until volume trades |
| RSI(14) | Wilder averages of gains and losses. Flat history gives 50 | 14 |
| MACD(12, 26, 9) | EMA12 - EMA26, signal EMA9 of that, histogram is the difference | 33 |
| Stochastic RSI(14, 14, 3, 3) | RSI position within its 14-candle range, %K is SMA3 of it, %D is SMA3 of %K | 31 |
| CCI(20) | (Typical price - SMA) / (0.015 × mean absolute deviation) | 19 |
| ROC(10) | 100 × (close / close 10 candles ago - 1) | 10 |
| ATR(14) | Wilder average of true range | 14 |
| ADX(14) | Wilder smoothing of the directional index | 27 |
| Bollinger(20, 2) | SMA20 ± 2 population standard deviations | 19 |
| Keltner(20, 10, 2) | EMA20 ± 2 × ATR10 | 19 |
| Historical volatility(20) | Annualised sample deviation of log returns, using 365 days | 20 |
| Volume SMA(20) | Mean of the last 20 volumes | 19 |
| Relative volume(20) | Volume over the mean of the 20 candles before it, excluding itself | 20 |
| Volume spike | Relative volume of at least 2 | 20 |
| OBV | Running sum of volume, signed by close direction | None |
| Volume delta | 2 × taker buy volume - volume. Empty if the provider gave no taker data | None |

Own implementations are checked against TA-Lib in tests.

## Market Structure

### Swings

A swing high at candle i needs a high above the n candles before it, and at or above the n candles after it. Swing lows mirror this. The default is n = 3.

**Confirmation delay:** a swing is unknown until n candles after it, so `detected_at` is the close of candle i + n. Using a swing earlier would be look-ahead.

### HH, HL, LH, LL

Each confirmed swing is compared with the previous swing of the same kind: higher or lower. The first swing of each kind has no label.

### BOS and CHoCH

State starts as `none`. Each candle's close is compared with the most recent confirmed swing high and low, and each swing can be broken only once.

| Close | Trend before | Event | Trend after |
|---|---|---|---|
| Above swing high | Down | Bullish CHoCH | Up |
| Above swing high | Up or none | Bullish BOS | Up |
| Below swing low | Up | Bearish CHoCH | Down |
| Below swing low | Down or none | Bearish BOS | Down |

A wick does not count. Limitation: results depend on n, and a low n gives many minor events.

### Support and Resistance

Swing prices within 0.5 ATR of each other cluster into one level, priced at their mean. A level needs at least two touches. Strength is 25 per touch, capped at 100. A level is `resistance` if at or above the latest close, otherwise `support`.

### Supply and Demand Zones

A base is 1 to 5 candles whose combined range is at most 1.5 ATR. An impulse is the next candle with a body of at least 1.5 ATR. An upward impulse makes a demand zone and a downward one makes a supply zone, spanning the base. It is invalidated when a close passes beyond the far side of the zone.

### Consolidation

At least 10 candles whose combined range is at most 3 ATR, with ATR measured at the start of the run. It ends at the first close outside the range.

### Liquidity

| Pattern | Rule |
|---|---|
| Equal highs or lows | Two confirmed swings of the same kind within 0.1 ATR |
| Liquidity sweep | A wick passes a confirmed swing level, and the same candle closes back inside |

## Candlestick Patterns

| Pattern | Rule |
|---|---|
| Bullish engulfing | Previous body is bearish, current is bullish, and the current body fully covers the previous body |
| Bearish engulfing | The mirror image |
| Pin bar | Range above zero, body at most 25% of range, one wick at least 60% of range, other wick at most 20% |
| Doji | Range above zero, body at most 10% of range |

Limitation: these describe one or two candles and say nothing of context. Crypto has no session gaps, so engulfing compares bodies only.

## Other Patterns

| Pattern | Rule | Invalidated when |
|---|---|---|
| Bullish FVG | Candle 3 low is above candle 1 high. The zone is that gap | A later low fills the zone completely |
| Bearish FVG | Candle 3 high is below candle 1 low | A later high fills the zone completely |
| Order block | Last opposite-colour candle in the 10 before a BOS. The zone is its high to low | A close beyond its far side |
| Breakout | A close beyond a level with relative volume of at least 1.5 | Becomes a false breakout |
| False breakout | A breakout whose close returns inside the level within 3 candles | Not applicable |
| Regular divergence | Two consecutive swings: price makes a higher high with lower RSI, or a lower low with higher RSI | A new swing beyond the second one |
| Hidden divergence | Price makes a higher low with lower RSI, or a lower high with higher RSI | A new swing beyond the second one |
| Trend reversal | A CHoCH followed by a confirmed swing in the new direction | The opposite CHoCH |

Divergences need RSI present at both swings. Limitation: divergence is a description of two points, and it often persists for a long time without price reversing.

## Strength Score

0 to 100, built only from values in the evidence. It ranks patterns of the same type and is not a probability.

## Multi-Timeframe

Default roles: 1D direction, 4H structure, 1H intermediate, 15M setup, 5M confirmation, 1M refinement. The owner can change them.

Each timeframe uses candles with `close_time` at or before the decision time, which keeps higher timeframes free of unfinished candles. Alignment is the share of roles agreeing with the direction role.
