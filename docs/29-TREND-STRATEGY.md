# Daily Trend Strategy

Date: 2026-11-04
Status: Pre-registered before any run. Results are added below once, without changing the rules.

## Why This Strategy

Trend following, also called time-series momentum, is the most widely documented trading effect across markets. Moskowitz, Ooi and Pedersen (2012) found it in 58 futures markets over decades. Liu and Tsyvinski (2021) found strong time-series momentum in cryptocurrency returns, and Hudson and Urquhart (2021) found technical rules profitable on major coins.

It differs from the 1H pattern breakouts: it is slower, it lets winners run instead of taking fixed targets, and it can stay short through a falling market.

## Rules

The Turtle traders' System 1, unchanged, on daily candles of BTC and ETH perpetuals:

| Part | Rule |
|---|---|
| Entry | A daily close above the highest high, or below the lowest low, of the previous 20 days. Market order at the next open |
| Stop | 2 × ATR(20) from the entry |
| Exit | A trailing stop at the lowest low (for longs) or highest high (for shorts) of the last 10 days, moved at each daily close and never loosened |
| Profit cap | 10R. It exists so the 2:1 rule can read the trade, and exits are expected to come from the trailing stop. For a short whose 10R would pass zero, as on cheap, volatile coins, the cap is the lowest price, one tick. Added 2026-11-07; it never applied to BTC or ETH |
| Positions | One per coin. Signals during an open trade are ignored |
| Risk and costs | 1% risk, leverage 1, the same fees, spread, slippage and real funding as the pattern strategy. Fills on 15M candles |

The trailing stop needed a new simulator capability: a stop can be tightened at a candle close and takes effect from the next candle. It can never move against the trade. Golden tests cover it.

## Hypothesis and Test

**Hypothesis.** A close beyond the prior 20-day range starts moves that the 10-day trailing exit captures well enough to pay for 2 ATR stops and costs, and better than random entries with the same stops and exit.

- One trial, with the rules above. Nothing is tuned.
- Period 2020-01-01 to 2025-11-01, before the holdout, with walk-forward folds for reporting.
- Costs at 1× and 2×.
- Benchmarks: buy and hold, and 20 seeded runs of random days and directions using the same stops, cap and trailing exit.
- **The holdout is not used.** It is already known to have been a strong falling year, which would flatter a trend strategy designed after seeing it. Evidence after 2025-11-01 comes from forward paper trading only.

## Limits

- Trend following wins rarely and big: many small losses and a few large gains. A sample of about 100 trades leaves wide intervals.
- Rules from a famous system were chosen with hindsight about that system's success, which is a mild selection bias.
- BTC and ETH were chosen with hindsight.

## Sources

- Moskowitz, Ooi and Pedersen, "Time Series Momentum", *Journal of Financial Economics* (2012)
- Liu and Tsyvinski, "Risks and Returns of Cryptocurrency", *Review of Financial Studies* (2021)
- Hudson and Urquhart, "Technical trading and cryptocurrencies", *Annals of Operations Research* (2021), see [26-PATTERN-RESEARCH.md](26-PATTERN-RESEARCH.md)
- Curtis Faith, *Way of the Turtle* (2007), for the System 1 rules

## Results

Run once on 2026-11-04, with the rules above unchanged. Simulated results. A profitable backtest is not proof of future profitability. Reports: [BTC](reports/trend-backtest-btc.md), [ETH](reports/trend-backtest-eth.md).

| 2020-01-01 to 2025-11-01, normal costs | BTC | ETH |
|---|---|---|
| Trades | 71 | 68 |
| Net P/L on 10,000 | +3,857 | +3,390 |
| Expectancy, with 95% interval | +0.50R, +0.01 to +1.07 | +0.46R, -0.02 to +1.02 |
| Profit factor | 1.84 | 1.85 |
| Maximum drawdown | 5.0% | 7.3% |
| Expectancy at 2× costs | +0.48R | +0.45R |
| Random entries with the same exits | +0.14R mean, 95th percentile +0.39R | +0.20R mean, 95th percentile +0.52R |
| Walk-forward test folds | 37 trades, +0.24R | 37 trades, -0.01R |

What this says:

- It beats the pattern strategy on every measure, and double costs barely touch it because it trades rarely.
- BTC beat 95% of the random-entry runs. ETH did not.
- 2020 alone made 72% of BTC's profit and 78% of ETH's. From 2021 on, results were modest, and the out-of-sample folds were weak.
- Longs made money and shorts lost on both coins.
- Several strategies have now been tested, so a borderline interval like BTC's is not proof.

Decision: no rule changes. It runs forward in paper trading beside the pattern strategy, and its first real evidence will come from there.

Correction, 2026-11-10: these runs charged no funding from 2020 to early 2023, because those stored rates have no mark price (docs/10, costs). With funding charged, BTC made +0.44R a trade (-0.03 to +0.98) and ETH +0.37R (-0.07 to +0.89), as in the corrected six-coin study (docs/33). The reports above are kept as they were run.
