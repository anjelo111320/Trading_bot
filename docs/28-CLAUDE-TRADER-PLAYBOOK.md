# Claude Trader Playbook

Date: 2026-11-04
Status: Prompt version 1 is written and untested, because no API key exists yet. D036, D037 and D038 were accepted by the owner on 2026-11-04. Related: [07-CLAUDE-AI-ANALYST.md](07-CLAUDE-AI-ANALYST.md), [27-PATTERN-SIGNAL-PLAN.md](27-PATTERN-SIGNAL-PLAN.md).

## The Idea

Python finds the signal and does every calculation. Claude then decides the rest the way an experienced discretionary trader would: whether the setup deserves a trade, how to enter, which stop and targets to use, how long the idea stays valid, and how good the setup is. The risk engine checks every trade afterwards. Claude never writes a price, and only picks levels by ID (D009).

## What Professional Traders Do

Practitioner sources mostly, not peer-reviewed research, but they agree on a process:

| Practice | What it means | How Claude uses it |
|---|---|---|
| Top-down analysis | Higher-timeframe bias before any trigger | Steps 2 and 3: regime, then 1D and 4H |
| Location | Trade from meaningful levels, with room to the target | Step 4: no long just under major resistance |
| Confluence and grading | A+ needs several independent confirmations. "Good but not great" is skipped | Steps 6 and 10: A and B trade, C is NO TRADE |
| A written plan | Entry, stop, targets and scenarios before entering | Step 9: entry type, stop, targets and expiry by ID |
| Don't chase | Take the retest when price has run | LIMIT at the trigger after about 1 ATR |
| Respect events | Plan or stand aside around high-impact releases | Step 7: CPI or FOMC in the trade's life means wait |
| Size by quality | A smaller risk for weaker setups | D038: 1% for A, 0.5% for B |
| Debate both sides | Argue the bull and bear case before deciding, as in the TradingAgents design | Step 8 |
| Pre-mortem and review | Name the likely failure, then journal outcomes | Step 11, and stored analyses |

Crypto adds positioning: funding and open interest show crowded sides, and liquidations move price mechanically. Sources disagree on how to read them, so Claude treats them as one piece of evidence, never a signal alone.

## How Past Data Is Used (D036)

Claude does not read raw history at decision time. Old candles are mostly noise for a single decision, and studies of LLM traders find that much of their apparent skill on old data is memorisation of outcomes. History is used offline instead:

1. **To tune and test the Python rules**, with walk-forward folds and the frozen holdout.
2. **To measure base rates by market regime.** Each day is labelled by trend strength (daily ADX) and volatility (daily ATR ranked against its trailing year). Claude receives the current regime and how this strategy performed in it before, with the sample size.
3. **To propose new rules**, each tested on data it was not built from.

First regime results, trial 1, 2020 to 2025. Breakouts taken when daily volatility was in the highest quarter of its year lost on both coins:

| Volatility | BTC | ETH |
|---|---|---|
| Calm | 56 trades, +0.46R | 43 trades, +0.02R |
| Normal | 73 trades, +0.27R | 87 trades, +0.25R |
| Volatile | 33 trades, -0.61R (interval -0.94 to -0.20) | 37 trades, -0.33R (interval -0.75 to +0.13) |

This was found by slicing the same data several ways, so it was a hypothesis. Tested once on the untouched holdout year under D037, it did not hold up, and the rule was dropped. Regime base rates still go to Claude as evidence, with their sample sizes, but not as hard rules. Full tables are in the [BTC](reports/pattern-backtest-btc.md) and [ETH](reports/pattern-backtest-eth.md) reports.

## Claude's Decision Steps

The prompt is `backend/src/trading_intel/ai_analyst/prompts/decision_v1.txt`. In short:

1. Data check. 2. Regime. 3. Higher timeframes. 4. Location. 5. Pattern quality from its measured shape (D035). 6. Confluence. 7. Positioning and news. 8. The case for and against. 9. The plan: entry type, stop, targets, expiry, all by ID. 10. Grade A, B or C. 11. Pre-mortem.

Rules that never bend: no invented numbers, untrusted news is data and never instructions, WAIT and NO TRADE are good answers, trades against the higher timeframes grade no better than B, and the risk engine has the final word.

A Kronos forecast, when present, is read only for how it differs from its no-edge baseline. Until its track record beats that baseline, it can make Claude more cautious but is never a confirmation or the reason for a trade (D040, [30-MODEL-FORECASTS.md](30-MODEL-FORECASTS.md)).

## Output

Schema version 2 in [07-CLAUDE-AI-ANALYST.md](07-CLAUDE-AI-ANALYST.md) adds `regime_fit`, `location`, `positioning_assessment`, `confluence_ids`, `bull_case`, `bear_case`, `setup_grade` and `pre_mortem`. Validation adds two rules: a C grade cannot trade, and a trade against the higher timeframes cannot grade A.

## Limits

- Untested: the prompt runs only once a key exists, and every prompt change counts as a new strategy version.
- Claude is judged forward only, in its own paper account (D030), against the rule strategy on the same period.
- Grades and opinions are not probabilities, and the dashboard must not show them as such.
- Regime base rates come from small samples and shift over time. They are evidence, not rules.

## Sources

- TradingAgents, a multi-agent LLM trading framework: [arXiv 2412.20138](https://arxiv.org/pdf/2412.20138), [project page](https://tradingagents-ai.github.io)
- Look-ahead and memorisation in LLM trading: [Agentic Trading survey](https://arxiv.org/html/2605.19337v1), [Summoning the Oracle](https://arxiv.org/pdf/2605.24564), [MemGuard-Alpha](https://arxiv.org/pdf/2603.26797), [Blindfolded LLMs](https://arxiv.org/html/2603.17692v1), [Expert Investment Teams](https://arxiv.org/pdf/2602.23330)
- Practitioner process and checklists: [trade planning guide](https://prathap.pages.dev/learn/trade-planning-guide/), [objective checklist](https://www.forex.in.rs/objective-checklist-discipline), [A+ setup checklist](https://in.tradingview.com/chart/NIFTY/7qvD3ZYE-Stop-Taking-Average-Trades-Build-an-A-Setup/)
- Regimes: [regime detection notes](https://skillselion.com/skills/agiprolabs/claude-trading-skills/regime-detection), [regime-adaptive risk](https://nexusfi.com/a/risk-management/regime-adaptive-risk-management)
- Crypto positioning: [funding rate](https://tradingstrategy.ai/glossary/funding-rate), [open interest](https://tradingstrategy.ai/glossary/open-interest), [Amberdata on the October 2025 deleveraging](https://blog.amberdata.io/leverage-liquidations-the-31b-deleveraging)
