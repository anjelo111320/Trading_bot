# Indicator and Pattern Rules

Date: 2026-11-02, updated 2026-11-03.
Rule version: 2. Changing a rule raises this version, and stored results keep the version they used.

Version 2 added the ATR zigzag, trend-aware candle patterns and chart patterns, at the end of this document. Version 1 rules are unchanged. Research behind them is in [26-PATTERN-RESEARCH.md](26-PATTERN-RESEARCH.md).

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

Pattern strategies use 1D for direction, 4H for structure, 1H for setups and 15M for entry timing (D031).

## ATR Zigzag (Version 2)

Chart patterns are drawn on zigzag pivots, which ignore the small swings `find_swings` reports.

- A pivot high is confirmed on the first later candle whose low is at least 2.5 × ATR(14) below it, with ATR read on that confirming candle. Lows mirror this.
- The candle that sets a new extreme never confirms a reversal itself, because the order of its high and low is unknown.
- `detected_at` is the confirming candle's close. Pivots alternate high and low, and carry HH, LH, HL or LL labels.
- No pivot confirms during ATR warm-up.

Limitation: one scale per run. Patterns much smaller or larger than 2.5 ATR legs are missed.

## Candle Patterns With Trend Context (Version 2)

**Prior trend** is read from the 10 closes before the pattern's first candle: a move of at least +1 ATR is up, at most -1 ATR is down, anything else is none. A **large** first body is at least the mean body of the 10 candles before it. Opens may differ from the previous close by 10% of the first body, because crypto candles open at the previous close give or take a tick. No rule needs a gap.

| Pattern | Rule | Trend needed |
|---|---|---|
| Hammer, hanging man | Lower wick at least 2 × body and 60% of range, upper wick at most 10% | Down for hammer, up for hanging man |
| Inverted hammer, shooting star | The mirror shape | Down for inverted hammer, up for shooting star |
| Dragonfly, gravestone doji | Body at most 10% of range, and the upper or lower wick at most 10% | Down, or up |
| Marubozu | Body at least 90% of range and at least the mean body | None |
| Harami | Large first body, second body at most half of it, inside it, opposite colour | Opposite to the pattern |
| Piercing line, dark cloud cover | Large first body. Second closes beyond the middle of the first body but not past its open | Down, or up |
| Tweezer bottom, top | Equal lows or highs within 0.1 ATR, the first candle with the trend and the second against it | Down, or up |
| Inside bar | High and low inside the previous candle | None |
| Morning, evening star | Large first body, star body at most 30% of it near the first close, third closes beyond the middle of the first | Down, or up |
| Three white soldiers, black crows | Three bodies of at least half their range, closing near the extreme, each opening within the previous body | Not already up, or not already down |
| Three inside up, down | A harami, then a close beyond the first candle's open | Opposite to the pattern |
| Three outside up, down | An engulfing pair, then a close beyond the second candle | Opposite to the pattern |

Limitation: these describe one to three candles. Studies find little value in them alone, so they serve as context and confirmation.

## Chart Patterns (Version 2)

A chart pattern exists only once a candle closes beyond its trigger line, and it is dated by that close. Tolerances use ATR on the breakout candle, or on the fifth pivot's confirmation for channel shapes. Each pattern carries its turning points, trigger line, invalidation level, height, and measured moves at 1× and 2× its height. It is invalidated by a later close beyond its invalidation level.

| Pattern | Rule | Trigger | Invalidation |
|---|---|---|---|
| Head and shoulders | Pivots E1 to E4 are high, low, high, low, and E5 is the highest high since E4. E3 above E1 and E5. E1 and E5 within 1 ATR, E2 and E4 within 1 ATR. The pivot before E1 lies below both troughs | First close below the neckline through E2 and E4 | E5, the right shoulder |
| Inverse head and shoulders | The mirror | First close above the neckline | E5 |
| Double top | Peak E1, trough E2, and the highest high since E2 as the second peak, within 1 ATR of E1 and at least 10 candles later. The pivot before E1 lies below E2 | First close below E2 | The second peak |
| Double bottom | The mirror | First close above E2 | The second trough |
| Rectangle | Five confirmed pivots. Tops within 0.5 ATR, bottoms within 0.5 ATR, the lowest top above the highest bottom | A close beyond the highest top or lowest bottom | The last bottom for an upward break, the last top for a downward one |
| Ascending triangle | Flat tops within 0.5 ATR, rising bottoms | A close beyond the lines through the last two tops and last two bottoms | As above |
| Descending triangle | Flat bottoms, falling tops | As above | As above |
| Symmetrical triangle | Falling tops, rising bottoms | As above | As above |
| Rising wedge | Rising tops and bottoms, converging | As above | As above |
| Falling wedge | Falling tops and bottoms, converging | As above | As above |
| Broadening | Rising tops, falling bottoms | As above | As above |
| Bull flag | The highest high of the last 3 to 24 candles is the pole top. The pole rises at least 5 ATR from the lowest low of the 12 candles before it. The pullback since keeps at least half the pole | First close above the pole top | The pullback low |
| Bear flag | The mirror | First close below the pole bottom | The pullback high |

Rules for the life of a pattern:

- Head and shoulders and double tops: the first close through the trigger decides. If the shape fails then, there is no pattern. The search ends when the right shoulder passes the head, or the next-but-one pivot confirms.
- Channel shapes live from their fifth pivot's confirmation until the next pivot confirms, and end early past their apex.
- Flags: each pole top is judged once, at the first close beyond it.

Strength ranks breakouts by relative volume, 50 × the ratio to the mean of the 20 candles before, because Bulkowski found high breakout volume helps. It is not a probability.

Limitations: geometry follows Lo, Mamaysky and Wang (2000), with ATR instead of percentages, but rules cannot see what a person sees. Some shapes that pass would not be drawn that way by hand. Measured moves for wedges use the pattern height, not the wedge start that Bulkowski uses.
