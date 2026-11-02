---
name: risk-engine
description: Implement and audit deterministic trading risk calculations, entry validation, stop-loss, take-profit, position sizing, fees and exposure controls. Use when developing trading risk management.
---

# Risk Management Skill

Act as a quantitative risk engineer.

Read docs/08-RISK-MANAGEMENT.md and docs/09-TRADE-SIGNALS.md.

All calculations must be deterministic.

Implement:
- Direction validation.
- Entry validation.
- Stop-loss validation.
- Take-profit validation.
- Position sizing.
- Contract specifications.
- Quantity precision.
- Minimum notional.
- Fee calculation.
- Spread and slippage.
- Reward/risk.
- Daily loss limits.
- Portfolio exposure.
- Duplicate signal protection.
- Signal expiry.

Use Decimal or appropriate fixed-precision arithmetic for financial values.

Do not assume all assets use the same contract model.

Reject invalid recommendations with explicit reasons.

Never silently adjust an invalid stop-loss.

Never allow Claude to override risk constraints.

Create boundary tests for every calculation.
