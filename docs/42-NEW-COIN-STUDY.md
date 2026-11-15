# New Coins and the 15M Rule Study

Date: 2026-11-14
Status: Pre-registered on 2026-11-14 at 14:07 UTC, before any run of these strategies on ZEC, 1000PEPE, HYPE or NEAR, and before any run of the 15M rule or its loose copy on any coin, apart from the timing run below. Not committed before the run, because the owner commits. The order rests on this record and the session log, and the SHA-256 of this text above "Results" is recorded with the results.

## Why This Study

The owner saw entries that looked wrong on some coins and asked for a score per coin.
- **Paper trading, 2026-11-07 to 2026-11-14:** 1000PEPE closed 6 trades and won none, and ZEC closed 3 and won none. All nine came from the 15M rule (7) and its loose copy (2).
- **ZEC and 1000PEPE (D052), and HYPE and NEAR (D059), trade with no strategy tested on them.** docs/33 and docs/35 covered the six other coins.
- **The 15M rule and its loose copy have never been tested on any coin.** They fill on 1-minute candles, and 1-minute history before the holdout exists only for BTC and ETH, from 2025-06-25 (docs/33).

## Already Seen

- The live paper and Binance results above.
- **A timing run, made before this registration to size the test:** the 15M rule on 15-minute fills over September 2025 on BTC. Only its time and decision count were printed, 7.4 seconds for 2,880 decisions. No result was looked at.

## Test

**Part A: the tested strategies on the four new coins**
- Strategies: `daily_trend` version 1, `pattern_breakout` version 1 and `fvg_choch` version 1, with the parameters that trade live.
- Coins: ZECUSDT, 1000PEPEUSDT, HYPEUSDT and NEARUSDT perpetuals.
- Window: 2020-01-01, or the coin's first stored candle, to 2025-11-01, before the frozen holdout (D029). The first candles are ZEC 2020-02-05, NEAR 2020-10-15, 1000PEPE 2023-05-05 and HYPE 2025-05-30.
- Engine, fills, costs and sizing are as in docs/33 and docs/35: the shared backtest engine on 15-minute fills, 1x and 2x costs, a 10,000 starting balance, 1% risk per trade, and each coin alone.

**Part B: the 15M rule and its loose copy on all ten coins**
- Strategies: `trend_break_baseline` version 2 (a break of structure on the latest 15M candle) and `trend_break_loose` version 1 (a break on any of the last 3). Both use the parameters that trade live.
- Coins: the ten that trade, BTC, ETH, SOL, XRP, BNB, DOGE, ZEC, 1000PEPE, HYPE and NEAR.
- **Window: 2023-11-01, or the coin's first stored candle, to 2025-11-01.** That is two years, not six, because the rule decides at every 15M close at about 2.6 milliseconds a decision, and six years of ten coins would take about six hours.
- **Fills on 15-minute candles, not the 1-minute candles the rule was written for.**
  - The entry is the next candle's open, the price at the 15M close, like the live rule's entry at the live price (D044).
  - When a candle touches the stop and a target, the stop is taken first (D034). Where both fall in one 15-minute candle, this can only lower the result.
  - A signal while the strategy holds the coin is skipped, as live.
- Costs, sizing and accounts are as in Part A. A decision is made once per moment and reused at 2x costs; it reads only candles, never costs.

**Measured, in both parts:** per coin and pooled, the trades, win rate, expectancy in R with the project's seeded bootstrap 95% interval (2,000 runs, seed 7), profit factor, maximum drawdown and expectancy at 2x costs.

## Decision Rule

Fixed before the run:

| Result | Decision |
|---|---|
| A strategy's own 95% interval on a coin is entirely below zero, at 1x costs | That strategy stops trading that coin in the money plan and on both Binance accounts (`LEFT_OUT`), as in docs/33 |
| The ten-coin pooled interval of the 15M rule or its loose copy is entirely below zero | The result goes to the owner with a recommendation to switch that strategy off on every coin. The owner decides |
| A strategy's mean on a coin is below zero, but its interval includes zero | It keeps trading, and is listed for the owner |

- Shares of risk (docs/33, docs/35) do not change in this study.
- A pass is not a promotion: the 15M rule keeps its untested quarter share, because 15-minute fills are not its own test.

## Limits Stated Before the Run

- **Short histories.** HYPE has 5 months before the holdout, so its results are weak. 1000PEPE has 2.5 years in Part A.
- **Coarser fills.** 15-minute fills are coarser than the 1-minute fills the 15M rule needs, so Part B is an approximation.
- **How the new coins were chosen.** They were picked in November 2026 because they were trending then (D052, D059). That says nothing about 2020 to 2025.
- **Correlated coins.** The coins move together, so the pooled intervals are narrower than they should be.
- **Today's rules.** Instrument rules are today's snapshot, used for the whole window.
- **What a result means.** A pass is not proof of future profit. A failure rejects these strategies with these parameters on these coins only.

## Results

Run once on 2026-11-14, from 14:10 to 15:26 UTC, with `uv run python -m trading_intel.entrypoints.new_coin_study` in `backend/`, and nothing tuned. The SHA-256 of the text above this heading, taken at registration and again after the run, is `062dd3127dc6bd2647a6568e869f9ee128915c040bd46269adbd31c044d8f5ab`. Simulated results. A profitable backtest is not proof of future profitability. Full tables: [new-coin-study.md](reports/new-coin-study.md).

**Part A, normal costs, expectancy in R (95% interval, trades):**

| Coin | Daily trend | 1H pattern | 4H gap + 15M CHoCH |
|---|---|---|---|
| ZEC | +0.16 (-0.34 to +0.79, 52) | +0.04 (-0.31 to +0.41, 82) | +0.08 (-0.32 to +0.50, 56) |
| 1000PEPE | +0.36 (-0.35 to +1.27, 36) | +0.46 (-0.10 to +1.10, 45) | -0.19 (-0.57 to +0.25, 56) |
| HYPE | -0.64 (-0.91 to -0.37, 6), lost | -0.79 (-1.05 to -0.28, 13), lost | -0.04 (-0.89 to +1.05, 9) |
| NEAR | -0.14 (-0.43 to +0.16, 32) | -0.11 (-0.49 to +0.33, 67) | +0.48 (-0.08 to +1.03, 41) |
| Four coins pooled | +0.10 (-0.21 to +0.48, 126) | +0.03 (-0.20 to +0.27, 207) | +0.08 (-0.17 to +0.33, 162) |

**Part B, on 15-minute fills from 2023-11-01:**

| | The 15M rule | Its loose copy |
|---|---|---|
| Ten coins pooled | -0.046R (-0.13 to +0.04), 1,498 trades | -0.109R (-0.18 to -0.04), 2,095 trades |
| At 2x costs | -0.091R | -0.169R |
| Coins with a mean below zero | 8 of 10 | 8 of 10 |
| 1000PEPE | +0.094R (-0.12 to +0.31), 245 trades | +0.009R (-0.16 to +0.19), 349 trades |
| Lost with 95% confidence | none | DOGE (-0.18R), HYPE (-0.41R) |

The decision rule gives:

- **Left out** (`LEFT_OUT`, applied on 2026-11-14):
  - the daily trend and the 1H pattern on HYPE;
  - the loose copy on DOGE and HYPE.
  - HYPE's two results rest on 6 and 13 trades, as the limits warned.
- **To the owner, with a recommendation to switch it off on every coin:** the loose copy, whose ten-coin interval is below zero.
- **Listed for the owner, still trading:**
  - the 15M rule on eight coins;
  - the loose copy on six more;
  - the daily trend and the 1H pattern on NEAR;
  - the 4H gap strategy on 1000PEPE and HYPE.
  - Each has a mean below zero, but its interval includes zero.

What this says:

- **The loose copy lost money.** Accepting a break of structure up to three candles back added trades and lost about 0.11R on each, even before the coarser fills are counted.
- **The 15M rule has no edge shown.** It came to -0.05R a trade, with an interval that includes zero, and it lost more at 2x costs. It trades at its untested quarter share.
- **1000PEPE's five straight live losses look like bad luck, not a broken coin.** That is five once a setup traded on several accounts counts once, as the Coins page counts (D068). On its two years of history, the 15M rule made +0.09R a trade on PEPE, among its best coins. At a win rate near one in three, losing five in a row happens about one time in seven.
- **The 15M rule was tested on 15-minute candles, not 1-minute ones.** Wherever a stop and a target fall in the same candle, the stop is taken first, so the coarser candles can only lower its result. A test on 1-minute history would settle it, but that history before the holdout exists only for BTC and ETH.

**The owner's decisions, 2026-11-15 (D070):**
- **The loose copy is switched off on every coin,** as recommended.
- **The 15M rule keeps trading** at its quarter share, as the rule says.
