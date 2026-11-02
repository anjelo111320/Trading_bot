# Requirements Traceability

Date: 2026-11-02

This maps every section of [21-PROJECT-BRIEF.md](21-PROJECT-BRIEF.md) to the design that covers it and the phase that builds it. "Designed" means specified, not implemented. **Nothing here is implemented yet.**

Phase numbers follow the proposed roadmap in [16-DEVELOPMENT-ROADMAP.md](16-DEVELOPMENT-ROADMAP.md).

## First Deliverables

| # | Deliverable | Location | Status |
|---|---|---|---|
| 1 | System architecture document | [02-SYSTEM-ARCHITECTURE.md](02-SYSTEM-ARCHITECTURE.md) | Draft for review |
| 2 | Technology selection document | [03-TECHNOLOGY-STACK.md](03-TECHNOLOGY-STACK.md) | Draft for review |
| 3 | Database schema | [12-DATABASE-DESIGN.md](12-DATABASE-DESIGN.md), [schema/schema-v0.sql](schema/schema-v0.sql) | Draft; loaded and constraint-tested on PostgreSQL 14 |
| 4 | API integration plan | [20-API-INTEGRATION-PLAN.md](20-API-INTEGRATION-PLAN.md) | Draft for review |
| 5 | Claude AI analysis design | [07-CLAUDE-AI-ANALYST.md](07-CLAUDE-AI-ANALYST.md) | Updated; D009 accepted |
| 6 | Risk calculation specification | [08-RISK-MANAGEMENT.md](08-RISK-MANAGEMENT.md) | Updated; examples computed |
| 7 | Backtesting methodology | [10-BACKTESTING.md](10-BACKTESTING.md) | Updated; D009 accepted |
| 8 | Security plan | [14-SECURITY.md](14-SECURITY.md) | Updated for local operation |
| 9 | Development roadmap | [16-DEVELOPMENT-ROADMAP.md](16-DEVELOPMENT-ROADMAP.md), [19-PHASE-0-1-PLAN.md](19-PHASE-0-1-PLAN.md) | Accepted order under D010 |
| 10 | Initial project folder structure | [23-PROJECT-STRUCTURE.md](23-PROJECT-STRUCTURE.md) | Draft for review |
| Added | AI cost strategy | [24-AI-COST-STRATEGY.md](24-AI-COST-STRATEGY.md) | Proposed under D025 |

## Coverage by Brief Section

| Brief section | Design | Phase | Open items |
|---|---|---|---|
| 1 Primary objective | All documents | 1 to 8 | None |
| 2 Market data | [04](04-MARKET-DATA.md), [20](20-API-INTEGRATION-PLAN.md), [19](19-PHASE-0-1-PLAN.md) | 1A, 1B | Owner to confirm Binance eligibility |
| 3 Technical analysis | [05](05-TECHNICAL-ANALYSIS.md), [23](23-PROJECT-STRUCTURE.md) | 2 | Detailed indicator spec at Phase 2 start |
| 4 Price action and structure | [05](05-TECHNICAL-ANALYSIS.md) | 2 | Each pattern needs written rules at Phase 2 start |
| 5 Multi-timeframe | [02](02-SYSTEM-ARCHITECTURE.md), [07](07-CLAUDE-AI-ANALYST.md), `timeframe_profiles` | 2 | None |
| 6 News intelligence | [06](06-NEWS-INTELLIGENCE.md), [07](07-CLAUDE-AI-ANALYST.md), [20](20-API-INTEGRATION-PLAN.md) | 6 | Vendor choice; no historical news source |
| 7 Claude analyst | [07](07-CLAUDE-AI-ANALYST.md) | 7 | None |
| 8 Recommendation engine | [07](07-CLAUDE-AI-ANALYST.md), [08](08-RISK-MANAGEMENT.md), [09](09-TRADE-SIGNALS.md) | 3, 7 | None |
| 9 Risk engine | [08](08-RISK-MANAGEMENT.md) | 3 | Proposed defaults need review |
| 10 Confidence | [07](07-CLAUDE-AI-ANALYST.md), [10](10-BACKTESTING.md) | 3, 4, 7 | Score weights at Phase 3 |
| 11 Real-time monitoring | [02](02-SYSTEM-ARCHITECTURE.md), [07](07-CLAUDE-AI-ANALYST.md) | 3, 5, 7 | Notification channel |
| 12 Dashboard | [23](23-PROJECT-STRUCTURE.md), [19](19-PHASE-0-1-PLAN.md) | 1A, 5, 6, 7, 8 | Visual design not yet produced |
| 13 Backtesting | [10](10-BACKTESTING.md) | 4 | Holdout date must be frozen before research |
| 14 Paper trading | [11](11-PAPER-TRADING.md), [10](10-BACKTESTING.md), [08](08-RISK-MANAGEMENT.md) | 5 | Shared simulator |
| 15 Database | [12](12-DATABASE-DESIGN.md), [schema](schema/schema-v0.sql) | Every phase | Repeat validation on PostgreSQL 18 |
| 16 Backend architecture | [02](02-SYSTEM-ARCHITECTURE.md), [23](23-PROJECT-STRUCTURE.md) | 0 onward | D011 |
| 17 Security and reliability | [14](14-SECURITY.md), [02](02-SYSTEM-ARCHITECTURE.md) | Every phase | D019 |
| 18 Cost optimization | [24](24-AI-COST-STRATEGY.md), [07](07-CLAUDE-AI-ANALYST.md) | 3, 6, 7 | Estimates to be replaced by measurements |
| 19 Methodology | [CLAUDE.md](../CLAUDE.md), [19](19-PHASE-0-1-PLAN.md) | Every phase | None |
| 20 First deliverables | This document | 0 | Owner review |
| 21 Final behaviour | All documents | 8 | Out-of-sample evidence comes only from later phases |

## Where the Brief Changed Earlier Plans

| Topic | Earlier | After the brief |
|---|---|---|
| Timeframes | Six | Seven, adding 30M. Roles are user-configurable |
| Derivatives data | Not planned | Funding, open interest and liquidations required when available, so Phase 1B is added |
| D008, meaning of SELL | Recommended long-only spot | Now recommends perpetuals, since the brief wants BUY and SELL, leverage and funding |
| D009, source of prices | Claude reviews or vetoes a deterministic setup | Claude is the main reasoning engine and selects from a Python level catalogue |
| Module names | `providers`, `marketdata`, `persistence` | Brief names: `data_providers`, `market_data`, `database` |
| Tables | `market_spread_1m`, `paper_accounts`, `technical_features` | `market_snapshots`, `trading_accounts`, `technical_indicators`, and new `trade_targets` |
| Models | One model | Two: stronger for reasoning, cheaper for classification |
| Triggers | Undefined | Defined by the brief; see the design |
| Providers considered | Binance, Bybit | OANDA and Interactive Brokers added, and deferred |

## Requirements Needing Care

These are requirements the design meets differently from a literal reading, so the owner can object.

| Requirement | Design | Reason |
|---|---|---|
| "Evaluates the system using historical data" | The rule baseline is backtested. Claude is evaluated forward only | Claude's training data contains those outcomes, so a historical test would leak the future |
| "Research and interpret relevant news" | Claude reads supplied, classified news and has no web access | Web access widens the prompt-injection risk, and the brief forbids claiming unchecked sources |
| "Generate a trade recommendation" with precise prices | Claude picks levels by ID, and Python supplies every price | The brief forbids invented numbers |
| "Calibrate probability estimates" | Shows "unavailable" until enough out-of-sample results exist, which may take a long time | The brief requires this label |
| "Liquidation data" | Stored as a sample | Binance sends at most one order per symbol per second, with no history |
| "Historical news" in backtests | First backtests exclude news | No affordable, cleanly licensed history was found |
| "Trigger analysis when" a candle closes, and so on | Every trigger runs, but Claude is called only after deterministic gates pass | Most candles hold no possible trade. An automatic NO_TRADE needs no AI spend |
| "Monitor live financial markets continuously" | Continuous while the computer is on. Gaps are repaired where possible, and reported | D007 runs it on the owner's computer first |
| "Survivorship bias" prevention | Declared as a limitation | BTC and ETH were chosen with hindsight |
