---
name: claude-analyst
description: Design, implement and evaluate the Claude-powered financial market analyst, structured prompts, evidence-grounded reasoning and API cost optimization. Use when developing AI trade analysis.
---

# Claude Analyst Skill

Act as an AI engineer and quantitative market researcher.

Read docs/07-CLAUDE-AI-ANALYST.md and docs/09-TRADE-SIGNALS.md.

Claude is a reasoning layer, not the source of market truth.

Implement:
1. Versioned system prompts.
2. Structured input construction.
3. Multi-timeframe context.
4. Technical evidence.
5. News evidence.
6. Conflict detection.
7. BUY, SELL, WAIT and NO_TRADE decisions.
8. Structured response validation.
9. Evidence references.
10. Invalidation conditions.
11. Signal expiry.
12. Token and cost tracking.

Require explicit timestamps and data freshness.

Never allow invented prices or indicators.

Never accept arbitrary numerical values without validation.

Use a strict Pydantic schema.

Never treat model confidence as a calibrated win probability.

Do not allow Claude to bypass the risk engine.

Do not send every tick to the API.

Test malformed JSON, missing data, conflicting evidence and API failures.
