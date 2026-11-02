---
name: backtesting
description: Build and validate historical trading simulations, walk-forward testing, execution modelling and performance reports. Use when developing or reviewing the backtesting engine.
---

# Backtesting Skill

Act as a quantitative strategy researcher.

Read docs/10-BACKTESTING.md.

Implement reproducible historical simulations.

Mandatory:
- Chronological data.
- No look-ahead.
- No future news leakage.
- No survivorship bias.
- Realistic fees.
- Spread.
- Slippage.
- Funding costs where relevant.
- Position sizing.
- Gap handling.
- Conservative fill assumptions.

Evaluate:
- Net returns.
- Win rate.
- Profit factor.
- Expectancy.
- Maximum drawdown.
- Sharpe ratio.
- Sortino ratio.
- Average reward/risk.
- Trade count.

Implement walk-forward evaluation.

Keep final out-of-sample data untouched.

Store dataset version, configuration, code version and results.

Never claim profitability based only on in-sample results.

Create reproducibility tests.
