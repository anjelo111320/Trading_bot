# AI Exit Manager, Shadow Mode

Date: 2026-11-11
Status: Accepted by the owner on 2026-11-11 ("start"), as step 2 after [37-EXIT-RULES.md](37-EXIT-RULES.md). **Shadow mode only:** Claude's advice is stored and scored, and never changes a trade. Model: Claude Haiku 5.5, the owner's choice for now. Decision D051.

## What It Does

Python watches every open paper trade at each 15M close. When one of the checks below fires, Python asks Claude one short question: hold the trade, take the profit now, or move the stop to breakeven? The answer is stored with exactly what Claude was shown.

When the trade closes, Python replays it from its start through the shared simulator on the stored 1M candles, with the advice applied at the moment it was given. The difference in R between that replay and the trade's real result is the advice's score.

## Rules That Never Bend

- **Shadow only.** No order, stop or paper fill changes because of Claude. Letting it act needs a new decision, after it has been scored.
- **Claude never sets a price.** It picks one of three actions. The breakeven stop is computed by Python with the docs/37 rule.
- **It can only lower risk.** There is no action to widen a stop, add to a trade, reverse it or change leverage.
- **Strict schema.** An answer that is not exactly one action and one sentence is stored as invalid, and counts as no advice.
- **Budget first.** The shared daily limit for all Claude calls, $3 (docs/24), is checked before every call. The provider spend limit in the Anthropic Console is the backstop.
- **No key, still counted.** Without `ANTHROPIC_API_KEY`, every check is still recorded, as "not asked", so the real number of checks is known before anything is spent.

## Checks

The same price checks as in docs/37, measured there at about 2 per open trade-day.

| Check | Fires at a 15M close when |
|---|---|
| Stall past +1R | The best price after the entry minute has reached +1R, and it was set 2 hours or more ago. Once per new best |
| Rejected near a target | The 15M candle's high for a long, or low for a short, came within 0.25R of the next target without trading through it, and the candle closed 0.5R or more back. Once per target |
| Volatility jump | The 15M candle's range is 3 times or more the median range of the 96 15M candles before it. At most once every 2 hours per trade |

Checks that fire on the same trade at the same close share one call. A CHoCH against the trade, news and economic events are not checks yet.

## What Claude Receives

One compact block of Python's numbers, inside the instructions' fixed format:

- The coin, strategy, side and account.
- The entry, stop and targets, with each one's distance in R, and how many targets have filled.
- The price now, the best and worst since entry in R, how long ago the best was, and how long the trade has been open.
- The last 8 15M candles and the last 6 1H candles, in R from the entry.
- Which checks fired.
- What docs/37 measured for this strategy: fixed rules that took profit early lost R overall.

Every number comes from stored, closed candles. The instructions are cached, so several trades checked at the same close pay for them once.

## Scoring

| Advice | Replayed as |
|---|---|
| Hold | The trade's own result, a change of zero |
| Take the profit now | The whole open position exits at the next 1M open after the close, with a stop's costs (docs/10) |
| Stop to breakeven | The stop moves to breakeven from the next candle, as every stop move does (D039) |

The change is the R with the advice minus the R with the trade's own exits, on the same simulator, candles and costs. After about 50 scored answers that were not "hold", the results are reported to the owner, with their interval. Only then can a decision let Claude act, and then on one account, with the others kept as the comparison.

## Cost

A call is about 2,300 input and 450 output tokens, about $0.0005 on Haiku 5.5. At about 20 calls a day, that is about $0.30 a month. `max_tokens` is 1,024, so one reply costs at most about $0.0008. The first week's stored usage replaces these estimates.

## Accounts

All three paper accounts: `Paper`, `Demo` and `Portfolio`. Not Binance demo: Binance does not yet report back the fills of the stops and targets it holds, so a review there could not be scored. Its trades come from the same strategies as `Portfolio`.

## Limits

- Haiku 5.5 is the smallest model. Shadow scoring is what tells whether it is good enough.
- A check runs at a 15M close, so a move inside 15 minutes is seen late.
- Scores rest on paper fills, with the backtests' cost assumptions.
- Claude's answers cannot be reproduced exactly, so the raw reply is stored.
