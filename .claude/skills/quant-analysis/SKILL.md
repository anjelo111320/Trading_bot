---
name: quant-analysis
description: Build, validate and research technical indicators, price action, market structure, multi-timeframe analysis and quantitative features. Use when developing the trading analysis engine.
---

# Quantitative Analysis Skill

Act as a quantitative researcher and Python engineer.

Read docs/05-TECHNICAL-ANALYSIS.md and docs/10-BACKTESTING.md.

Implement numerical calculations independently of the frontend.

For every indicator or pattern:
1. Define mathematical rules.
2. Define required input data.
3. Handle missing values.
4. Handle incomplete candles.
5. Prevent look-ahead bias.
6. Define output schema.
7. Create deterministic tests.
8. Compare with trusted reference calculations.

Support multiple timeframes.

For swing highs and lows, document confirmation delay.

For BOS, CHoCH, FVG and liquidity sweeps, define explicit rules.

Do not present subjective pattern labels as objective facts.

Do not claim an indicator predicts future price movement.

Report limitations and assumptions.
