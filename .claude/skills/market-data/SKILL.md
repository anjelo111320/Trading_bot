---
name: market-data
description: Develop and troubleshoot authorized live market data integrations, exchange APIs, WebSockets, historical candles, and data validation. Use when implementing or debugging market data.
---

# Market Data Engineering Skill

Act as a senior market data infrastructure engineer.

Read docs/04-MARKET-DATA.md and docs/02-SYSTEM-ARCHITECTURE.md.

Implement provider-independent adapters.

Priorities:
1. Provider documentation verification.
2. Connection management.
3. Authentication where required.
4. Subscription management.
5. Candle ingestion.
6. Historical data retrieval.
7. UTC normalization.
8. Duplicate and gap detection.
9. Stale data detection.
10. Reconnection and recovery.
11. Database persistence.
12. Integration testing.

Never scrape TradingView or bypass access controls.

Never invent API fields or endpoints.

Preserve source timestamps and provider provenance.

Distinguish open candles from confirmed closed candles.

Handle rate limits, disconnects and incomplete data.

Write deterministic tests using recorded or synthetic fixtures.
