# Exit Rules Study

Date: 2026-11-11
Status: Pre-registered on 2026-11-11, before any code for these rules existed and before any run on any data. This document is committed to `develop` before the run, so the order can be checked in Git. Results will be added below the line "Results" after one run, and nothing above it changes.

## Why This Study

The owner asked for an AI that trades like a person: when a trade looks unlikely to reach its target, it should be able to take the current profit. Before any Claude call, the same idea is tested with fixed Python rules, for three reasons:

- Fixed rules can be tested on 2020 to 2025. Claude cannot be, because the model may remember what prices did next (docs/28).
- Taking profit early is the classic human mistake, the disposition effect. Our strategies earn from the few trades that reach 2R or more, so cutting winners can lower the average. It has to be measured.
- Whatever exits win here become the bar that an AI exit manager must beat in shadow mode.

## What Is Already Known

- The strategies' own results with their own exits: the daily trend (docs/29, docs/33), the 1H pattern breakout (docs/27, docs/33) and the 4H gap and 15M CHoCH strategy (docs/35). In docs/35, 187 of 255 trades ended at the stop.
- No exit rule below has been run on any of these strategies or coins before this document.

## Rules

Each rule is added on top of a strategy's own stop, targets and, for the daily trend, its 10-day trailing stop. A rule decides at the close of a setup candle, from candles closed by then, and acts from the next fill candle, as stop moves already do (D039).

| Rule | What it does |
|---|---|
| `breakeven` | Once price has reached +1R beyond the entry fill, the stop moves to breakeven after costs: the entry fill plus, in the trade's direction, half the spread, the stop slippage and two taker fees, rounded to the tick away from the entry. A stop there nets about zero |
| `stall_exit` | Before the first target fills: if the setup candle closes at least +0.5R beyond the entry fill, and the best price since entry was set 6 or more setup candles ago, the whole open position closes at market at the next fill candle's open. It pays the taker fee, half the spread and the slippage, like a stop |
| `swing_trail` | Once price has reached +1R, the stop moves to the latest confirmed swing low on the setup timeframe for a long, or swing high for a short, with the project's swing strength of 3, whenever that is tighter |

Definitions:

- **R** is the planned risk per unit: the distance from the planned entry to the first stop, as in every report.
- **Reached +1R** means the best high for a long, or low for a short, of the fill candles after the entry candle, up to this close. The entry candle is left out, because part of it may have traded before the entry.
- **Best price set N setup candles ago** counts setup closes since the best price last improved.
- **Setup candles:** 1D for the daily trend, 1H for the pattern breakout, 15M for the gap strategy.
- A stop only ever tightens. A stop moved beyond the market fills at the next candle's open, by the existing gap rule (docs/10).

Every value above was fixed before any run. Changing one makes a new trial.

### New fill rule, for exits at market

An exit decided at a close fills at the next fill candle's open, with the costs of a stop: the taker fee, half the spread and the slippage. That candle's stop and targets are not checked, because the position is gone at its open. No current strategy uses this, so no earlier result changes.

## Test

- **Strategies:** `daily_trend`, `pattern_breakout` and `fvg_choch`, with the parameters that trade live. The 15M rule baseline cannot be tested on this history (docs/33) and is left out.
- **Coins:** BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT and DOGEUSDT perpetuals, each in its own 10,000 account at 1% risk.
- **Window:** 2020-01-01, or the coin's first stored candle, to 2025-11-01, before the frozen holdout (D029). The holdout is not used.
- **Fills** on 15M candles, as in docs/33 and docs/35. When a stop and a target fall in the same candle, the stop is taken first (D034).
- **Costs** at 1× and 2×.
- **Same entries.** Each strategy runs once with its own exits, through the backtest engine, as in the earlier studies. Each filled trade is then replayed through the shared simulator with each rule added. A replay with no rule must reproduce every trade exactly. Any mismatch voids the run until it is fixed.
- **Measured:** the change in R per trade, rule minus own exits, on the same trade. Pooled six-coin mean, with seeded bootstrap intervals at 95% and at 99.4% (2,000 runs, seed 7). 99.4% is 95% shared across the 9 strategy and rule pairs (Bonferroni). Also: the same mean at 2× costs, and on SOL, XRP, BNB and DOGE pooled.
- **Also reported:** how often each rule acted; on those trades, the R saved where the trade would have hit its stop and the R given up where it would have reached a target; by coin.

## Decision Rule

Fixed before the run:

| Result | Decision |
|---|---|
| For a strategy, a rule passes when, at the same time: the pooled six-coin mean change is above zero at 1× costs with its 99.4% interval above zero; the mean change is above zero at 2× costs; and the mean change is above zero on the four coins pooled | Adopted for that strategy in the money plan's `Portfolio` account and on Binance demo |
| More than one rule passes for a strategy | The one with the larger pooled mean change. Combinations need a new trial |
| No rule passes | The strategy keeps its own exits |

- A pass does not change a strategy's share of risk (docs/33).
- The `Paper` and `Demo` accounts keep the strategies' own exits, so the two can be compared on live results.
- The exits each strategy ends up with are the bar for an AI exit manager in shadow mode.

## AI Check Counts

A planning number for the token estimate. No decision depends on it.

During the replays with no rule, at each 15M fill close while a trade is open, these checks are counted:

| Check | Counted when |
|---|---|
| Stall past +1R | The best price has reached +1R and has not improved for 8 15M candles. Once, until a new best |
| Rejected near a target | A 15M candle's high for a long, or low for a short, comes within 0.25R of the next target without trading through it, and the candle closes at least 0.5R back from that extreme. Once per target |
| Volatility jump | A 15M candle's range is at least 3 times the median range of the 96 15M candles before it. At most once every 8 candles |

A CHoCH against the trade, news and economic events are not counted. They need more code or have no stored history, so the count is a lower bound. Reported: checks per trade and per open trade-day.

## Limits Stated Before the Run

- Entries are held fixed. An earlier exit could free a coin for its next signal sooner. That effect is not measured.
- 15M fills are coarse. A market exit at the next open uses the backtest costs, and a real exit in a fast market could be worse.
- The rules come from common trading practice, not from these data. One set of values is tested. A rejection rejects these values, not every version of the idea.
- The six coins move together, they were chosen in 2026 from those still trading, and several strategies have been tested on these years. A borderline result is weak evidence.

## Sources

- [10-BACKTESTING.md](10-BACKTESTING.md), for the fill rules, and D039 in [17-DECISIONS.md](17-DECISIONS.md), for stop moves from the next candle.
- [33-COIN-REPLICATION.md](33-COIN-REPLICATION.md) and [35-FVG-CHOCH-STRATEGY.md](35-FVG-CHOCH-STRATEGY.md), for the strategies' own results.
- Ouyang and Sui, "Dissecting AI Trading: Behavioral Finance and Market Bubbles", arXiv 2604.18373 (2026), on LLM agents selling winners early. https://arxiv.org/abs/2604.18373
- Barton et al., "What LLM Trading Agents Actually Do in Production", arXiv 2609.05663 (2026), on agents giving back reached profit and fixed brackets doing better. https://arxiv.org/abs/2609.05663

## Results
