# News Move Strategy

Date: 2026-11-11
Status: Pre-registered on 2026-11-11, before any code or run of these rules. Trades on Binance demo and in the paper money plan from the start, at the smallest share, by the owner's choice (D056). Results go below "Results", and nothing above it changes. A changed rule is a new version.

## Why

The owner asked whether Python trades when the news signal comes. It did not: news was recorded only (D055). The owner chose a strategy where **Python finds a price move first, and the news must agree**, trading on Binance demo now rather than in shadow.

The idea comes from stocks. After a big move, prices that move with public news tend to keep going, while big moves without news tend to reverse (Chan, 2003, *Journal of Financial Economics*). Whether that holds for crypto over hours is not known. Studies find news sentiment has some value for Bitcoin over days and weeks, and no clear intraday edge after costs.

Hypothesis, stated before any test: a strong 1H move that the coin's news agrees with continues far enough to pay for a 1.5 ATR stop and costs. This is an idea to test, not a claim that it works.

## Rules, Version 1

Decided at each 1H close, for each of the eight coins, from candles closed by then:

1. **ATR:** ATR(14) of 1H candles up to the candle **before** the move, so the move does not inflate it.
2. **A strong move:** the last closed 1H candle's body, `|close − open|`, is at least 1.5 ATR.
3. **A strong close:** a rising candle closes in the top 30% of its range, and a falling one in the bottom 30%.
4. **Direction:** a rising candle is a long, a falling one a short.
5. **The news must agree:** the coin's news reading at that close (rule version 1, [39-NEWS-SIGNAL.md](39-NEWS-SIGNAL.md)) is bullish for a long or bearish for a short. A neutral or opposite reading, or no reading, means no trade.
6. **Entry:** at market, at the live price after the close, as the other strategies do.
7. **Stop:** 1.5 ATR from the close, rounded away from the entry.
8. **Targets:** 2R and 3R from the entry, split 62.5% and 37.5% (the money plan's 50/30 shares, rescaled for two targets).
9. **Risk:** the risk engine decides, as for every trade. A strategy no study has covered gets the smallest share (D045): a quarter of the account's risk per trade. That is 0.5% of the 100 USDT Binance demo budget (0.5 USDT), and 0.25% in the 1,000 USDT paper money plan.
10. **One trade per coin**, as the plan already enforces. A coin with a position or a waiting entry takes no new signal.

Python computes every price. Claude only labels the news stories. News alone cannot open a trade, because the price move must come first.

## What Is Measured

- **Context, run once after this registration:** the price rules alone (1 to 4 and 6 to 8, without the news check) on the first six coins, 2020 to 2025-11-01, in the shared simulator with stressed costs. This measures what strong moves did without the news filter. It is not a test of the strategy, because there is no labelled news history to backtest with. It does not stop the strategy, which trades by the owner's choice.
- **The test:** forward results of the strategy itself, in R per trade, from the paper money plan, which records every fill.

## Decision Rule

- **Stop rule:** after 30 closed trades in the paper money plan, the strategy is removed from both accounts if its mean R is below zero with 95% confidence (bootstrap). Removing it needs no further decision.
- **Raising its share** needs its own pre-registered study under D045. Good early results never raise it automatically.
- **Report:** at 30 and at 60 closed trades, the mean R, win rate and costs, beside the same coins' 1H pattern strategy over the same period.

## Limits

- **Delay:** news reaches the system about 35 minutes after publication, and is labelled within minutes. A move and its news can arrive in either order. The 12-hour reading window lets news from earlier in the day confirm a move now.
- **Coverage:** most coins have no labelled news most of the time, so the strategy will trade mostly BTC and ETH, and rarely.
- **Planted text:** a planted or wrong story can make a reading agree with a move. It cannot start a trade without the move. Every trade still goes through the risk engine.
- **No backtest of the news part:** results are forward only, on test funds and paper.

## Results

### Context: the price rules alone, run once on 2026-11-11

Without the news check, on the first six coins from 2020 to 2025-11-01, in the shared simulator. Report: [news-move-price-only.md](reports/news-move-price-only.md). Simulated results.

| Coin | Trades | Mean R | Win rate | Mean R at stressed costs |
|---|---|---|---|---|
| BTCUSDT | 780 | −0.047 | 35% | −0.115 |
| ETHUSDT | 1,073 | +0.088 | 38% | −0.125 |
| SOLUSDT | 601 | +0.040 | 37% | +0.030 |
| XRPUSDT | 538 | +0.004 | 36% | −0.021 |
| BNBUSDT | 741 | +0.005 | 35% | −0.020 |
| DOGEUSDT | 822 | −0.015 | 35% | −0.110 |

- **Pooled, at normal costs:** 4,555 trades, mean +0.017R a trade, 95% interval −0.028 to +0.059. No edge.
- **At stressed costs:** 1,114 trades, mean −0.060R, interval −0.148 to +0.027. Fewer trades pass at stressed costs, because the 2:1 rule after costs refuses more of them.
- **Reading:** strong 1H moves alone did not continue on average. Any edge has to come from the news check, which is the hypothesis. As registered, this context does not stop the strategy.

### The test

Forward results, not yet available.
