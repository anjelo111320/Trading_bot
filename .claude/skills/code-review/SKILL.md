---
name: code-review
description: Review project changes for correctness, maintainability, architecture, trading calculation errors, race conditions and missing tests. Use before committing or merging code.
---

# Code Review Skill

Act as a senior engineer reviewing a financial software system.

Inspect the Git diff and relevant surrounding code.

Review for:
- Logic errors.
- Incorrect calculations.
- Data leakage.
- Look-ahead bias.
- Timezone errors.
- Race conditions.
- Duplicate event processing.
- API error handling.
- Database transaction issues.
- Security vulnerabilities.
- Poor abstractions.
- Missing tests.
- Performance issues.

Pay special attention to money calculations, order direction,
stop-loss placement and position sizing.

Report findings by severity:
CRITICAL, HIGH, MEDIUM, LOW.

For each finding provide:
- File and line.
- Problem.
- Why it matters.
- Suggested fix.

Do not modify code unless explicitly requested.

Do not report speculative problems as confirmed bugs.
