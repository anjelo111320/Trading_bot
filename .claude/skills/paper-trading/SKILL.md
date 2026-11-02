---
name: paper-trading
description: Implement and troubleshoot simulated trading accounts, positions, fills, stop-losses, take-profits and live performance tracking. Use when developing paper trading.
---

# Paper Trading Skill

Act as a trading simulation engineer.

Read docs/11-PAPER-TRADING.md.

Implement a simulated trading environment only.

Support:
- Simulated account balance.
- Positions.
- Entry simulation.
- Stop-loss.
- Multiple take-profit targets.
- Fees.
- Spread.
- Slippage.
- Funding where relevant.
- Realized P/L.
- Unrealized P/L.
- Trade history.

Define deterministic fill rules.

Handle price gaps and ambiguous candle execution conservatively.

Prevent duplicate fills.

Make position transitions auditable.

Clearly label all results as simulated.

Do not implement live order execution.
