# Project Overview

## Vision
Build a real-time AI trading intelligence platform combining market data,
technical analysis, financial news, quantitative research and AI reasoning.

## Core Pipeline
Market Data
-> Data Validation
-> Indicator Engine
-> Market Structure Engine
-> News Intelligence
-> Claude Analyst
-> Deterministic Risk Engine
-> Trade Recommendations
-> Paper Trading
-> Performance Evaluation

## Main Operating Modes
- Development with labelled synthetic data.
- Historical research with archived market data.
- Live analysis using authorized data.
- Paper trading using live market prices.

## Initial Scope
Start with cryptocurrency and one exchange provider.
Support BTC/USDT and ETH/USDT initially.
Simulated trades run on USDT-margined perpetuals. Spot provides long history.
For the owner's personal use, running on the owner's computer first.
Use 1m, 5m, 15m, 30m, 1h, 4h and 1d timeframes.

Master requirements: [21-PROJECT-BRIEF.md](21-PROJECT-BRIEF.md).

## Non-Goals
- Guaranteed profitable trading.
- Autonomous live order execution.
- Unauthorized data extraction.
- Unvalidated self-modifying trading strategies.

## Success Criteria
- Reliable market-data ingestion.
- Correct indicator calculations.
- Reproducible pattern detection.
- Validated AI output.
- Correct risk calculations.
- Reproducible backtesting.
- Reliable paper trading.
