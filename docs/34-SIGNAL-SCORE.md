# Signal Score Study

Date: 2026-11-10
Status: Pre-registered on 2026-11-10, before any run of these conditions on any data. This document is committed to `develop` before the run, so the order can be checked in Git. Results will be added below the line "Results" after one run, and nothing above it changes.

## Why This Study

The money plan (D045) splits risk by tested evidence per strategy, but every signal from one strategy gets the same share. The owner asked for more money on the signals with the most potential, and for Python to become more accurate before Claude is added. Python's current setup score is mostly fixed numbers (`trade_signals/quality.py`), so it measures nothing.

This study tests one simple score: a few facts known at the signal, each with a reason fixed in advance and an equal weight. If weak signals earned clearly less than strong ones in history, the money plan halves the risk on weak signals. The owner chose on 2026-11-10 that a passing score may only lower risk on weak signals, never raise it above 1%.

Hypothesis, stated before any test: signals that go with the coin's long-term trend, with Bitcoin's long-term trend, with rising volume, and against crowded funding earn more per trade than signals with two or more of these against them. This is an idea to test, not a claim that it works.

## Already Seen

Results known before this registration, from these strategies on this history:

- Direction: longs made money and shorts lost for both strategies on BTC and ETH (docs/27, docs/29), and for the daily trend on XRP ([trend-backtest-xrp.md](reports/trend-backtest-xrp.md)).
- Pattern breakout on BTC and ETH by daily ADX and by volatility rank, where the most volatile quarter lost. A rule built on it failed the holdout (D037), so volatility is not a condition here.
- Daily trend on BTC and ETH by year: 2020 made most of the profit (docs/29).
- Per-coin results on all six coins, in the first and the corrected run of docs/33.

No result has been seen by long-term trend, Bitcoin's trend, volume or funding. The first two conditions lean with the market's direction, which links them to the known long and short result. Check 4 of the decision rule exists for that reason.

## Conditions

Each is read from candles and funding known when the signal's setup candle closed, and is either for the trade, against it, or unknown.

| Condition | For a long | For a short | Reason |
|---|---|---|---|
| Coin's long-term trend | The last closed daily close is above the mean of the last 200 daily closes | Below that mean | Time-series momentum: assets trending over the past year tend to keep going (Moskowitz, Ooi and Pedersen, 2012), and long-term trend filters are common in trend following |
| Bitcoin's long-term trend | The same test on BTCUSDT's daily candles | The same, below | Crypto coins move largely with Bitcoin, the market's main common factor. It does not apply to BTCUSDT's own trades |
| Volume | The signal candle's volume is at least the mean of the 20 candles before it, on the strategy's setup timeframe: 1H for the pattern, 1D for the trend | The same | Breakouts on heavier volume have held better in chart pattern studies (Bulkowski). The pattern strategy only ranks patterns by volume today, and filters nothing |
| Funding | The mean funding rate of the last 24 hours is at most the median rate of the last 90 days | At least that median | High funding means leveraged longs are paying to stay in, so the long side is crowded, and low funding means the short side is. Evidence for this is mixed. Each coin is compared with its own history, because their usual rates differ |

A condition is unknown before 200 daily candles, 21 setup candles, or 90 days of funding exist, or when no funding was paid in the last 24 hours.

**Score.** A signal is **weak** when two or more of its conditions are against it, and **strong** otherwise. For BTCUSDT that means two of its three. A signal with any unknown condition is left out of every check and counted in the report.

## Test

- Strategies: `daily_trend` version 1 and `pattern_breakout` version 1, with the parameters that trade live, as in docs/33.
- Coins: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT and DOGEUSDT perpetuals.
- Window: 2020-01-01, or the coin's first stored candle, to 2025-11-01, before the frozen holdout (D029). The holdout is not used.
- Engine, costs and fills: the corrected engine of docs/33, with funding charged in every year, at normal costs. 2× costs are reported, but not used for the decision.
- Each trade is scored at its signal time. Results are in R per trade, with the seeded bootstrap (2,000 runs, seed 7). The interval for a difference resamples each group on its own.

## Decision Rule

Fixed before the run. The score passes only if all six hold, pooled over both strategies and all six coins unless stated:

1. Strong signals' mean R minus weak signals' mean R is above zero, with its 95% interval above zero.
2. The difference is above zero for each strategy on its own.
3. The difference is above zero on the four coins added later, SOL, XRP, BNB and DOGE, pooled.
4. The difference is above zero among longs and among shorts, each on its own, so the score is more than the known long and short result.
5. The difference is above zero in at least 4 of the 6 years 2020 to 2025, by signal time. A year where either group has fewer than 5 trades counts as not above zero.
6. Sizing as the money plan would beats sizing without the score. Each trade is weighed by its strategy's share (daily trend 1, pattern breakout 0.5), and in the scored version a weak signal's share is halved. With trades in exit order, the scored version's total R divided by its largest fall in cumulative R must be higher than the unscored version's.

If the score passes, a weak signal from `daily_trend` or `pattern_breakout` in the `Portfolio` account gets half its strategy's share, stored with its assessment. A strong signal keeps its share. The 15M baseline is unchanged, because it cannot be tested on this history (docs/33). The risk engine still decides every trade, and no share rises above the account's 1%.

If any check fails, nothing changes in trading. A changed score would be a new trial with its own registration, tested on forward paper results rather than this history again.

Every condition's own result is also reported, for and against, as a description only. Six such slices invite fitting, so none of them can change trading.

## Limits Stated Before the Run

- The six coins move together, so their trades are not independent, and intervals are narrower than they should be.
- The conditions overlap: a coin's trend and Bitcoin's often agree.
- The coins were chosen in 2026 from those still trading, so they are survivors.
- Early trades are left out where a condition is unknown, so 2020 counts less than in docs/27 and docs/29.
- Funding before March 2023 is charged at the last 15M close, not the mark price (docs/10).
- A pass is not proof of future profit. It is a reason to size weak signals down, which forward paper results can then confirm or reject.

## Results

Not run yet.
