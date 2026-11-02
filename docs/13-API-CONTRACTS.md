# API Contracts

## REST Groups
- /api/v1/instruments
- /api/v1/market
- /api/v1/analysis
- /api/v1/news
- /api/v1/signals
- /api/v1/risk
- /api/v1/paper-trading
- /api/v1/backtests
- /api/v1/settings
- /api/v1/health

## WebSocket Events
- market.price
- market.candle
- market.status
- analysis.updated
- signal.created
- signal.updated
- signal.invalidated
- paper.position.updated
- news.received
- system.alert

## Rules
Use Pydantic request and response models.
Version public APIs.
Validate all inputs.
Use consistent error structures.
Implement authentication and authorization.
Document rate limits.
Never expose provider credentials.
Publish OpenAPI documentation.
