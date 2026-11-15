# Profit Lock Study

Date: 2026-11-15
Status: Pre-registered on 2026-11-15 at 03:27 UTC, before any run of the lock on history. Not committed before the run, because the owner commits. The order rests on this record and the session log, and the SHA-256 of this text above "Results" is recorded with the results.

## Why This Study

The owner chose the profit lock (D066) and had it built for real money with no backtest first. The research report of 2026-11-14 and the exit rules study (docs/37) both expect a lock to change how results are spread more than their mean. This study measures the live rule on history.

On 2026-11-15 the owner asked for this test while away from the computer, with permission to make the code and safety decisions.

## Already Seen

- **docs/37:** breakeven at +1R changed results by -0.023R, -0.005R and -0.073R a trade on the three tested strategies. None of these was significant.
- **Live since 2026-11-14 07:20 UTC, five locks:** ETH went on to its target (+1.48 USDT), and SOL, BNB, XRP and DOGE closed at their locks.

## Rule

The live lock (`risk_management/profit_lock.py`), as it trades:
- **Trigger:** the best price after the entry candle is at least 1.5R beyond the entry fill.
- **Move:** the stop goes to 1R beyond the entry fill, rounded to the tick that keeps a little less, if that is tighter than the stop it holds. R is the planned entry to the first stop.
- **Timing:** it decides at every 15-minute fill close and acts from the next fill candle, as stop moves do (D039).
- The strategy's own stop, targets and trail are unchanged.

## Test

- **Strategies and windows:**
  - `daily_trend` version 1, `pattern_breakout` version 1 and `fvg_choch` version 1, from 2020-01-01 or the coin's first candle to 2025-11-01;
  - `trend_break_baseline` version 2, the 15M rule, from 2023-11-01 or the coin's first candle to 2025-11-01, as in docs/42.
- **Coins:** the ten that trade.
- **Same entries:**
  - Each strategy runs once through the backtest engine, and each filled trade is then replayed twice, with its own exits and with the lock.
  - A replay with no rule must match the engine exactly. Any mismatch voids the run.
- **Fills:** 15-minute candles. When a stop and a target fall in one candle, the stop is taken first (D034).
- **Costs:** 1x and 2x, with 10,000 per coin at 1% risk.
- **Measured:**
  - per strategy and pooled, the change in R per trade, the lock minus own exits, with its mean and a seeded bootstrap 95% interval (2,000 runs, seed 7);
  - the same mean at 2x costs;
  - how often the lock acted, and on those trades, the R it kept where it helped and gave up where it hurt;
  - the same, by coin.

## Decision Rule

Fixed before the run, for each strategy at 1x costs:

| Result | Decision |
|---|---|
| The 95% interval of the change is entirely below zero | The lock stops acting on that strategy's trades, because it loses money there. The owner gave standing permission to choose the safer design when money is at risk (D067) |
| The interval is entirely above zero | The lock stays: the evidence supports it |
| The interval includes zero | The lock stays, as the owner chose (D066) |

The owner is told every result and can reverse any decision.

## Limits Stated Before the Run

- **15-minute fills.** The live lock reads the mark price each minute; the test sees each 15-minute candle's extreme. So the test triggers at least as often as the live lock, and it cannot tell within a candle whether the stop or the lock's trigger came first.
- **The 15M rule's window.** It is tested on two years, on 15-minute fills.
- **Correlated coins.** The coins move together, so the intervals are narrower than they should be.
- **One set of values.** Only 1.5R and 1R are tested. A different lock is a new trial.

## Results

Run once on 2026-11-15, from 03:27 to 03:58 UTC, with `uv run python -m trading_intel.entrypoints.profit_lock_backtest` in `backend/`, and nothing tuned. The SHA-256 of the text above this heading, at registration and after the run, is `77ae0c3bd0b865b5acfae8c5fc3c299dbd0d9f812e95da3d944aeb9f397d8dfd`. All 6,093 replays with no rule matched the engine, so the comparisons are valid. Simulated results. A profitable backtest is not proof of future profitability. Full tables: [profit-lock.md](reports/profit-lock.md).

| Change in R per trade, 1x costs | Trades | Lock acted | Change | 95% interval | At 2x costs |
|---|---|---|---|---|---|
| `daily_trend` | 470 | 171 | -0.117 | -0.251 to +0.002 | -0.117 |
| `pattern_breakout` | 997 | 419 | -0.045 | -0.111 to +0.021 | -0.054 |
| `fvg_choch` | 417 | 169 | -0.015 | -0.093 to +0.064 | +0.008 |
| `trend_break_baseline` | 1,498 | 566 | -0.042 | -0.090 to +0.006 | -0.055 |
| All four pooled | 3,382 | 1,325 | -0.050 | -0.086 to -0.015 | -0.060 |

**The decision rule gives no change.** No strategy's own interval is entirely below zero, so the lock stays on all four, as the owner chose (D066).

What this says:

- **The lock lowered the mean on every strategy.** It acted on 39% of trades. Where it acted, it kept 724.7R on trades that would have done worse and gave up 894.1R on trades that went on to their targets or their trails.
- **Pooled, it costs about 0.05R a trade, with a 95% interval entirely below zero.** The pre-registered rule decides by strategy, not pooled, so this changes nothing by itself. It is reported to the owner with a recommendation to switch the lock off.
- **The daily trend lost most, -0.12R a trade,** as the research expected: a lock cuts the long trends its 10-day trail is built to ride.
- **The test sees each 15-minute candle's extreme, so it triggers at least as often as the live lock.** The live cost may be somewhat smaller, but nothing here suggests it is a gain.
