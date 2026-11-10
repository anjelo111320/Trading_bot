# Six-Coin Replication Study

Date: 2026-11-09
Status: Pre-registered at 09:45 UTC on 2026-11-09, before any run of these rules on SOL, BNB or DOGE, or of the pattern breakout on XRP. Run once, from 09:47 to 09:49 UTC the same day, with nothing tuned. The results are below. The registration was not committed before the run, so its order rests on this record and the session log.

## Why This Study

The two tested strategies were backtested only on BTC and ETH (docs/27, docs/29), but they already trade SOL, XRP, BNB and DOGE live. The owner asked for a money plan that puts more of the account on the strategies with the most potential (D045), and to make Python's engine more accurate before Claude is added. This study asks whether each strategy's backtest result holds on coins it was not first tested on. Its answer sets each strategy's share of risk in the money plan.

## Already Seen

- BTC and ETH results for both strategies, in docs/27 and docs/29.
- The daily trend on XRP was run once on 2026-11-07, outside any registration: 52 trades, +0.347R a trade, 95% interval -0.29 to +1.07 ([trend-backtest-xrp.md](reports/trend-backtest-xrp.md)). It is part of the pooled results and is marked as seen. The run is deterministic, so running it again gives the same numbers.

## Test

- Strategies: `pattern_breakout` version 1 and `daily_trend` version 1, with the default parameters that trade live today.
- Coins: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT and DOGEUSDT perpetuals.
- Window: 2020-01-01, or the coin's first stored candle, to 2025-11-01, before the frozen holdout (D029). The first candles are XRP 2020-01-06, BNB 2020-02-10, DOGE 2020-07-10 and SOL 2020-09-14.
- Engine, costs, fills and sizing as in docs/27 and docs/29: the shared backtest engine, 1× and 2× costs, 15M fills for the pattern and daily fills for the trend, 10,000 starting balance and 1% risk per trade. Each coin runs on its own.
- Pooled: all trades from the coins together, with expectancy in R and the project's seeded bootstrap 95% interval (2,000 runs, seed 7).
- Reported per coin and pooled: trades, win rate, expectancy, its interval, profit factor, maximum drawdown, and expectancy at 2× costs.

## Decision Rule

Fixed before the run, for each strategy at normal costs:

| Share of the account's 1% risk | When |
|---|---|
| Full, 1.0 | The pooled six-coin interval is above zero, the four new coins pooled have a positive mean, and the pooled mean at 2× costs is positive |
| Half, 0.5 | The pooled six-coin mean is positive, but a full-share condition fails |
| Quarter, 0.25 | The pooled six-coin mean is zero or below |

- The 15M rule baseline cannot be tested here. One-minute history before the holdout exists only for BTC and ETH, from 2025-06-25, and the baseline fills on one-minute candles. It gets the quarter share, labelled untested.
- On a coin where a strategy's own interval is entirely below zero, that strategy does not trade that coin in the money-plan account.
- Shares only lower risk below the account's limit, as grades do in D038. They are weights from evidence, not win probabilities.

## Limits Stated Before the Run

- The six coins move together, so their trades are not independent and the pooled interval is narrower than it should be.
- The coins were chosen in 2026 from those still trading, so they are survivors.
- Each coin has far fewer than the 200 out-of-sample trades the promotion gate needs (docs/27).
- A pass is not proof of future profit.

## Results

Run once on 2026-11-09 with `uv run python -m trading_intel.entrypoints.coin_replication` in `backend/`. Simulated results. A profitable backtest is not proof of future profitability. Full tables: [coin-replication.md](reports/coin-replication.md).

| Normal costs, expectancy in R | Pattern breakout | Daily trend |
|---|---|---|
| BTC, ETH (known before) | +0.16, +0.14 | +0.50, +0.46 |
| SOL | -0.01 | +0.55 |
| XRP | +0.23 | +0.35, seen before registration |
| BNB | +0.05 | +0.32 |
| DOGE | -0.07 | +0.50 |
| Four new coins pooled, 95% interval | +0.05, -0.12 to +0.22, 452 trades | +0.42, +0.09 to +0.77, 205 trades |
| Six coins pooled, 95% interval | +0.09, -0.03 to +0.22, 790 trades | +0.44, +0.20 to +0.70, 344 trades |
| Six coins pooled at 2× costs | +0.06 | +0.43 |

The decision rule gives:

| Strategy | Share of the account's 1% risk | Why |
|---|---|---|
| `daily_trend` | Full, 1.0 | All three conditions hold. It made money on every coin, and on the four new coins pooled its interval is above zero |
| `pattern_breakout` | Half, 0.5 | Positive pooled, but its interval includes zero. On the new coins it was close to zero, and lost on SOL and DOGE |
| `trend_break_baseline` | Quarter, 0.25 | Not testable before the holdout |

No coin is left out: no strategy lost on any coin with 95% confidence.

What this says:

- The daily trend replicated. Its edge on BTC and ETH was not specific to those two coins. Only XRP's result was known in advance, and the other three new coins pooled are also positive.
- The pattern breakout did not clearly replicate. Its BTC and ETH profit looks more like those coins' history than a general effect.
- docs/29 found that 2020 made most of the trend's BTC and ETH profit, and that its shorts lost. This study did not test either again, so both still apply.

## Correction, 2026-11-10

The run above charged no funding from 2020 to early 2023. Binance's funding history has no mark price before March 2023, and the loader dropped every event without one. In 2021, BTC longs paid about 30% of their size in funding over the year, so long trades in those years looked better than they were. The loader now uses the last 15M close as the mark (docs/10, costs), with a regression test.

The same study was run again at 01:52 UTC with nothing else changed. The first run's full tables are kept in [coin-replication-uncorrected.md](reports/coin-replication-uncorrected.md), and [coin-replication.md](reports/coin-replication.md) now holds the corrected run.

| Expectancy in R, 95% interval | First run | With funding |
|---|---|---|
| Daily trend, six coins | +0.44, +0.20 to +0.70 | +0.40, +0.16 to +0.65 |
| Daily trend, four new coins | +0.42, +0.09 to +0.77 | +0.39, +0.07 to +0.74 |
| Daily trend, six coins at 2× costs | +0.43 | +0.38 |
| Pattern breakout, six coins | +0.09, -0.03 to +0.22 | +0.08, -0.04 to +0.20 |
| Pattern breakout, four new coins | +0.05 | +0.04 |
| Pattern breakout, six coins at 2× costs | +0.06 | +0.05 |

The decision rule gives the same shares: daily trend full, pattern breakout half, no coin left out. The money plan is unchanged.
