# News Signal Study

Date: 2026-11-11
Status: Pre-registered on 2026-11-11, before any reading was scored against price. The rule is in code as `RULE_VERSION = 1` in `backend/src/trading_intel/news_intelligence/reading.py`. Results are added below the line "Results" after one scoring run, and nothing above it changes. A changed rule is a new version with its own forward test.

## Why This Study

The owner asked whether positive news makes the AI tell Python to trade, and then asked for a signal from the news too. Nothing in trading reads news (D052), and a news signal has never been tested here. Claude cannot be backtested honestly on old news, because the model may remember what prices did next. So the signal is tested forward, on news and prices that arrive after this date.

Hypothesis, stated before any test: over the 4 hours after a 4H close, a coin's price moves more often with its news reading than against it. This is an idea to test, not a claim that it works.

## Already Seen

- Finnhub crypto news since 12:11 UTC on 2026-11-11, and Federal Reserve releases since 2026-11-06. No reading has been compared with any later price.
- The first pull stored 92 articles from the previous two days, about 35 minutes behind publication at its newest.

## The Reading

At a moment `at`, for one coin:

1. **Stories.** The coin's articles published in the 12 hours before `at`, counted once per story, where a story is a cluster of copies. Each counts only if it was first seen by `at` and Claude had labelled it by `at`. Nothing from after `at` is used.
2. **Left out:** stories Claude flagged as possibly misleading.
3. **Weight per story:** sign × impact × relevance.
   - Sign: bullish +1, bearish −1, neutral 0, from Claude's label.
   - Impact: low 1, medium 2, high 3, from Claude's label.
   - Relevance: how directly the story names the coin. 0.9 when named, 0.6 for general crypto news on BTC and ETH, and 0.4 for macro news on BTC and ETH (D052). A story keeps its highest relevance across its copies.
4. **Score:** the sum of the weights.
5. **Direction:**
   - Bullish at +1.5 or more, bearish at −1.5 or less, otherwise neutral.
   - 1.5 is about one medium-impact story naming the coin, or one high-impact crypto story.

Claude only labels each story. Python does the sum.

## What Is Recorded

- **At every 4H close** (00:00, 04:00 … 20:00 UTC), each of the eight coins' readings is stored in `news_readings`, with the coin's 15M close price at that moment (migration 0017).
- **With every Python signal,** in every account, the reading at its close is stored, along with whether it agrees with the trade (`news_alignment`: aligned, conflicting, neutral, or unavailable if the reading failed). The reading behind it goes in `news_context`.
- Neither is read by any trading decision. An import rule keeps the trading, risk, execution, paper trading and backtest code from reaching the news module.

## Test 1: Does the Reading Point the Right Way?

- **Unit:** a bullish or bearish reading at a 4H close. Neutral readings are counted and reported, not tested.
- **Outcome:** the coin's return from that close to the next 4H close, from stored 15M candles. A reading is right when the return has its sign. A reading whose next close is missing is left out and counted.
- **When:** once, as soon as 150 bullish or bearish readings have outcomes, or on 2027-01-31 with however many there are.

The signal **passes** only if all three hold:
1. The share of right readings has a one-sided 95% Wilson lower bound above 50%.
2. The mean return in the reading's direction is above 0.10%, about a round trip at Binance's taker fee.
3. Bullish and bearish readings each have at least 30 outcomes and a positive mean return in their own direction. This guards against a market that only rose or only fell, as long and short results did in earlier studies.

Fewer than 150 readings by 2027-01-31, or fewer than 30 on one side, is **inconclusive**, not a pass.

## Test 2: Python's Trades With and Against the News

- The mean R of closed trades whose news was aligned, conflicting or neutral, in every account.
- This is descriptive only, because trades are few. No decision follows from it alone.

## What a Result Allows

- **A pass** lets the owner choose, as a new decision, that a conflicting reading skips or halves a Python trade. A news reading never starts a trade and never raises risk.
- **A fail or an inconclusive result:** the news stays information only. The rule is not tuned and retried on the same readings.

## Limits

- **Delay:** Finnhub articles arrived about 35 minutes after publication, and Claude labels at most 10 stories per 2-minute pass, so a reading can trail the market by tens of minutes.
- **Overlap:** a 12-hour window read every 4 hours shares stories between neighbouring readings, so readings are not independent. Outcomes do not overlap.
- **Labels and links can be wrong:**
  - Claude's labels describe the text, not the price.
  - A story's link to a coin comes from names in its text. An integration test showed a planted line naming BTC raising a Fed story's relevance from 0.4 to 0.9.
- **Coverage:** news reaches BTC and ETH far more often than the other coins. Small coins will often read neutral.

## Results

Not run yet.

Note added 2026-11-11, outside the registration above: by the owner's choice, the news move strategy (D056, [40-NEWS-MOVE-STRATEGY.md](40-NEWS-MOVE-STRATEGY.md)) now uses this reading to confirm Python's price moves. The test above is unchanged.
