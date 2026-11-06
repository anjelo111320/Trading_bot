# Trend Pullback Strategy

Date: 2026-11-06
Status: Pre-registered before any run, then run once on 2026-11-06 and **rejected**. The results are added below without changing the rules.

## Why This Strategy

- The two strategies so far enter on strength: a chart-pattern breakout ([27-PATTERN-SIGNAL-PLAN.md](27-PATTERN-SIGNAL-PLAN.md)) and a 20-day breakout ([29-TREND-STRATEGY.md](29-TREND-STRATEGY.md)). Neither has a rule for a market that pulls back inside its trend.
- The pattern research concluded that candles are useful "as context and confirmation at a level that matters, not as stand-alone signals" ([26-PATTERN-RESEARCH.md](26-PATTERN-RESEARCH.md)). This strategy tests exactly that: a reversal candle counts only at a Python level, in the direction of both higher trends.
- Buying a pullback inside an established trend is a common discretionary setup, described for example in Raschke and Connors, *Street Smarts* (1995).
- It reuses Python's existing parts unchanged: the 4H and 1D swing trends, the candle signals, ATR, the level catalogue and the 2:1 target search. Nothing new is fitted.

## Rules

| Part | Rule |
|---|---|
| Setup | Each 1H close |
| Trend | 4H and 1D swing trends both up for a long, both down for a short, as the pattern strategy reads them |
| Trigger | A candle signal in the trend's direction detected at this close: an engulfing, a pin bar, or a trend candle pattern from `pattern_detection.candles` |
| Location | The candle's low, for a long, within 0.25 ATR of a support or swing low below the close in the catalogue at that close. For a short, its high within 0.25 ATR of a resistance or swing high above the close |
| Entry | Market at the next 1H open, valid for 4 candles, as in the pattern strategy |
| Stop | 0.25 ATR beyond the level or the candle's extreme, whichever is further |
| Targets | Up to three catalogue levels at least 2R away. None means no trade |
| Positions | One per coin. Signals during an open trade are ignored |
| Risk and costs | 1% risk, leverage 1, and the same fees, spread, slippage and real funding as the other strategies. Fills on 15M candles |

## Hypothesis and Test

**Hypothesis.** With the 4H and 1D trends agreeing, a with-trend reversal candle at a Python level starts a move that pays for a 2:1 trade after costs, and does better than random entries with the same trend filter and exits.

- One trial, with the values above. Nothing is tuned.
- Period 2020-01-01 to 2025-11-01, before the holdout (D029), on BTC and ETH perpetuals, with walk-forward folds for reporting.
- Costs at 1×, 1.5× and 2×.
- Benchmark: 20 seeded runs of random 1H closes where 4H and 1D agree, given the stops and targets of the strategy's own trades, as for the pattern strategy.
- Promotion gate, the same as in docs/27: at least 200 out-of-sample trades, an expectancy interval above zero, a profit factor above 1.2 at 1.5× costs, positive results in most folds, and a beat over the random benchmark's 95th percentile.
- The holdout is not used. If the gate is passed, evidence after 2025-11-01 comes from paper trading forward.

## Limits

- The trend reader and the catalogue were built for the pattern strategy. Using them here is a choice made before testing.
- Many candle signals form away from any level, so trades may be fewer than the gate needs.
- The idea was chosen on 2026-11-06, when ETH sat at support under an up-trend reading. That is hindsight about the kind of situation, not about any outcome, and the rules do not depend on it.
- Several strategies have now been tested on the same years, so a borderline result is weak evidence.

## Sources

- [26-PATTERN-RESEARCH.md](26-PATTERN-RESEARCH.md), section 2, for the evidence on candlestick patterns.
- Linda Bradford Raschke and Laurence Connors, *Street Smarts* (1995), for pullback entries in trends.

## Results

Run once on 2026-11-06, with the rules above unchanged and committed before the run. Simulated results. A profitable backtest is not proof of future profitability. Reports: [BTC](reports/pullback-backtest-btc.md), [ETH](reports/pullback-backtest-eth.md).

| 2020-01-01 to 2025-11-01, normal costs | BTC | ETH |
|---|---|---|
| Trades | 513 | 696 |
| Net P/L on 10,000 | -5,736 | -6,094 |
| Expectancy, with 95% interval | -0.18R, -0.31 to -0.03 | -0.14R, -0.26 to -0.01 |
| Profit factor | 0.78 | 0.83 |
| Maximum drawdown | 58% | 64% |
| Expectancy at 2× costs | -0.28R | -0.20R |
| Random with-trend entries, same exits | -0.005R mean, 95th percentile +0.058R | -0.063R mean, 95th percentile -0.008R |
| Walk-forward test folds | 199 trades, -0.14R, 2 of 6 positive | 307 trades, -0.20R, none positive |
| Promotion gate | 0 of 5 | 1 of 5, trade count only |

What this says:

- The hypothesis is rejected. Both coins lost money with 95% confidence, at every cost level, and did worse than random entries with the same trend filter and exits.
- Most trades ended at the stop: 405 of 513 on BTC and 550 of 696 on ETH. When a reversal candle formed at a level inside a trend, the level more often broke than held.
- The per-candle rows are small samples. Picking the candles that happened to do well would be fitting the past.

Decision: rejected. The strategy stays out of the live view, the paper loop and Claude's evidence. Its code and tests remain so the result can be reproduced.
