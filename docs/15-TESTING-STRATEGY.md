# Testing Strategy

## Unit Tests
- Indicator calculations.
- Candle validation.
- Pattern detection.
- Position sizing.
- Reward/risk.
- Fee calculations.
- Signal state transitions.

## Integration Tests
- Provider adapters.
- Database repositories.
- Redis event processing.
- Claude response validation.
- News ingestion.

## Backtesting Tests
- No future data access.
- Correct event ordering.
- Correct fills.
- Fees and slippage.
- Gap handling.
- Reproducibility.

## Security Tests
- Secret exposure.
- Authentication.
- Authorization.
- Injection.
- Rate limits.

## Acceptance
Every major module must have tests.
Use fixed test datasets.
Document expected numerical outputs.
Never use live market data as the only test fixture.
