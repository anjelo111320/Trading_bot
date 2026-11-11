# 4H Gap and 15M CHoCH Strategy

Date: 2026-11-10
Status: Pre-registered on 2026-11-10, before any code for these rules existed and before any run on any data. This document is committed to `develop` before the run, so the order can be checked in Git. Results will be added below the line "Results" after one run, and nothing above it changes.

## Why This Strategy

The owner asked whether the system has this setup, and to research and add it if not: find a fair value gap on 4H, go to 15M, and take the signal when a change of character (CHoCH) lines up with the gaps.

What the system had on 2026-11-10:

- Detectors for fair value gaps (FVG), order blocks, BOS and CHoCH on any timeframe, with written rules ([25-PATTERN-RULES.md](25-PATTERN-RULES.md)). They feed the level catalogue, where open gaps become `fvg_edge` levels, and Claude's evidence.
- No strategy that trades them. The 15M rule baseline enters on a 15M BOS with 1H and 4H agreeing, and never looks at gaps.

## Research

This is a setup from "Smart Money Concepts" (SMC) and ICT teaching. It has no single standard version. Descriptions agree on the outline:

1. **Bias from the higher timeframe.** The 4H structure sets the direction. Gaps are traded only in that direction.
2. **Zone.** A 4H fair value gap, a three-candle gap where candle 3 does not overlap candle 1, is an area where price may react when it returns.
3. **Confirmation.** When price pulls back into the 4H gap, the trader drops to a lower timeframe and waits for a CHoCH back in the bias direction: the lower timeframe's down-trend breaks upwards, for a long.
4. **Entry.** The move that makes the CHoCH often leaves its own small gap. The entry is a limit order on the return to that gap.
5. **Stop and target.** The stop sits beyond the pullback's extreme. Targets are the next swing or opposing level.

Sources differ on details: how a CHoCH is defined, whether the entry is at market or at the lower gap, and how old a gap may be. The rules below fix one version of each.

**Evidence.** No peer-reviewed study found for this note tests fair value gaps or CHoCH entries:

- A 2026 SSRN working paper by Mahadzva coded six ICT and SMC rules mechanically and tested them on intraday G10 currency pairs. Its abstract reports "no evidence that ICT/SMC concepts work as literally taught". The full paper could not be read for this note.
- StatOasis tested 45 variants of order blocks, fair value gaps, liquidity sweeps and optimal trade entry on daily US index ETFs, against a coin-flip baseline, without costs. One of 32 forward-return t-statistics cleared 2, and none of 648 backtests beat buy and hold.
- Vendor articles quote win rates above 60%, with no method that can be checked.
- This project's own history: gap edges are levels in the catalogue, and Phase 2 found many minor CHoCH events with a swing strength of 3 ([phase-2.md](reports/phase-2.md)).

So the setup is popular, written down clearly enough to code, and untested on crypto in any source found. That is a reason to test it, not to expect it to work.

## Rules

| Part | Rule |
|---|---|
| Setup | Each 15M close |
| Bias | The 4H swing trend, read from the last closed 4H candle as the other strategies read it: up for a long, down for a short |
| 4H gap | A 4H fair value gap in the bias direction, by the rule in docs/25, detected at a 4H close at most 30 days before this 15M close, and before the pullback's extreme candle opened |
| Gap still open | No 15M low at or below the gap's far edge (for a bullish gap, its bottom) from the gap's detection to this close. For a short, no 15M high at or above the top of a bearish gap |
| Trigger | A 15M CHoCH in the bias direction at this close, by the structure rules in docs/25: a close beyond the last confirmed swing while the 15M trend was the other way |
| Pullback | For a long, the lowest 15M low from the swing the CHoCH broke to this close. It must lie inside the 4H gap: above its bottom and at or below its top. For a short, the highest high, inside a bearish gap |
| 15M gap | A 15M fair value gap in the bias direction, whose first candle is at or after the pullback's extreme, detected by this close, and not filled by it. The most recent one is used. The close must be beyond its near edge, so the limit sits below the market for a long |
| Entry | Limit at the 15M gap's near edge, its top for a long. Valid for 8 15M candles. It fills only when price trades through by one tick (docs/10) |
| Stop | 0.25 15M ATR beyond the pullback's extreme, rounded away from the trade |
| Targets | Up to three catalogue levels at least 2R from the entry, from 400 15M candles. None means no trade |
| Positions | One per coin. Signals while an order or position is open are ignored |
| Risk and costs | 1% risk, leverage 1, and the same fees, spread, slippage and real funding as the other strategies. A limit fill pays the maker fee with no spread or slippage, by the existing rules in docs/10 |

Swings use the project's default strength of 3. Every value above was fixed before any run. Changing one makes a new trial.

### New fill rule, for limit entries

On the candle where a limit entry fills, only the stop is checked. A target in that candle is not counted, because price may have reached the target before the entry. This is the cautious reading of an unclear candle, as the other fill rules are. No current strategy uses limit entries, so no earlier result changes.

## Hypothesis and Test

**Hypothesis.** With the 4H trend agreeing, a 15M CHoCH that starts inside an open 4H fair value gap and leaves a 15M gap behind starts a move that pays for a 2:1 trade after costs, entering on the return to that 15M gap. It does better than random 15M entries with the same 4H trend and the same exits.

- One trial, with the values above. Nothing is tuned.
- Coins: BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, BNBUSDT and DOGEUSDT perpetuals, each in its own 10,000 account.
- Window: 2020-01-01, or the coin's first stored candle, to 2025-11-01, before the frozen holdout (D029). The holdout is not used.
- Fills on 15M candles, because one-minute history before the holdout exists only from mid-2025. When a stop and a target fall in the same 15M candle, the stop is taken first (D034).
- Costs at 1×, 1.5× and 2×.
- Pooled: all trades from the six coins together, with the seeded bootstrap 95% interval (2,000 runs, seed 7). Also the four coins SOL, XRP, BNB and DOGE pooled, as in docs/33.
- Benchmark: 20 seeded runs per coin of random 15M closes where the 4H trend is up or down, entering at market in that direction, with the stops and targets of the strategy's own trades in ATR and R. Each seed's trades are pooled across coins.
- Reported: trades, win rate, expectancy, its interval, profit factor and maximum drawdown per coin and pooled; walk-forward test folds; the promotion gate from docs/27 on the pooled test folds; a funnel of why each CHoCH did or did not become a trade; and results by year and side.

## Decision Rule

Fixed before the run:

| Result at normal costs | Decision |
|---|---|
| Pooled six-coin expectancy at zero or below | **Rejected.** It stays out of live trading, the paper loop and Claude's evidence. The code, tests and report stay so the result can be reproduced |
| Pooled six-coin expectancy above zero | It joins the money plan's `Portfolio` account (D045) at the share the docs/33 rule gives: full when the pooled interval is above zero, the four coins pooled are positive, and the pooled mean at 2× costs is positive, and half otherwise |

- A coin where it lost with 95% confidence is left out of the plan, as in docs/33.
- If it joins, the quant worker runs it at every 15M close, next to the 15M rule baseline, on all six coins, through the risk engine. The `Paper` and `Demo` accounts do not change. Live entries are limit orders filled by the shared simulator on one-minute candles.
- A pass is a small amount of evidence, not proof. The promotion gate from docs/27 is reported but does not decide. Forward paper results decide later.

## Limits Stated Before the Run

- SMC rules have no standard. This is one written version. A loss rejects this version, not every reading of the idea.
- 15M fills are coarse. A limit entry and a stop in the same 15M candle count as entered and stopped, which can only make results worse.
- A limit fill pays the maker fee and no spread, while the benchmark's market entries pay the taker fee, spread and slippage. That gives the strategy a small cost advantage over its benchmark.
- With a swing strength of 3, many 15M CHoCH events are minor.
- The six coins move together, they were chosen in 2026 from those still trading, and several strategies have now been tested on the same years. A borderline result is weak evidence.
- Live runs load about 35 days of 15M candles and 100 days of 4H candles. The 15M trend state comes from that window, which could differ from the full history right after a long quiet spell.

## Sources

- [25-PATTERN-RULES.md](25-PATTERN-RULES.md), for the fair value gap and CHoCH rules used here.
- Shepherd Mahadzva, "Smart Money or Costly Folklore? A Systematic Evaluation of ICT/Smart-Money-Concepts Trading Rules in G10 FX", SSRN working paper 7430998 (2026). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7430998
- StatOasis, "I Backtested ICT / Smart Money Concepts — What Survives". https://statoasis.com/overfit/research/ict-backtest-what-survives
- Quantum Algo, "Fair value gaps trading guide", for the higher and lower timeframe outline. https://www.quantum-algo.com/blog/fair-value-gaps-trading-guide/

## Results

Run once on 2026-11-10, from 14:28 to 14:31 UTC, with `uv run python -m trading_intel.entrypoints.fvg_choch_backtest` in `backend/`. The rules above were committed first, as `bd6090f`, and nothing was tuned. Simulated results. A profitable backtest is not proof of future profitability. Full tables: [fvg-choch.md](reports/fvg-choch.md).

| 2020 to 2025-11-01, expectancy in R | Result |
|---|---|
| Six coins pooled, normal costs | +0.020, 95% interval -0.18 to +0.23, 255 trades, profit factor 1.03 |
| Six coins at 1.5× and 2× costs | -0.065 and -0.144 |
| SOL, XRP, BNB and DOGE pooled | -0.012 |
| By coin | BTC +0.55 (26 trades), BNB +0.26, SOL +0.23, DOGE -0.05, ETH -0.13, XRP -0.43 |
| Longs, shorts | +0.17, -0.13 |
| Walk-forward test folds | 103 trades, +0.10R, 4 of 6 positive |
| Random 15M entries with the 4H trend and the same exits | mean -0.075R, 95th percentile +0.089R |

The decision rule gives a **half share**. The pooled mean is above zero, so the strategy joins the money plan; the interval includes zero and the 2× cost mean is negative, so it does not get the full share. No coin lost with 95% confidence, so none is left out.

What this says:

- The setup made almost nothing after costs. +0.02R a trade is indistinguishable from zero, and it turned negative at 1.5× costs. It did beat random with-trend entries with the same exits, so the gap and CHoCH filter picked better moments than chance, but not enough to pay well.
- Most trades ended at the stop: 187 of 255.
- Most CHoCH events were refused before any gap check: 22,152 went against the 4H trend, and 16,405 did not pull back into an open 4H gap.
- The rule was followed as written. It joins at half share because its rule says so, not because the evidence is strong. Forward paper results decide its future.

Decision: it joins the money plan's `Portfolio` account at a half share from 2026-11-10 (D049). Binance demo trading sends market entries only for now, so its limit orders are refused there with that reason. Since 2026-11-11 (D054) its limit entries trade on Binance demo too, waiting there with their stop and targets already placed.
