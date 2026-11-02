# Phase 3 Completion Report

Date: 2026-11-02
Status: Exit gate met.

## Exit Gate

| Gate | Result | Evidence |
|---|---|---|
| Worked examples reproduced | Passed | Examples A, B and C match the specification to every stated digit |
| All rejection codes tested | Passed | All 28, and a test fails if a new code has no test |
| Leverage never changes size or risk | Passed | Property test |
| Risk never exceeds the budget | Passed | Property test, 150 generated cases |
| Independent check | Passed | A separate exact-fraction calculation agrees with Example A |
| Risk engine cannot import AI or storage | Passed | Enforced by import rules |

## Built

- Risk engine for spot and linear perpetuals, with profiles capped by hard ceilings.
- Level catalogue, rule baseline, quality score and signal lifecycle.
- Signal service, which stores every proposal, approved or rejected, with its reasons.
- In-app alerts as rows in `alerts`. Telegram is not built, and needs a bot token.

## Decisions Made Here

- The quality score weights are starting points with no evidence behind them yet. In the signal service, three of the seven inputs are fixed at 0.5 until the service computes them from indicators, so the score is only partly informative today.
- Fee schedules were seeded from public sources, and need rechecking against Binance's live table.

## Limits

- The exposure default of 100% of equity rejected many real signals, because tight stops need more size. It was left unchanged, since loosening a safety limit is an owner decision.
- `is_countertrend` is not set by the baseline, because it only trades with the trend.
