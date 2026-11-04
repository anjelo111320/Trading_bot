# Chart Pattern and Candlestick Research

Date: 2026-11-03
Status: Research. It feeds rule version 2 in [25-PATTERN-RULES.md](25-PATTERN-RULES.md) and the plan in [27-PATTERN-SIGNAL-PLAN.md](27-PATTERN-SIGNAL-PLAN.md).

## Summary

- **Patterns describe the past. None predicts the future reliably.** Studies of candlesticks alone mostly find no edge after costs. Chart patterns carry some statistical information in large samples, and simple technical rules have worked on crypto in at least one rigorous study. None of this guarantees profit in a new period.
- **Trend context decides what a shape means.** The same candle is a hammer after a fall and a hanging man after a rise. A head and shoulders needs a rise before it.
- **Confirmation matters more than shape.** In Bulkowski's data, only 35% to 37% of double and triple tops in bull markets ever confirmed. Shorting a top before it breaks is a losing bet most of the time.
- **Crypto differs from the stocks most studies used.** It trades all day, every day, so candles almost never gap. Wicks and stop sweeps are common, and volatility changes quickly, so tolerances must scale with ATR rather than fixed percentages.
- **What follows for this project:** detect patterns with written rules, act only on confirmed breakouts in the direction of the higher-timeframe trend, attach measured-move targets and invalidation levels, and let backtests and forward paper results decide what has value.

## 1. How Patterns Relate to Trend

A trend is a sequence of swings. Higher highs and higher lows make an uptrend. Lower highs and lower lows make a downtrend. Overlapping swings make a range.

| Market phase | Continuation patterns, with the trend | Reversal warnings, against the trend |
|---|---|---|
| Uptrend | Bull flag, pennant, ascending triangle, rectangle with an upward break, falling wedge as a pullback | Head and shoulders top, double or triple top, rising wedge, bearish engulfing, evening star, shooting star, hanging man, dark cloud cover, bearish harami, three black crows |
| Downtrend | Bear flag, pennant, descending triangle, rectangle with a downward break, rising wedge as a pullback | Inverse head and shoulders, double or triple bottom, falling wedge, bullish engulfing, morning star, hammer, inverted hammer, piercing line, bullish harami, three white soldiers |
| Range | Rectangle, symmetrical triangle, broadening formation | Breakouts and false breakouts, which are liquidity sweeps in this project |

Two practical rules follow from this.

1. **A reversal pattern needs a trend to reverse.** A head and shoulders after a flat market is just noise. Detection must check the move into the pattern.
2. **A small reversal can be a large continuation.** An inverse head and shoulders on 1H, inside a 4H uptrend, ends a pullback and resumes the bigger trend. This is why the strategy filters 1H patterns by the 4H and 1D trend (D031).

## 2. Candlestick Patterns

Candles describe one to three bars of buying and selling pressure. Their names come from Japanese rice trading, popularised in the West by Steve Nison.

| Pattern | Candles | Shape | Context needed | Meaning |
|---|---|---|---|---|
| Doji | 1 | Body tiny against the range | Any | Indecision |
| Dragonfly or gravestone doji | 1 | Doji with the body at the top or bottom of the range | After a fall, or after a rise | Rejection of lower or higher prices |
| Hammer | 1 | Small body near the top, lower wick at least twice the body | After a fall | Bullish reversal |
| Hanging man | 1 | Same shape as a hammer | After a rise | Bearish warning |
| Inverted hammer | 1 | Small body near the bottom, long upper wick | After a fall | Bullish reversal |
| Shooting star | 1 | Same shape as an inverted hammer | After a rise | Bearish reversal |
| Marubozu | 1 | Body almost the whole range, and large against recent bodies | Any | Strong control by one side |
| Pin bar | 1 | Already built: a long wick and small body | Any | Rejection |
| Engulfing | 2 | Second body covers the first, opposite colour | After the opposite trend | Reversal |
| Harami | 2 | Second body sits inside a large first body, opposite colour | After the opposite trend | Momentum fading |
| Piercing line | 2 | Bullish candle closes above the middle of a large bearish body | After a fall | Bullish reversal |
| Dark cloud cover | 2 | Mirror of the piercing line | After a rise | Bearish reversal |
| Tweezer top or bottom | 2 | Two equal highs, or two equal lows | After a rise, or after a fall | Rejection of a level |
| Inside bar | 2 | Range inside the previous range | Any | Compression before a move |
| Morning star | 3 | Large bearish, small star, bullish closing above the middle of the first | After a fall | Bullish reversal |
| Evening star | 3 | Mirror of the morning star | After a rise | Bearish reversal |
| Three white soldiers | 3 | Three large bullish bodies, each closing higher near its high | After a fall or range | Bullish strength |
| Three black crows | 3 | Mirror of three white soldiers | After a rise or range | Bearish strength |
| Three inside up or down | 3 | Harami, then a candle closing beyond the first body | After the opposite trend | Confirmed harami |
| Three outside up or down | 3 | Engulfing, then a candle closing beyond it | After the opposite trend | Confirmed engulfing |

### Crypto has no gaps

Classical definitions of the morning star, evening star, piercing line and dark cloud cover require a gap between candles. Measured on this project's stored Binance perpetual candles on 2026-11-03, consecutive 1H candles open at the previous close: the median difference is 0 basis points, the 99th percentile under 0.06 basis points, and 2 of 5,259 candles per instrument opened outside the previous candle's range. So:

- Star, piercing and dark cloud patterns are defined here without a gap. The star only needs a small body.
- Patterns that are defined by a gap, such as the abandoned baby, kicker, tasuki gap and on-neck lines, are not built. They would essentially never fire.
- Engulfing already compares bodies only (rule version 1).

### Evidence on candlesticks

| Study | Market | Finding |
|---|---|---|
| Marshall, Young and Rose, "Market timing with candlestick technical analysis" (2007, also cited as 2006) | Dow Jones Industrial Average stocks | Candlestick strategies were not profitable for large US stocks |
| Marshall, PhD thesis, Massey University (2005) | US stocks | No evidence that a candlestick trader beats the market |
| Tharavanij, Siraprapasiri and Rajchamaha, SAGE Open (2017) | Thailand | Reversal patterns of little use. Filtering with %D, RSI or MFI did not help |
| "Do Candlestick Patterns Work in Cryptocurrency Trading?" (2021) | 23 cryptocurrencies, daily, 68 patterns | Candlestick patterns of little use |
| "Intraday price forecasts using candlestick patterns in cryptocurrency markets", *International Review of Economics & Finance* (2026) | About 400 cryptocurrencies on 36 exchanges, hourly, 2018 to 2022, 55 TA-Lib patterns | Some patterns, such as bullish harami and hikkake, and bearish harami and hanging man, preceded significant moves. Fewer than half forecast direction correctly. Only the abstract was read |
| Bulkowski, *Encyclopedia of Candlestick Charts*, "top 10" list | US stocks | Best reversal rates: three stars in the south 86%, bearish three-line strike 84% (as a bullish reversal), three white soldiers 82%, bearish engulfing 79%, morning star 78%, three black crows 78%, evening star 72%. His definition of reversal is his own, and costs are not included |

Conclusion: candles are useful as **context and confirmation** at a level that matters, not as stand-alone signals. TA-Lib's 61 candlestick functions compare bodies and wicks with the average of the previous 10 candles and ignore trend. This project adds an explicit prior-trend rule.

## 3. Chart Patterns

Chart patterns are drawn on swing points. The notation below uses five consecutive turning points, E1 to E5, as Lo, Mamaysky and Wang did.

| Pattern | Type | Geometry | Confirmation | Measured move | Invalidation |
|---|---|---|---|---|---|
| Head and shoulders top | Reversal of a rise | Peaks E1, E3, E5 with E3 highest. E1 and E5 similar. Neckline through troughs E2 and E4 | Close below the neckline | Head height, projected down from the breakout | Above the right shoulder |
| Inverse head and shoulders | Reversal of a fall | Mirror image | Close above the neckline | Head depth, projected up | Below the right shoulder |
| Double top | Reversal of a rise | Two similar peaks with a trough between | Close below the trough | Peak-to-trough height, projected down | Above the second peak |
| Double bottom | Reversal of a fall | Mirror image | Close above the peak between | Height, projected up | Below the second trough |
| Rectangle | Continuation or reversal | Flat tops and flat bottoms | Close outside either side | Rectangle height, projected | Back inside, beyond the far side |
| Ascending triangle | Usually bullish | Flat tops, rising troughs | Close outside the triangle | Widest height, projected | Beyond the last touch |
| Descending triangle | Usually bearish | Falling peaks, flat troughs | Close outside the triangle | Widest height, projected | Beyond the last touch |
| Symmetrical triangle | Either way | Falling peaks, rising troughs | Close outside the triangle | Widest height, projected | Beyond the last touch |
| Rising wedge | Bearish bias | Both lines rise and converge | Close outside the wedge | Back to the wedge start | Beyond the last touch |
| Falling wedge | Bullish bias | Both lines fall and converge | Close outside the wedge | Back to the wedge start | Beyond the last touch |
| Broadening formation | Either way | Peaks rise and troughs fall | Close beyond the last peak or trough | Widest height | Beyond the last touch |
| Flag | Continuation | Steep pole, then a short, tight drift against it | Close beyond the flag in the pole's direction | Pole height, projected from the flag | Beyond the far side of the flag |

### Evidence on chart patterns

**Lo, Mamaysky and Wang, "Foundations of Technical Analysis", *Journal of Finance* (2000).** Read in full for this document.

- Method: kernel regression on rolling 38-day windows (35 days plus a 3-day lag), with the bandwidth set to 0.3 times the cross-validated optimum, because the optimum looked too smooth to human analysts. Extrema of the smoothed curve are mapped back to the highest or lowest real price nearby.
- Definitions: a head and shoulders needs E3 above E1 and E5, with E1 and E5 within 1.5% of their average and E2 and E4 within 1.5% of theirs. Rectangle tops and bottoms must lie within 0.75% of their averages, and the lowest top above the highest bottom. A double top needs two peaks within 1.5% of their average and more than 22 trading days apart. Triangles need E1 > E3 > E5 and E2 < E4, or the mirror. Broadening needs E1 < E3 < E5 and E2 > E4, or the mirror.
- Results, US stocks from 1962 to 1996: on Nasdaq, all 10 patterns changed the distribution of later returns at the 5% level. On NYSE and AMEX, 5 of 10 did: head and shoulders, broadening bottom, rectangle top, rectangle bottom and double top. Volume trend added little.
- The authors' own caveat: incremental information "does not necessarily imply" excess trading profits, and traditional shapes "need not be optimal".

**Bulkowski, thepatternsite.com and *Encyclopedia of Chart Patterns*, 3rd edition.** US stocks, mostly daily charts, measured as "perfect trades" that buy at the breakout and sell at the ultimate high, without costs. The rankings are useful. The percentages are optimistic.

| Pattern | Statistic |
|---|---|
| Unconfirmed tops, bull market | Double tops confirmed 37% of the time, triple tops 35%, head and shoulders tops 62% |
| Unconfirmed bottoms, bull market | Double bottoms 56%, triple bottoms 57%, head and shoulders bottoms 76% |
| Inverse head and shoulders | Rank 13 of 39. Break-even failure 11%. 71% meet the measured target. Throwback 65% |
| Symmetrical triangle | Rank 36 of 39 for upward breakouts, 34 of 36 downward. 58% meet the target upward, 36% downward. Breakout comes about 74% of the way to the apex |
| Rising wedge | Rank 32 of 39 upward, last of 36 downward. Breaks down 60% of the time |
| Flag | 46% meet the target in both directions. Break-even failure 44% to 45%. Tight flags beat loose ones |

Bulkowski's measure rule scales the pattern height by the share that historically reached the full target, for example 0.71 for the inverse head and shoulders. This project offers several multiples as catalogue levels, and the risk engine decides whether any of them gives 2:1.

## 4. Technical Analysis on Crypto

**Hudson and Urquhart, "Technical trading and cryptocurrencies", *Annals of Operations Research* 297 (2021).** About 15,000 rules from five classes, tested on two Bitcoin markets and three other large coins. They found significant predictability and profitability in every class for every coin, robust to data-snooping corrections, with better risk-adjusted returns than buy and hold.

Caveats: the data ends years before today. Edges in young markets tend to shrink as they mature. Results depend on costs, which matter more on short timeframes. This project's 15M baseline lost about a third of gross profit to costs on BTC.

Overall, the evidence is mixed and depends on the period. Only an honest backtest with costs, then forward paper trading, can say whether this system's rules help.

## 5. Detecting Patterns in Code

| Method | How it works | Strengths | Weaknesses | Used |
|---|---|---|---|---|
| Local extrema with a fixed window | A high above the n candles on each side. Already built as `find_swings` | Simple, known delay | Finds many minor swings. Phase 2 found 76 CHoCH events in 90 days of 1H candles | Structure, stops |
| ATR zigzag | A turning point is confirmed once price moves k × ATR away from it | Adapts to volatility, explicit confirmation, easy to explain | One scale per run | **Chart patterns** |
| Kernel smoothing | Lo, Mamaysky and Wang | Smooth, matches human judgment | Heavier. Points near the window end move as data arrives | Later research |
| Perceptually important points | Fu, Chung and others, 2001 to 2008. Points a human would pick | Good for template matching | Selection depends on the whole window | No |
| Templates, DTW, image networks | Compare shapes with examples | Flexible | Opaque. A CNN study found candlestick images no better than prices alone | No |

Look-ahead traps, each covered by a test in this project:

- A swing is unknown until confirmed. Its detection time is the confirming candle.
- A chart pattern is dated by its breakout close, not its first turning point.
- Charting software often redraws the last zigzag leg. Here the last leg is explicitly unconfirmed.
- A smoothed curve uses later points to smooth earlier ones, so it may only be read at the window end.

## 6. Crypto Specifics

- **No gaps.** See section 2.
- **Wicks and sweeps.** Leverage and liquidations produce long wicks through obvious levels. Stops need a buffer beyond the invalidation point, and the liquidity sweep detector already flags these events.
- **Volatility regimes.** Tolerances are in ATR units. Lo, Mamaysky and Wang's 1.5% suited daily US stocks, not hourly crypto.
- **Funding.** Perpetual positions pay or receive funding every 8 hours. The simulator charges actual historical rates.
- **News shocks.** Exchange failures, hacks, ETF decisions and macro data can break any pattern. This is the news layer's job.
- **Survivorship.** BTC and ETH were chosen because they survived. Every report says so.

## 7. Most-Traded Coins

Binance USD-M USDT perpetuals, from Binance's public endpoints on 2026-11-03 at 15:14 UTC. Ranked by the median daily traded value of the last 30 closed days, which filters out one-day bursts. Values are millions of USDT.

| Rank | Contract | 30-day median | Last 24h | 24h ÷ median | Listed |
|---|---|---|---|---|---|
| 1 | BTCUSDT | 9,961 | 9,715 | 0.98 | 2019-09 |
| 2 | ETHUSDT | 7,101 | 6,760 | 0.95 | 2019-11 |
| 3 | ZECUSDT | 1,668 | 2,168 | 1.30 | 2020-02 |
| 4 | SOLUSDT | 1,468 | 1,595 | 1.09 | 2020-09 |
| 5 | NEARUSDT | 658 | 503 | 0.77 | 2020-10 |
| 6 | XRPUSDT | 581 | 704 | 1.21 | 2020-01 |
| 7 | HYPEUSDT | 473 | 874 | 1.85 | 2025-05 |
| 8 | DOGEUSDT | 311 | 293 | 0.94 | 2020-07 |
| 9 | BNBUSDT | 281 | 295 | 1.05 | 2020-02 |
| 10 | WLDUSDT | 258 | 132 | 0.51 | 2023-07 |
| 11 | ENAUSDT | 257 | 215 | 0.83 | 2024-04 |
| 12 | 1000PEPEUSDT | 239 | 339 | 1.42 | 2023-05 |
| 13 | SUIUSDT | 217 | 165 | 0.76 | 2023-05 |
| 15 | UNIUSDT | 194 | 215 | 1.11 | 2020-09 |
| 17 | ADAUSDT | 145 | 100 | 0.69 | 2020-01 |

BTC and ETH carried 55% of the day's USDT-perpetual value across 522 contracts. The same day showed news-driven bursts: HOTUSDT traded 297 times its 30-day median, IDOLUSDT 148 times, and several contracts in Binance's "Alpha" category rose 40% to 60%. Contracts listed within the last year have too little history for pattern statistics.

A ranking from one day and 30 days is a snapshot. It changes, which is why D033 proposes a screened universe rather than a fixed list.

## 8. News Sources

Checked on 2026-11-03. Each source still needs its full terms read before code is written.

| Source | Access | What was found | Status |
|---|---|---|---|
| Federal Reserve | RSS | Already collected | Running |
| SEC press releases | RSS, `sec.gov/news/pressreleases.rss` | Fair access: at most 10 requests a second. Unclassified bots are not permitted | Check the User-Agent rule |
| BLS release calendar | ICS, `bls.gov/schedule/news_release/bls.ics` | National release dates, including CPI and the Employment Situation. 2025 dates were revised after the funding lapse | Ready to build |
| US Treasury | Press releases | Not yet checked | Check |
| CoinDesk | RSS | No RSS-specific terms found. General terms, and a separate licence for its data API | Check |
| Cointelegraph | RSS, `cointelegraph.com/rss` | Terms allow quoting with attribution under fair use. No RSS-specific terms found | Check |
| CryptoPanic | API with a key | Plan tiers named developer, growth and enterprise, per a third-party SDK. Official terms not found by search | Needs the owner's key and a terms check |
| Finnhub | API with a key | Has a crypto news category. Third-party pages describe a free personal-use tier at about 60 calls a minute | Needs the owner's key and a terms check |
| NewsData.io | API with a key, `latest` and `crypto` endpoints | Free plan, checked 2026-11-04: 200 credits a day, 1 to 10 articles per credit, the past 48 hours, **news delayed by 12 hours**, "for testing and personal projects". The `crypto` endpoint tags articles by coin | Owner's key stored in `.env` and tested on 2026-11-04: both endpoints work |

Under D006, everything stays on this computer for the owner's use. Headlines and short summaries are stored, never republished.

## 9. What This Means for the Build

- Each pattern becomes an evidence item with its rule, detection time, invalidation and target levels. Claude selects among these by ID and never invents a price (D009).
- Candles serve as context and confirmation. Chart patterns are the setups. The 4H and 1D trend decides direction.
- NO TRADE is the normal answer. A signal needs a confirmed pattern, trend agreement and a 2:1 trade that survives costs.
- The deterministic strategy is tested on history from before the frozen holdout. Claude is judged forward only, in its own paper account (D030), because its training data contains the historical outcomes.

## Sources

- Lo, Mamaysky and Wang (2000): [NBER working paper 7613](https://www.nber.org/papers/w7613), [author page](https://web.mit.edu/~alo/www/Papers/techanal.html)
- Marshall, Young and Rose: [RePEc listing](https://ideas.repec.org/a/ris/jofitr/0834.html), [Massey thesis](https://mro.massey.ac.nz/items/edc6c1cf-63d9-4c94-a13d-92ffe1a53481/full)
- Tharavanij et al. (2017): [SAGE Open](https://journals.sagepub.com/doi/10.1177/2158244017736799)
- Hudson and Urquhart (2021): [RePEc listing](https://ideas.repec.org/a/spr/annopr/v297y2021i1d10.1007_s10479-019-03357-1.html)
- Intraday candlestick study (2026): [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S1059056026002716), [ResearchGate](https://www.researchgate.net/publication/403391704_Intraday_price_forecasts_using_candlestick_patterns_in_cryptocurrency_markets)
- Daily crypto candlestick study: [ResearchGate](https://www.researchgate.net/publication/355991813_Do_Candlestick_Patterns_Work_in_Cryptocurrency_Trading)
- Bulkowski: [confirmation](https://thepatternsite.com/Confirmation.html), [rankings](https://thepatternsite.com/id84.html), [inverse head and shoulders](https://www.thepatternsite.com/hsb.html), [symmetrical triangles](https://thepatternsite.com/st.html), [flags](https://thepatternsite.com/flags.html), [rising wedges](https://thepatternsite.com/risewedge.html), [candle reversals](https://thepatternsite.com/CandleReverse.html)
- TA-Lib: [candle settings](https://ta-lib.org/api/candle-settings/)
- Perceptually important points: [Fu et al., template versus rule matching](https://repository.vtc.edu.hk/ive-it-sp/4)
- SEC: [developer resources](https://www.sec.gov/developer), [RSS feeds](https://www.sec.gov/about/secrss.shtml)
- BLS: [release schedule](https://www.bls.gov/schedule/2027/01_sched_list.htm)
- CoinDesk: [terms](https://coindesk.com/terms/). Cointelegraph: [terms](https://cointelegraph.com/terms-and-privacy)
- Binance market data: public `fapi/v1/ticker/24hr`, `fapi/v1/exchangeInfo` and `fapi/v1/klines` endpoints
